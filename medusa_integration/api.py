import requests
import frappe
import json
from medusa_integration.constants import get_headers, get_url
from medusa_integration.utils import send_request
from datetime import datetime, timedelta
from alfarsi_erpnext.alfarsi_erpnext.customer import fetch_standard_price

@frappe.whitelist(allow_guest=True)
def create_lead():
	data = json.loads(frappe.request.data)
	lead = frappe.get_doc({
		"doctype": "Lead",
		"medusa_id": data.get("id"),
		"first_name": data.get("first_name"),
		"last_name": data.get("last_name"),
		"email_id": data.get("email"),
		"mobile_no": data.get("mobile"),
		"phone": data.get("phone"),
		"source": "Alfarsi Website",
		"status": "Lead",
		"company_name": data.get("organization_name"),
		"custom_address_line1": data.get("address_line_1"),
		"custom_address_line2": data.get("address_line_2"),
		"city": data.get("city"),
		"state": data.get("state"),
		"country": data.get("country"),
		"custom_pincode": data.get("pin_code"),
		"t_c_acceptance": data.get("t_c_acceptance"),
		"offers_agreement": data.get("offers_agreement"),
	})
	lead.insert(ignore_permissions=True)
	return {"message": ("Lead created successfully"), "Lead ID": lead.name}

@frappe.whitelist(allow_guest=True)
def update_existing_customer():
	try:
		data = json.loads(frappe.request.data)
		customer_id = data.get("erp_customer_id")
		
		customer = frappe.get_doc("Customer", customer_id)
		
		customer.medusa_id = data.get("id")
		customer.email_id = data.get("email_id")
		customer.mobile_no = data.get("mobile_no")
		customer.t_c_acceptance = data.get("t_c_acceptance")
		customer.offers_agreement = data.get("offers_agreement")
		
		customer.save(ignore_permissions=True)
		
		return ("Customer updated successfully")
	except frappe.DoesNotExistError:
		return {"error": f"Customer with ID '{customer_id}' does not exist."}
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Update Existing Customer Error")
		return {"error": str(e)}

@frappe.whitelist(allow_guest=True)
def create_opportunity():
	data = json.loads(frappe.request.data)
	medusa_id = data.get("customer_id")
	form = data.get("form")

	lead = frappe.get_value("Lead", {"medusa_id": medusa_id}, "name")

	opportunity_type = "Sales" if form == "Setup Clinic" else "Support"
	sales_stage = "Prospecting" if form == "Setup Clinic" else "Needs Analysis"
	expected_closing = datetime.today() + timedelta(days=30)

	opportunity = frappe.get_doc({
		"doctype": "Opportunity",
		"opportunity_type": opportunity_type,
		"sales_stage": sales_stage,
		"opportunity_from": "Lead",
		"source": "Advertisement",
		"expected_closing": expected_closing.date(),
		"party_name": lead,
		"status": "Open",
	})

	opportunity.insert(ignore_permissions=True)
	return {"message": ("Opportunity created successfully"), "Opportunity ID": opportunity.name}

@frappe.whitelist(allow_guest=True)
def create_quotation():
	data = json.loads(frappe.request.data)
	medusa_id = data.get("customer_id")
	items = data.get("items", [])
	valid_till = datetime.today() + timedelta(days=30)

	customer_details = frappe.get_value("Customer", {"medusa_id": medusa_id}, ["name", "customer_name"], as_dict=True)
	if customer_details:
		party_name = customer_details.name
		quotation_to = "Customer"
		title = customer_details.customer_name
	else:
		lead = frappe.get_value("Lead", {"medusa_id": medusa_id}, "name")
		if not lead:
			frappe.throw(f"Lead or Customer with medusa_id {medusa_id} not found.")
		party_name = lead
		quotation_to = "Lead"
		title = "Unapproved Lead"

	quote = frappe.get_doc({
		"doctype": "Quotation",
		"title": title,
		"order_type": "Sales",
		"quotation_to": quotation_to,
		"party_name": party_name,
		"medusa_draft_order_id": data.get("draft_order_id"),
		"medusa_quotation_id": data.get("quotation_id"),
		"valid_till": valid_till.date(),
		"from_ecommerce": 1,
		"items": [],
		"taxes": []
	})
	
	tax_summary = set()
	
	for item in items:
		variant_id = item.get("variant_id")
		quantity = item.get("quantity", 1)

		item_code = frappe.get_value("Website Item", {"medusa_variant_id": variant_id}, "item_code")
		if not item_code:
			return {"error": "Item not found for variant ID: {}".format(variant_id)}

		quote.append("items", {
			"item_code": item_code,
			"qty": quantity,
		})
		
		item_doc = frappe.get_doc("Item", item_code)
		item_taxes = item_doc.taxes or []
		
		for tax in item_taxes:
			tax_template = tax.item_tax_template
			if tax_template:
				tax_template_doc = frappe.get_doc("Item Tax Template", tax_template)
				for template_tax in tax_template_doc.taxes:
					account_head = template_tax.tax_type
					if account_head not in tax_summary:
						tax_summary.add(account_head)
						quote.append("taxes", {
							"charge_type": "On Net Total",
							"account_head": account_head,
							"description": account_head
						})

	quote.insert(ignore_permissions=True)

	serialized_items = json.dumps(
	[ 
		{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in item.as_dict().items()} 
		for item in quote.items
	]
)

	try:
		prices = fetch_standard_price(
			items=serialized_items,
			price_list=quote.selling_price_list,
			party=quote.party_name,
			quotation_to=quote.quotation_to
		)

		for item in quote.items:
			item_code = item.item_code
			item.standard_price = prices.get(item_code, 0)
			item.rate = prices.get(f"{item_code}-negotiated", 0)

		quote.save(ignore_permissions=True)
	except Exception as e:
		return {"error": f"Failed to fetch and update standard prices: {str(e)}"}

	return {"message": "Quotation created successfully", "quotationId": quote.name}

@frappe.whitelist(allow_guest=True)
def create_sales_order():
	try:
		data = json.loads(frappe.request.data)
		items = data.get("items", [])
		delivery_date = datetime.today() + timedelta(days=1)

		customer = data.get("customer")

		company = data.get("company")

		sales_order = frappe.new_doc("Sales Order")
		sales_order.update(
			{
			"customer": customer,
			"delivery_date": delivery_date,
			"order_type": "Sales",
			"company": company,
			"workflow_state": "Draft",
			"from_ecommerce": 1,
			"items": [],
			"conversion_rate": 1.0
		})

		for item in items:
			item_code = item.get("item_code")
			qty = item.get("qty")
			rate = item.get("rate")
			amount = rate * qty

			sales_order.append("items", {
				"item_code": item_code,
				"qty": qty,
				"rate": rate,
				"base_net_rate": rate,
				"amount": amount,
				"conversion_factor": 1.0,
			})

		sales_order.insert(ignore_permissions=True)

		return {"message": "Sales Order created successfully", "Sales Order ID": sales_order.name}

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Sales Order Creation Error")
		return {"error": str(e)}

@frappe.whitelist(allow_guest=True)
def update_quotation():
	data = json.loads(frappe.request.data)
	medusa_quotation_id = data.get("quotation_id")
	quotation_id = frappe.get_value("Quotation", {"medusa_quotation_id": medusa_quotation_id}, "name")
	approval = data.get("approval")
	custom_is_courier_required = data.get("is_courier_required")
	custom_location_and_contact_no = data.get("location_and_contact_no")
	items = data.get("items", [])
	unapproved_items = data.get("unapproved_items", [])
	medusa_order_id = data.get("order_id")
	custom_increased_items = data.get("increased_items", [])

	try:
		quote = frappe.get_doc("Quotation", quotation_id)
	except frappe.DoesNotExistError:
		return {"error": "Quotation not found for ID: {}".format(quotation_id)}
	
	if approval == "Partially Approved" or "Partially Approved with Increased Deal":
		quote.status = "Open"
		quote.workflow_state = approval
		quote.order_type = "Sales"

		tax_summary = set()

		quote.items = []
		quote.taxes = []
		for item in items:
			variant_id = item.get("variant_id")
			item_code = frappe.get_value("Website Item", {"medusa_variant_id": variant_id}, "item_code")
			if not item_code:
				return {"error": "Item not found for variant ID: {}".format(variant_id)}

			quote.append("items", {
				"item_code": item_code,
				"qty": item.get("quantity"),
				"rate": item.get("rate"),
				"amount": item.get("amount")
			})

			item_doc = frappe.get_doc("Item", item_code)
			item_taxes = item_doc.taxes or []
			for tax in item_taxes:
				tax_template = tax.item_tax_template
				if tax_template:
					tax_template_doc = frappe.get_doc("Item Tax Template", tax_template)
					for template_tax in tax_template_doc.taxes:
						account_head = template_tax.tax_type
						if account_head not in tax_summary:
							tax_summary.add(account_head)
							quote.append("taxes", {
								"charge_type": "On Net Total",
								"account_head": account_head,
								"description": account_head
							})

		quote.unapproved_items = []
		for item in unapproved_items:
			variant_id = item.get("variant_id")
			item_details = frappe.get_value("Website Item", {"medusa_variant_id": variant_id}, ["item_code", "stock_uom"], as_dict=True)
			quote.append("unapproved_items", {
				"item_code": item_details["item_code"],
				"qty": item.get("quantity"),
				"uom": item_details["stock_uom"],
				"rate": item.get("rate"),
				"amount": item.get("amount")
			})
		
		quote.custom_increased_items = []
		for item in custom_increased_items:
			variant_id = item.get("variant_id")
			item_details = frappe.get_value("Website Item", {"medusa_variant_id": variant_id}, ["item_code", "stock_uom"], as_dict=True)
			quote.append("custom_increased_items", {
				"item_code": item_details["item_code"],
				"old_quantity": item.get("old_quantity"),
				"new_quantity": item.get("new_quantity")
			})

	if approval == "Approved":
		quote.status = "Open"
		quote.workflow_state = "Approved"
		quote.order_type = "Sales"
		quote.medusa_order_id = medusa_order_id,
		quote.submit()
		if quote.quotation_to == "Customer":
			try:
				sales_order = frappe.call(
				"erpnext.selling.doctype.quotation.quotation.make_sales_order",
				source_name=quotation_id
				)

				sales_order.delivery_date = frappe.utils.add_days(frappe.utils.nowdate(), 1)
				if custom_is_courier_required:
					sales_order.custom_is_courier_required = custom_is_courier_required
					sales_order.custom_location_and_contact_no = custom_location_and_contact_no
				
				sales_order.flags.ignore_permissions = True
				sales_order.insert()
				sales_order.submit()
			except Exception as e:
				return {"error": "Failed to create Sales Order: {}".format(str(e))}
		quote.reload()
	
	if approval != "Rejected":
		quote.save(ignore_permissions=True)

	if approval == "Rejected":
		quote.cancel()

	return {"message": "Quotation updated successfully", "Quotation ID": quote.name}

@frappe.whitelist(allow_guest=True)
def update_address():
	try:
		data = frappe._dict(json.loads(frappe.request.data))
		customer_id = data.get("customer_id")

		if not customer_id:
			return {"error": "Customer ID is required."}

		address_id = frappe.db.get_value(
			"Dynamic Link",
			{
				"link_name": customer_id,
				"link_doctype": "Customer",
				"parenttype": "Address"
			},
			"parent"
		)

		if not address_id:
			return {"error": f"No address found for customer ID '{customer_id}'"}

		address_doc = frappe.get_doc("Address", address_id)

		fields_to_update = ["address_line1", "address_line2", "city", "state", "country", "pincode"]
		for field in fields_to_update:
			if data.get(field) is not None:
				setattr(address_doc, field, data.get(field))

		address_doc.save(ignore_permissions=True)

		return ("Address updated successfully")

	except frappe.DoesNotExistError:
		return {"error": f"Customer with ID '{customer_id}' or their address does not exist."}
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Update Address Error")
		return {"error": str(e)}

def export_website_item(self, method):
	item_group = frappe.get_doc("Item Group", self.item_group)

	if not item_group.medusa_id:
		export_item_group(item_group)

	origin_country = frappe.get_value("Item", {"item_code": self.item_code}, "country_of_origin")
	if origin_country:
		country_of_origin = frappe.get_value("Country", {"name": origin_country}, "code")
	country_code = country_of_origin.upper() if origin_country else None

	specifications = []
	if self.website_specifications:
		for spec in self.website_specifications:
			specifications.append({
				"label": spec.label,
				"description": spec.description
			})

	payload = {
		"title": self.web_item_name,
		"item_code": self.item_code,
		"discountable": False,
		"is_giftcard": False,
		"collection_id": item_group.medusa_id,
		"short_description": self.short_description,
		"description": self.web_long_description,
		"ranking": self.ranking,
		"status": "published" if self.published else "draft",
		"brand_name": self.brand,
		"origin_country": country_code,
		"metadata": {"UOM": self.stock_uom},
		"specifications": specifications
	}

	try:
		if get_url()[1] and not self.medusa_id:
			args = frappe._dict({
				"method": "POST",
				"url": f"{get_url()[0]}/admin/products",
				"headers": get_headers(with_token=True),
				"payload": json.dumps(payload),
				"throw_message": f"Error while exporting Website Item {self.name} to Medusa"
			})
			self.db_set("medusa_id", send_request(args).get("product").get("id"))
			medusa_var_id = create_medusa_variant(self.medusa_id, self.item_code, self.on_backorder, country_code)
			self.db_set("medusa_variant_id", medusa_var_id)
			print(self.name, " exported successfully")
	
	except frappe.ValidationError as e:
		if "Product with handle" in str(e) and "already exists" in str(e):
			print(f"Duplicate error for {self.name}: {str(e)}")
		else:
			raise e
	except Exception as e:
		print(f"Unexpected error while exporting {self.name}: {str(e)}")
		raise e

def update_website_item(self, method):
	def send_update_request(payload, throw_message):
		try:
			args = frappe._dict({
				"method": "POST",
				"url": f"{get_url()[0]}/admin/products/{self.medusa_id}",
				"headers": get_headers(with_token=True),
				"payload": json.dumps(payload),
				"throw_message": throw_message
			})
			send_request(args)
			print(self.medusa_id, " updated successfully")
		except Exception as e:
			print(f"Unexpected error while updating {self.name}: {str(e)}")
			raise e
		
	if self.custom_skip_update_hook:
		frappe.db.set_value("Website Item", self.name, "custom_skip_update_hook", 0)
		return

	item_group = frappe.get_doc("Item Group", self.item_group)
	if not item_group.medusa_id:
		export_item_group(item_group)

	origin_country = frappe.get_value("Item", {"item_code": self.item_code}, "country_of_origin")
	if origin_country:
		country_of_origin = frappe.get_value("Country", {"name": origin_country}, "code")
	country_code = country_of_origin.upper() if origin_country else None
	
	specifications = []
	if self.website_specifications:
		for spec in self.website_specifications:
			if spec.label and spec.description:
				specifications.append({
					"label": spec.label,
					"description": spec.description
				})
	
	payload = {
		"title": self.web_item_name,
		"item_code": self.item_code,
		"discountable": False,
		"collection_id": item_group.medusa_id,
		"short_description": self.short_description,
		"description": self.web_long_description,
		"ranking": self.ranking,
		"status": "published" if self.published else "draft",
		"brand_name": self.brand,
		"origin_country": country_code,
		"metadata": {
			"UOM": self.stock_uom
		},
		"specifications": specifications
	}
	send_update_request(payload, f"Error while updating Website Item {self.name} in Medusa")

def website_item_validate(self, method):
	if not self.medusa_id:
		export_website_item(self, method)
	else:
		update_website_item(self, method)

def create_medusa_variant(product_id, item_code, backorder = False, country_code = None):	
	inventory_quantity = frappe.get_list('Bin', filters={'item_code': item_code}, fields='actual_qty', pluck='actual_qty')
	qty = int(sum(inventory_quantity))
	
	option_id = create_medusa_option(product_id)
	payload = json.dumps({
							"title": "Default",
							"material": None,
							"mid_code": None,
							"hs_code": None,
							"origin_country": country_code,
							"sku": None,
							"ean": None,
							"upc": None,
							"barcode": None,
							"inventory_quantity": qty, # Needs to be updated
							"manage_inventory": True,
							"allow_backorder": True if backorder else False,
							"weight": None,
							"width": None,
							"height": None,
							"length": None,
							"prices": [],
							"metadata": {},
							"options": [
								{
								"option_id": option_id,
								"value": "Default"
								}
							]
	})
	args = frappe._dict({
							"method" : "POST",
							"url" : f"{get_url()[0]}/admin/products/{product_id}/variants",
							"headers": get_headers(with_token=True),
							"payload": payload,
							"throw_message": f"Error while creating Item Variant for {product_id} in Medusa"
	})
	
	return send_request(args).get("product").get("variants")[0].get("id")

# def update_medusa_variant(product_id, variant_id, option_id):
# 	payload = json.dumps({
# 							"title": "Default",
# 							"material": None,
# 							"mid_code": None,
# 							"hs_code": None,
# 							"origin_country": "IN", # item.country_of_origin
# 							"sku": None,
# 							"ean": None,
# 							"upc": None,
# 							"barcode": None,
# 							"inventory_quantity": 0,
# 							"manage_inventory": True,
# 							"allow_backorder": True,
# 							"weight": None,
# 							"width": None,
# 							"height": None,
# 							"length": None,
# 							"prices": [],
# 							"metadata": {},
# 							"options": [
# 								{
# 								"option_id": option_id,
# 								"value": "Default"
# 								}
# 							]
# 	})
# 	args = frappe._dict({
# 							"method" : "POST",
# 							"url" : f"{get_url()[0]}/admin/products/{product_id}/variants/{variant_id}",
# 							"headers": get_headers(with_token=True),
# 							"payload": payload,
# 							"throw_message": "Error while updating Item Variant in Medusa"
# 	})

def create_medusa_option(product_id):
	payload = json.dumps({
			"title": "Default",
		})
	args = frappe._dict({
					"method" : "POST",
					"url" : f"{get_url()[0]}/admin/products/{product_id}/options",
					"headers": get_headers(with_token=True),
					"payload": payload,
					"throw_message": f"Error while creating Item Option for {product_id} in Medusa"
	})
	
	return send_request(args).get("product").get("options")[0].get("id")

def export_item_group(self):
	if get_url()[1] and not self.medusa_id:
		payload = json.dumps({
					"title": self.name,
					"metadata": {"parent_item_group": self.parent_item_group, "is_group": self.is_group}
		})
		args = frappe._dict({
		"method" : "POST",
		"url" : f"{get_url()[0]}/admin/collections",
		"headers": get_headers(with_token=True),
		"payload": payload,
		"throw_message": f"Error while exporting Item Group {self.name} to Medusa"
		})

		self.db_set("medusa_id", send_request(args).get("collection").get("id"))
		print(self.name, " exported successfully")
	
def create_medusa_price_list(self, called_manually=False):	
	medusa_variant_id = frappe.db.get_value("Website Item", {"item_code": self.item_code}, "medusa_variant_id")

	if not medusa_variant_id:
		print("No Website Item found for item code: ", self.item_code)
		return
	
	item_price = 0
	
	if called_manually:
		recent_item_price = frappe.db.sql("""
			SELECT 
				name, price_list_rate
			FROM 
				`tabItem Price`
			WHERE 
				item_code = %s
			ORDER BY 
				valid_from DESC
			LIMIT 1
		""", (self.item_code,), as_dict=True)

		if recent_item_price[0]['name'] != self.name:
			print(f"Skipping {self.name} as it is not the most recent Item Price of {self.item_code}")
			return

		item_price = recent_item_price[0]['price_list_rate']

	else:
		item_price = self.price_list_rate

	item_price = int(item_price * 1000)

	web_item_name = frappe.db.get_value("Website Item", {"item_code": self.item_code}, "web_item_name")

	if called_manually:
		starts_at = self.valid_from.isoformat() if self.valid_from else None
		ends_at = self.valid_upto.isoformat() if self.valid_upto else None
	else:
		starts_at = datetime.datetime.strptime(self.valid_from, "%Y-%m-%d").isoformat() if self.valid_from else None
		ends_at = datetime.datetime.strptime(self.valid_upto, "%Y-%m-%d").isoformat() if self.valid_upto else None

	
	payload = json.dumps({
		"name": web_item_name,
		"description": self.price_list,
		"type": "override",  # or "sale"
		"customer_groups": [],
		"status": "active",
		"starts_at": starts_at,
		"ends_at": ends_at,
		"prices": [
			{
				"amount": item_price,
				"variant_id": medusa_variant_id,
				"currency_code": self.currency.lower(),
			}
		]
	})
	
	if get_url()[1] and not self.medusa_id:
		args = frappe._dict({	
			"method" : "POST",
			"url" : f"{get_url()[0]}/admin/price-lists",
			"headers": get_headers(with_token=True),
			"payload": payload,
			"throw_message": f"Error while exporting Item Price {self.name} to Medusa"
		})
		response = send_request(args).get("price_list")
		self.db_set("medusa_id", response.get("id"))

		prices = response.get("prices", [])
		self.db_set("medusa_price_id", prices[0].get("id"))
		print(self.name, "exported successfully")
	
	if self.medusa_id and self.get_doc_before_save():
		payload = json.dumps({
			"prices": [
				{
					"id": self.medusa_price_id,
					"amount": item_price,
					"variant_id": medusa_variant_id,
					"currency_code": self.currency.lower(),
				}
			]
		})
		args = frappe._dict({	
			"method" : "POST",
			"url" : f"{get_url()[0]}/admin/price-lists/{self.medusa_id}",
			"headers": get_headers(with_token=True),
			"payload": payload,
			"throw_message": f"Error while updating Item Price {self.name} in Medusa"
		})
		send_request(args)

def create_medusa_customer(self, method):
	if get_url()[1] and not self.get_doc_before_save():
		def split_name(full_name):
			full_name = full_name.strip()
			if " " not in full_name:
				return full_name, "" 

			last_space_index = full_name.rfind(" ")
			first_name = full_name[:last_space_index]
			last_name = full_name[last_space_index + 1:]
			return first_name, last_name

		first_name, last_name = split_name(self.customer_name)
		payload = json.dumps({
			"first_name": first_name, # frappe.get_value("Contact", {"mobile_no": self.mobile_no}, "first_name"),
			"last_name": str(last_name),
			"email": self.email_id,
			"phone": self.mobile_no,
			"password": str(self.email_id) + str(self.mobile_no),
			})
		args = frappe._dict({
			"method" : "POST",
			"url" : f"{get_url()[0]}/admin/customers",
			"headers": get_headers(with_token=True),
			"payload": payload,
			"throw_message": f"Error while exporting Customer {self.name} to Medusa"
		})
		self.db_set("medusa_id", send_request(args).get("customer").get("id"))

@frappe.whitelist(allow_guest=True)
def fetch_all_customers(name=None):
	base_query = """
		SELECT 
			name, customer_name, email_id, mobile_no
		FROM 
			`tabCustomer`
		WHERE 
			medusa_id IS NULL
	"""

	if name:
		name_parts = name.split()
		conditions = " AND ".join([f"customer_name LIKE '%{part}%'" for part in name_parts])
		base_query += f" AND ({conditions})"

	customers = frappe.db.sql(base_query, as_dict=True)

	if not customers:
		return ("No relevant customers found")

	return customers

def file_validation_wrapper(self):
	namecheck(self)
	
	upload_image_to_medusa(self)

def upload_image_to_medusa(self):
	web_item = ""
	if self.attached_to_doctype == "Website Item":
		medusa_id = frappe.get_value("Website Item", {"name": self.attached_to_name}, "medusa_id")
		print("Website item Medusa ID: ", medusa_id)
		web_item = frappe.get_value("Website Item", {"name": self.attached_to_name}, "web_item_name")
		print("Web Item Name: ", web_item)
	elif self.attached_to_doctype == "Item":
		medusa_id = frappe.get_value("Item", {"item_name": self.attached_to_name}, "medusa_id")
		print("item Medusa ID: ", medusa_id)

	if medusa_id and self.attached_to_field not in ["image", "website_image"]:
		images = frappe.get_all("File", filters={
						"attached_to_doctype": self.attached_to_doctype,
						"attached_to_name": self.attached_to_name,
						"attached_to_field": ["not in", ["image", "website_image"]]
				})
		image_urls = []

		for image in images:
			doc = frappe.get_doc("File", image)
			image_path = doc.get_full_path()
			url = f"{get_url()[0]}/admin/uploads"
			headers = get_headers(with_token=True)
			headers.pop('Content-Type', None)  # Remove the Content-Type header to let requests set it
			payload = {}
			with open(image_path, 'rb') as image_file:
				files = {'files': (image_path, image_file, 'image/jpeg')}
				response = requests.post(url, headers=headers, data=payload, files=files)
				if response.status_code == 200:
					uploaded_image_url = response.json().get('uploads')[0].get('url')
					print("Image uploaded")
					print("Image URL: ",uploaded_image_url)
					image_urls.append(uploaded_image_url)
				else:
					frappe.throw("Failed to upload image to Medusa")

		attach_image_to_product(image_urls, medusa_id)
				
	elif medusa_id and self.attached_to_field in ["image", "website_image"]:
		image_url = ""
		image_path = self.get_full_path()
		url = f"{get_url()[0]}/admin/uploads"
		headers = get_headers(with_token=True)
		headers.pop('Content-Type', None)  # Remove the Content-Type header to let requests set it
		payload = {}
		with open(image_path, 'rb') as image_file:
			files = {'files': (image_path, image_file, 'image/jpeg')}
			response = requests.post(url, headers=headers, data=payload, files=files)
			if response.status_code == 200:
				uploaded_image_url = response.json().get('uploads')[0].get('url')
				print("Image uploaded")
				image_url = uploaded_image_url
			else:
				frappe.throw("Failed to upload image to Medusa")

		attach_thumbnail_to_product(image_url, medusa_id)

def attach_thumbnail_to_product(image_url, product_id):
	url = f"{get_url()[0]}/admin/products/{product_id}"
	headers = get_headers(with_token=True)
	payload = json.dumps({"thumbnail": image_url})

	args = frappe._dict({
		"method": "POST",
		"url": url,
		"headers": headers,
		"payload": payload,
		"throw_message": f"Error while attaching thumbnail {image_url} to the Medusa product {product_id}"
	})
	send_request(args)

def attach_image_to_product(image_url, product_id):
	url = f"{get_url()[0]}/admin/products/{product_id}"
	headers = get_headers(with_token=True)

	response = requests.get(url, headers=headers)

	existing_images = response.json().get("product", {}).get("images", [])
	existing_image_urls = [img.get("url") for img in existing_images if "url" in img]

	updated_image_urls = existing_image_urls + [image_url]

	updated_image_urls = list(set(updated_image_urls))

	payload = json.dumps({"images": updated_image_urls})

	args = frappe._dict({
		"method": "POST",
		"url": url,
		"headers": headers,
		"payload": payload,
		"throw_message": "Error while attaching image to the Medusa product"
	})
	send_request(args)
 
def export_image_to_medusa(self):
	medusa_id = frappe.get_value("Website Item", {"name": self.attached_to_name}, "medusa_id")

	if medusa_id:
		image_path = self.get_full_path()
		url = f"{get_url()[0]}/admin/uploads"
		headers = get_headers(with_token=True)
		headers.pop('Content-Type', None)
		payload = {}
		image_url = []

		with open(image_path, 'rb') as image_file:
			files = {'files': (image_path, image_file, 'image/jpeg')}
			response = requests.post(url, headers=headers, data=payload, files=files)

			if response.status_code == 200:
				uploaded_image_url = response.json().get('uploads')[0].get('url')
				print("Image uploaded")
				image_url.append(uploaded_image_url)

			else:
				frappe.throw("Failed to upload image to Medusa")

		attach_image_to_product(image_url, medusa_id)
		print("Completed image attach")
		self.db_set("medusa_id", medusa_id)

def namecheck(self):
	if ' ' in self.file_name:
		frappe.throw("Invalid name format!<br>File name cannot contain spaces")

def export_all_website_item():
	doctype = "Website Item"
	method = ""
	record = frappe.get_all(doctype)  # frappe.get_all(doctype, limit = 5)
	for r in record:
		doc = frappe.get_doc(doctype, r)
		if doc.published and not doc.medusa_id:
			try:
				print("Beginning to export: ", doc.name)
				export_website_item(doc, method)
			except frappe.ValidationError as e:
				print(f"Skipping {doc.name} due to error: {str(e)}")
			except Exception as e:
				print(f"Unexpected error while exporting {doc.name}: {str(e)}")
				raise e

def update_all_website_item(method = None):
	doctype = "Website Item"
	record = frappe.get_all(doctype)  # frappe.get_all(doctype, limit = 5)
	for r in record:
		doc = frappe.get_doc(doctype, r)
		if doc.medusa_id:
			try:
				print("Beginning to update: ", doc.name)
				update_website_item(doc, method)
			except frappe.ValidationError as e:
				print(f"Skipping {doc.name} due to error: {str(e)}")
			except Exception as e:
				print(f"Unexpected error while updating {doc.name}: {str(e)}")
				raise e

def export_all_item_groups():
	doctype = "Item Group"
	groups = frappe.get_all(doctype)  # frappe.get_all(doctype, limit = 5)
	for group in groups:
		doc = frappe.get_doc(doctype, group)
		if not doc.medusa_id:
			try:
				print("Beginning to export: ", doc.name)
				export_item_group(doc)
			except frappe.ValidationError as e:
				print(f"Skipping {doc.name} due to error: {str(e)}")
			except Exception as e:
				print(f"Unexpected error while exporting {doc.name}: {str(e)}")
				raise e

def export_all_website_images():
	doctype = "File"
	images = frappe.get_all(doctype, filters={
						"attached_to_doctype": "Website Item",
						"attached_to_field": ["in", ["image", "website_image"]]
				})
	for image in images:
		doc = frappe.get_doc(doctype, image)
		if not doc.medusa_id:
			try:
				print("Beginning to export: ", doc.name)
				export_image_to_medusa(doc)
			except frappe.ValidationError as e:
				print(f"Skipping {doc.name} due to error: {str(e)}")
			except Exception as e:
				print(f"Unexpected error while exporting {doc.name}: {str(e)}")
				raise e

def export_all_medusa_price_list():
	doctype = "Item Price"
	record = frappe.get_all(doctype)
	for r in record:
		doc = frappe.get_doc(doctype, r)
		is_diabled = frappe.get_value("Item", {"item_code": doc.item_code}, "disabled")
		if is_diabled:
			print(f"skipping {doc.name} due to disabled item {doc.item_code}")
			continue
		if not doc.medusa_id:
			try:
				print("Beginning to export: ", doc.name)
				create_medusa_price_list(doc, called_manually=True)
			except frappe.ValidationError as e:
				print(f"Skipping {doc.name} due to error: {str(e)}")
			except Exception as e:
				print(f"Unexpected error while exporting {doc.name}: {str(e)}")
				raise e

def clear_all_item_group_id(): #For Item Group
	item_groups = frappe.get_all("Item Group", filters={"medusa_id": ["!=", ""]}, fields=["name"])
	print(item_groups)
	
	for item_group in item_groups:
		frappe.db.set_value("Item Group", item_group.name, "medusa_id", "")

	frappe.db.commit()

def clear_all_website_item_id(): #For website items
	items = frappe.get_all("Website Item", filters={"medusa_id": ["!=", ""]}, fields=["name"])
	print(items)

	for item in items:
		frappe.db.set_value("Website Item", item.name, {"medusa_id": "", "medusa_variant_id": ""})

	frappe.db.commit()

def clear_all_website_image_id(): #For website images
	images = frappe.get_all("File", filters={"medusa_id": ["!=", ""]}, fields=["name"])
	print(images)

	for image in images:
		frappe.db.set_value("File", image.name, {"medusa_id": ""})

	frappe.db.commit()

def clear_all_item_price_id(): #For item price
	item_prices = frappe.get_all("Item Price", filters={"medusa_id": ["!=", ""]}, fields=["name"])
	print(item_prices)

	for item_price in item_prices:
		frappe.db.set_value("Item Price", item_price.name, {"medusa_id": "", "medusa_price_id": ""})

	frappe.db.commit()

def export_quotation(self, method):
	from erpnext.controllers.taxes_and_totals import get_itemised_tax_breakup_data

	quotation = frappe.get_doc("Quotation", self)

	medusa_id = frappe.get_value("Customer", {"name": quotation.party_name}, "medusa_id")
	if not medusa_id:
		medusa_id = frappe.get_value("Lead", {"name": quotation.party_name}, "medusa_id")

	tax_breakup = get_itemised_tax_breakup_data(quotation)

	payload = {
		"customer_id": medusa_id,
		"draft_order_id": quotation.medusa_draft_order_id,
		"erp_status": "Quote received",
		"erp_items": [],
		"erp_unaccepted_items": [],
		"erp_total_quantity": quotation.total_qty,
		"erp_total": quotation.total,
		"erp_net_total": quotation.net_total or 0,
		"erp_tax": [],
		"erp_total_taxes": quotation.total_taxes_and_charges or 0,
		"avail_delivery": quotation.get("delivery_available", False),
		"erp_delivery_charges": quotation.get("erp_delivery_charges", 2),
		"erp_grand_total": quotation.grand_total or 0,
		"erp_rounding_adjustments": quotation.rounding_adjustment or 0,
		"erp_discount_on": quotation.apply_discount_on,
		"erp_discount_percentage": quotation.additional_discount_percentage or 0,
		"erp_discount_amount": quotation.discount_amount or 0,
		"tax_breakup": tax_breakup,
	}

	for item in quotation.items:
		variant_id = frappe.get_value("Website Item", {"item_name": item.item_name}, "medusa_variant_id")
		payload["erp_items"].append({
			"item": variant_id,
			"item_code": item.item_code,
			"price": item.rate,
			"quantity": item.qty,
			"uom": item.uom,
			"amount": item.amount,
			"item_tax_template": item.item_tax_template
		})
	
	if quotation.unapproved_items:
		for item in quotation.unapproved_items:
			variant_id = frappe.get_value("Website Item", {"item_name": item.custom_item_name}, "medusa_variant_id")
			payload["erp_unaccepted_items"].append({
				"item": variant_id,
				"price": item.rate,
				"quantity": item.qty
			})

	for tax in quotation.taxes:
		payload["erp_tax"].append({
			"account_head": tax.account_head,
			"tax_rate": tax.rate or 0,
			"tax_amount": tax.tax_amount or 0
		})

	try:
		if quotation.medusa_quotation_id and quotation.medusa_draft_order_id:
			args = frappe._dict({
				"method": "POST",
				"url": f"{get_url()[0]}/store/quotation-update?quot_id={quotation.medusa_quotation_id}",
				"headers": get_headers(with_token=True),
				"payload": json.dumps(payload),
				"throw_message": f"Error while exporting Quotation {quotation.name} to Medusa"
			})
			response = send_request(args)

			if response.message == "Quotation updated successfully":
				print(f"Quotation {quotation.name} exported to Medusa successfully")
			else:
				print(f"Error: Quotation export failed for {quotation.name}: {response.get('error')}")
	   
	except Exception as e:
			print(f"Error exporting Quotation {quotation.name}: {str(e)}")
			raise e

def export_quotation_on_update(doc, method):
	if doc.workflow_state == "Ready for Customer Review" and doc.from_ecommerce == 1:
		try:
			export_quotation(doc.name, "")
			frappe.msgprint("Quotation price details sent to e-Commerce site successfully")
		except Exception as e:
			frappe.log_error(f"Failed to export Quotation {doc.name}: {str(e)}", "Quotation Export Error")
			print(f"Error exporting Quotation {doc.name}: {str(e)}")

@frappe.whitelist(allow_guest=True)
def export_sales_order(self, method): # Need to test
	sales_order = frappe.get_doc("Sales Order", self)

	customer_id = frappe.get_value("Customer", {"name": sales_order.customer}, "medusa_id") #Need to update
	if not customer_id:
		frappe.throw(f"Medusa Customer ID not found for Customer: {sales_order.customer}")
	# customer_id = "cus_01JEN21R04B3DK7DRFS2AVY8BR"

	payment_status = "Unpaid"
	
	sales_invoice_name = frappe.db.sql("""
		SELECT DISTINCT sii.parent 
		FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON sii.parent = si.name
		WHERE sii.sales_order = %s AND si.docstatus = 1
		LIMIT 1
	""", (sales_order.name), as_dict=True)

	if sales_invoice_name:
		invoice_status = frappe.get_value("Sales Invoice", sales_invoice_name[0].parent, "status")
		payment_status = invoice_status if invoice_status else "Unpaid"

	payload = {
		"customer_id": customer_id,
		"order_status": "Pending" if sales_order.state == "Draft" else sales_order.state,
		"payment_status":  payment_status,
	}

	try:
		if sales_order.medusa_order_id:
			args = frappe._dict({
				"method": "POST",
				"url": f"{get_url()[0]}/store/order-update?order_id={sales_order.medusa_order_id}",
				"headers": get_headers(with_token=True),
				"payload": json.dumps(payload),
				"throw_message": f"Error while exporting Sales Order {sales_order.name} to Medusa"
			})
			response = send_request(args)

			if response.message == "Order updated successfully":
				print(f"Sales Order {sales_order.name} exported to Medusa successfully")
			else:
					print(f"Error: Sales Order export failed for {sales_order.name}: {response.get('error')}")
	except Exception as e:
		print(f"Error exporting Sales Order {sales_order.name}: {str(e)}")
		raise e

def export_sales_order_on_update(doc, method):
	if doc.from_ecommerce == 1:
		try:
			export_sales_order(doc.name, "")
			frappe.msgprint("Order details updated in Medusa site successfully")
		except Exception as e:
			frappe.log_error(f"Failed to export Sales Order {doc.name}: {str(e)}", "Sales Order Export Error")
			print(f"Error exporting Sales Order {doc.name}: {str(e)}")

def send_quotation_emails():
	email_queue = frappe.get_all(
		"Email Queue",
		filters={
			"status": "Not Sent",
			"reference_doctype": "Quotation" #Need to update. Add sender email filter
		},
		pluck="name"
	)

	for email in email_queue:
		try:
			from frappe.email.doctype.email_queue.email_queue import send_now
			send_now(email)

		except Exception as e:
			frappe.log_error(message=str(e), title="Quotation Email Sending Failed")

@frappe.whitelist(allow_guest=True)
def get_website_items(url=None):
	from frappe import _
	import re
	import math

	def fetch_items(filters, order_by, offset, page_size, customer_id):
		"""Fetch paginated website items with filters and sorting."""
		website_items = frappe.get_all(
			"Website Item",
			fields=["name", "medusa_id", "web_item_name", "item_group", "custom_overall_rating"],
			filters=filters,
			order_by=order_by,
			start=offset,
			page_length=page_size
		)

		base_url = frappe.utils.get_url()
		modified_items = []
		for item in website_items:
			item_group_medusa_id = frappe.db.get_value("Item Group", item["item_group"], "medusa_id")
			image_url = frappe.db.get_value(
				"File", 
				{"attached_to_doctype": "Website Item", "attached_to_name": item["name"]}, 
				"file_url"
			)
			thumbnail = f"{base_url}{image_url}" if image_url else None

			is_wishlisted = 0
			if customer_id:
				is_wishlisted = frappe.db.exists(
					"Medusa Wishlist",
					{
						"parent": item["name"],
						"medusa_customer_id": customer_id
					}
				)
				is_wishlisted = 1 if is_wishlisted else 0

			modified_items.append({
				"id": item["medusa_id"],
				"title": item["web_item_name"],
				"collection_title": item["item_group"],
				"thumbnail": thumbnail,
				"rating": item["custom_overall_rating"],
				"is_wishlisted": is_wishlisted
			})
		return modified_items

	try:
		data = frappe.request.get_json()

		collection_titles = data.get("collection_title")
		brands = data.get("brand")
		customer_id = data.get("customer_id")
		page = data.get("page", 1)
		availability = data.get("availability")
		sort_order = data.get("sort_order", "asc")
		page_size = 20
		offset = (int(page) - 1) * page_size

		last_part = url.strip("/").split("/")[-1].replace("-", "%")
		second_part = set()

		item_group = frappe.db.get_value(
			"Item Group", 
			{"name": ["like", f"%{last_part}%"]} if "%" in last_part else {"name": last_part}, 
			"name"
		)

		if not item_group:
			return {"status": "error", "message": f"No matching item group found for the URL: {url}"}
		
		if sort_order == "default":
			order_by = "ranking desc"
		elif sort_order == "asc":
			order_by = "item_name asc"
		else:
			order_by = "item_name desc"
		
		descendant_groups = frappe.db.get_descendants("Item Group", item_group)
		descendant_groups.append(item_group)

		filters = {"item_group": ["in", descendant_groups]}
		
		distinct_parent_item_groups = []
		distinct_collection_titles = []
		distinct_brands = []

		distinct_collection_titles = frappe.db.sql("""
			SELECT item_group AS name, COUNT(*) AS count
			FROM `tabWebsite Item`
			WHERE item_group IN %(descendant_groups)s
			GROUP BY item_group
			ORDER BY name
		""", {"descendant_groups": tuple(descendant_groups)}, as_dict=True)

		if collection_titles:
			if not isinstance(collection_titles, list):
				collection_titles = [collection_titles]
			
			collection_descendants = []
			for title in collection_titles:
				descendants = frappe.db.get_descendants("Item Group", title)
				collection_descendants.extend(descendants)
				collection_descendants.append(title)

			filters["item_group"] = ["in", list(set(collection_descendants))]

			distinct_brands = frappe.db.sql("""
				SELECT brand AS name, COUNT(*) AS count
				FROM `tabWebsite Item`
				WHERE item_group IN %(collection_descendants)s AND brand IS NOT NULL AND brand != ''
				GROUP BY brand
				ORDER BY brand
			""", {"collection_descendants": tuple(collection_descendants)}, as_dict=True)
		
		else:
			distinct_brands = frappe.db.sql("""
				SELECT brand AS name, COUNT(*) AS count
				FROM `tabWebsite Item`
				WHERE item_group IN %(descendant_groups)s AND brand IS NOT NULL AND brand != ''
				GROUP BY brand
				ORDER BY brand
			""", {"descendant_groups": tuple(descendant_groups)}, as_dict=True)

		if brands:
			if not isinstance(brands, list):
				brands = [brands]
			filters["brand"] = ["in", brands]
		
		if brands and not collection_titles:
			distinct_collection_titles = frappe.db.sql("""
				SELECT item_group AS name, COUNT(*) AS count
				FROM `tabWebsite Item`
				WHERE item_group IN %(descendant_groups)s
				{brand_filter}
				GROUP BY item_group
				ORDER BY name
			""".format(
				brand_filter="AND brand IN %(brands)s" if brands else ""
			), {
				"descendant_groups": tuple(descendant_groups),
				"brands": tuple(brands) if brands else None
			}, as_dict=True)

		if not (item_group == "Products" and brands and not collection_titles):
			immediate_descendants = frappe.get_all(
				"Item Group",
				fields=["name"],
				filters={"parent_item_group": item_group},
				order_by="name"
			)

			distinct_parent_item_groups = [
				{
					"title": group["name"],
					"handle": re.sub(r"[^a-z0-9]+", "-", group["name"].lower()).strip("-")
				}
				for group in immediate_descendants
			]
		else:
			for collection in distinct_collection_titles:
				route = frappe.db.get_value("Item Group", {"name": collection.name}, "route")
				parts = route.strip("/").split("/")
				if len(parts) > 1:
					second_part.add(parts[1].replace("-", "%"))
			
			second_part_list = list(second_part)
			parent_groups = []
			for part in second_part_list:
				parent_group = frappe.db.get_value(
					"Item Group",
					{"name": ["like", f"%{part}%"]} if "%" in part else {"name": part}, 
					"name"
				)
				if parent_group:
					parent_groups.append(parent_group)

			distinct_parent_item_groups = [
				{
					"title": group,
					"handle": re.sub(r"[^a-z0-9]+", "-", group.lower()).strip("-"),
				}
				for group in parent_groups
			]

		if availability:
			filters["custom_in_stock"] = ["=", 1]

		total_products = frappe.db.count("Website Item", filters=filters)

		modified_items = fetch_items(filters, order_by, offset, page_size, customer_id)

		return {
			"product_count": total_products,
			"total_pages": math.ceil(total_products / page_size),
			"current_page": int(page),
			"items_in_page": len(modified_items),
			"distinct_parent_item_groups": distinct_parent_item_groups,
			"distinct_collection_titles": distinct_collection_titles,
			"distinct_brands": distinct_brands,
			"paginatedProducts": modified_items,
		}

	except Exception as e:
		frappe.log_error(message=str(e), title=_("Fetch Website Items Failed"))
		return {"status": "error", "message": str(e)}

@frappe.whitelist(allow_guest=True)
def get_all_brands(item_group=None):
	try:
		base_url = frappe.utils.get_url()
		brands = []

		if item_group:
			descendant_groups = frappe.db.get_descendants("Item Group", item_group)
			descendant_groups.append(item_group)

			brands = frappe.db.sql("""
				SELECT DISTINCT w.brand AS name
				FROM `tabWebsite Item` w
				WHERE w.item_group IN %(descendant_groups)s
				AND w.brand IS NOT NULL AND w.brand != ''
				ORDER BY w.brand ASC
			""", {"descendant_groups": tuple(descendant_groups)}, as_dict=True)

		else:
			brands = frappe.get_all("Brand", fields=["name"], order_by="name asc")

		brand_list = []
		for brand in brands:
			image_url = frappe.db.get_value(
				"File",
				{"attached_to_doctype": "Brand", "attached_to_name": brand.get("brand") or brand["name"]},
				"file_url"
			)
			image_url = f"{base_url}{image_url}" if image_url else None

			brand_list.append({
				"brand": brand.get("brand") or brand["name"],
				"image": image_url
			})

		return brand_list

	except Exception as e:
		frappe.log_error(message=str(e), title="Fetch Brands Failed")
		return {
			"status": "error",
			"message": str(e)
		}

@frappe.whitelist(allow_guest=True)
def get_homepage_top_section():
	try:
		top_section = frappe.get_doc("Homepage Landing", "Active Homepage Landing")

		base_url = frappe.utils.get_url()
		
		def fetch_image_url(doctype, name):
			image_url = frappe.db.get_value(
				"File",
				{"attached_to_doctype": doctype, "attached_to_name": name},
				"file_url"
			)
			return f"{base_url}{image_url}" if image_url else None

		entries_data = []
		for entry in top_section.top_section:
			thumbnail = fetch_image_url(entry.link_doctype, entry.name1)

			if entry.link_doctype == "Item Group":
				item_group_details = get_menu(parent=entry.name1, mobile_view=0)
				item_group_info = item_group_details.get("children", [])
				url = get_full_route(item_group=entry.name1)
				
				entries_data.append({
					"type": entry.link_doctype,
					"title": entry.name1,
					"thumbnail": thumbnail,
					"url": url,
					"sub_categories": item_group_info
				})
			elif entry.link_doctype == "Brand":
				item_groups = frappe.db.sql("""
					SELECT DISTINCT w.item_group AS name
					FROM `tabWebsite Item` w
					WHERE w.brand = %(brand_name)s
					ORDER BY w.item_group ASC
				""", {"brand_name": entry.name1}, as_dict=True)

				categories = [
					{
						"name": group["name"],
						"url": get_full_route(item_group=group["name"])
					}
					for group in item_groups
				]

				entries_data.append({
					"type": entry.link_doctype,
					"title": entry.name1,
					"thumbnail": thumbnail,
					"categories": categories
				})
			
		return entries_data

	except Exception as e:
		frappe.log_error(message=str(e), title="Fetch Homepage Top Banner Failed")
		return {"status": "error", "message": str(e)}

def get_full_route(item_group):
		current_group = item_group
		route_parts = []

		while current_group and current_group != "Products":
			route_parts.append(slugify(current_group))
			current_group = frappe.db.get_value("Item Group", current_group, "parent_item_group")

		route_parts.append("products")
		return "/".join(reversed(route_parts))

def slugify(name):
	import re
	
	return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")

@frappe.whitelist(allow_guest=True)
def get_menu(parent=None, mobile_view=0):
	
	def fetch_image(item_group_name):
		image_url = frappe.db.get_value(
			"File",
			{"attached_to_doctype": "Item Group", "attached_to_name": item_group_name},
			"file_url"
		)
		base_url = frappe.utils.get_url()
		return f"{base_url}{image_url}" if image_url else None

	def fetch_child_groups(parent_group, recursive=False):
		children = frappe.get_all(
			"Item Group",
			fields=["name"],
			filters={"parent_item_group": parent_group},
			order_by="name"
		)
		
		child_groups = []
		for child in children:
			sub_child_count = frappe.db.count("Item Group", {"parent_item_group": child["name"]}),
			route = get_full_route(child["name"])
			image = fetch_image(child["name"])

			child_data = {
				"title": child["name"],
				"handle": slugify(child["name"]),
				"url": route,
				"thumbnail": image
			}

			if recursive and sub_child_count[0] > 0:
				child_data["children"] = fetch_child_groups(child["name"], recursive=True)

			child_groups.append(child_data)

		return child_groups

	try:

		recursive = bool(int(mobile_view))
		child_item_groups = fetch_child_groups(parent, recursive=recursive)

		return {
			"children": child_item_groups
		}

	except Exception as e:
		frappe.log_error(message=str(e), title="Fetch Child Item Groups Failed")
		return {"status": "error", "message": str(e)}

@frappe.whitelist(allow_guest=True)
def add_review_to_website_item(item_code, customer_id, customer_name=None, review=None, review_id=0, rating=0, date=None, likes=0, dislikes=0):
	website_item = None
	try:
		web_item_code = frappe.db.get_value("Website Item", { "medusa_id": item_code}, "name")
		website_item = frappe.get_doc("Website Item", web_item_code)

		frappe.db.set_value("Website Item", website_item.name, "custom_skip_update_hook", 1)

		if likes or dislikes:
			like_dislike_review = None
			for r in website_item.custom_review:
				if r.review_id == str(review_id):
					like_dislike_review = r
					break
			
			if likes:
				like_dislike_review.likes = likes
			if dislikes:
				like_dislike_review.dislikes = dislikes
			website_item.save(ignore_permissions=True)
			frappe.db.commit()

			return {"status": "success", "message": "Likes and dislikes updated successfully"}
		
		rating = max(1, rating)
		existing_review = None
		for r in website_item.custom_review:
			if r.medusa_id == customer_id:
				existing_review = r
				break

		if existing_review:
			if customer_name:
				existing_review.name1 = customer_name
			if review:
				existing_review.review = review
			if review_id:
				existing_review.review_id = review_id
			if rating:
				existing_review.rating = rating / 5
			if date:
				existing_review.date = date
			existing_review.likes = 0
			existing_review.dislikes = 0
		else:
			website_item.append("custom_review", {
				"medusa_id": customer_id,
				"name1": customer_name,
				"review": review,
				"review_id": review_id,
				"rating": rating / 5,
				"date": date,
				"likes": likes,
				"dislikes": dislikes
			})

		reviews = website_item.get("custom_review")
		total_ratings = sum([r.rating * 5 for r in reviews])
		total_reviews = len(reviews)
		overall_rating = total_ratings / total_reviews if total_reviews > 0 else 0
		website_item.custom_overall_rating = overall_rating

		website_item.save(ignore_permissions=True)
		frappe.db.commit()

		return ("Review updated successfully" if existing_review else "Review added successfully")

	except Exception as e:
		frappe.log_error(message=frappe.get_traceback(with_context=1), title="Add Review to Website Item")
		return {"status": "error", "message": str(e)}

	finally:
		if website_item:
			frappe.db.set_value("Website Item", website_item.name, "custom_skip_update_hook", 0)

@frappe.whitelist(allow_guest=True)
def handle_wishlist(item_code, customer_id):
	website_item = None
	try:
		web_item_code = frappe.db.get_value("Website Item", {"medusa_id": item_code}, "name")
		website_item = frappe.get_doc("Website Item", web_item_code)

		frappe.db.set_value("Website Item", website_item.name, "custom_skip_update_hook", 1)
		website_item.reload()

		existing_wishlist_entry = None
		for entry in website_item.custom_medusa_wishlist:
			if entry.medusa_customer_id == customer_id:
				existing_wishlist_entry = entry
				break
		
		if existing_wishlist_entry:
			website_item.custom_medusa_wishlist.remove(existing_wishlist_entry)
			website_item.save(ignore_permissions=True)
			frappe.db.commit()
			return ("Customer removed from wishlist successfully")
		
		website_item.append("custom_medusa_wishlist", {
			"medusa_customer_id": customer_id
		})

		website_item.save(ignore_permissions=True)
		frappe.db.commit()

		return ("Customer added to wishlist successfully")

	except Exception as e:
		frappe.log_error(message=frappe.get_traceback(with_context=1), title="Add Customer to Wishlist")
		return {"status": "error", "message": str(e)}

	finally:
		if website_item:
			frappe.db.set_value("Website Item", website_item.name, "custom_skip_update_hook", 0)

@frappe.whitelist(allow_guest=True)
def fetch_quotation_pdf_url():
	data = json.loads(frappe.request.data)
	quotation_id = data.get("quotation_id")
	
	if not frappe.db.exists("Quotation", quotation_id):
		return {"error": f"Quotation with ID {quotation_id} not found."}
	
	try:
		site_url = frappe.utils.get_url()
		
		pdf_url = f"{site_url}/printview?doctype=Quotation&name={quotation_id}&format=Alfarsi%20Quote%20Print&no_letterhead=0&_lang=en"

		return (pdf_url)
	
	except Exception as e:
		frappe.log_error(f"Error generating PDF URL for Quotation {quotation_id}: {str(e)}", "Quotation PDF URL Error")
		return {"error": f"Failed to generate PDF URL: {str(e)}"}

@frappe.whitelist(allow_guest=True)
def fetch_relevant_collection_products():
	try:
		data = json.loads(frappe.request.data)
		item_group = data.get("item_group")
		
		route = frappe.db.get_value("Item Group", {"name": item_group}, "route")
		parts = route.strip("/").split("/")
		if len(parts) > 1:
			second_part = parts[1].replace("-", "%")
		
		parent_group = frappe.db.get_value(
			"Item Group",
			{"name": ["like", f"%{second_part}%"]} if "%" in second_part else {"name": second_part}, 
			"name"
		)
		if parent_group:
			parent_route = frappe.db.get_value("Item Group", {"name": parent_group}, "route")
			result = get_website_items(url=parent_route, homepage=1)
			return {"top_collection": parent_group, "products": result.get("paginatedProducts")}
		else:
			return {"status": "error", "message": "No parent group found."}
	except Exception as e:
		frappe.log_error(message=str(e), title=_("Fetch Relevant Collection Products Failed"))
		return {"status": "error", "message": str(e)}

@frappe.whitelist(allow_guest=True)
def fetch_relevant_items():
	recommended_items_data = []

	def get_recommended_items_data(relevant_items, cus_id):
		items_data = []
		for recommended_item in relevant_items:
			base_url = frappe.utils.get_url()
			website_item_name = recommended_item
			medusa_id = frappe.get_value("Website Item", {"name": website_item_name}, "medusa_id")
			image_url = frappe.db.get_value(
				"File", 
				{"attached_to_doctype": "Website Item", "attached_to_name": website_item_name}, 
				"file_url"
			)
			thumbnail = f"{base_url}{image_url}" if image_url else None

			item_data = frappe.get_doc("Website Item", website_item_name)

			is_wishlisted = 0
			if cus_id:
				is_wishlisted = frappe.db.exists(
					"Medusa Wishlist",
					{
						"parent": item_data.web_item_name,
						"medusa_customer_id": cus_id
					}
				)
				is_wishlisted = 1 if is_wishlisted else 0
			
			items_data.append({
				"id": medusa_id,
				"title": item_data.web_item_name,
				"item_group": item_data.item_group,
				"thumbnail": thumbnail,
				"rating": item_data.custom_overall_rating,
				"isWishlisted": is_wishlisted
			})
		return items_data

	try:
		data = json.loads(frappe.request.data)
		item_code = data.get("item_code")
		cus_id = data.get("cus_id")
		
		website_item = frappe.get_doc("Website Item", {"item_code": item_code})
		parent_route = frappe.db.get_value("Item Group", {"name": website_item.item_group}, "route")

		relevant_items = [related_item.website_item for related_item in website_item.recommended_items]

		relevant_items_data = get_recommended_items_data(relevant_items, cus_id)
		recommended_items_data.extend(relevant_items_data)
			
		products = get_website_items(url=parent_route)
		recommended_items_data.extend(products.get("paginatedProducts"))
		
		return recommended_items_data
	except Exception as e:
		frappe.log_error(message=str(e), title=_("Fetch relevant products failed"))
		return {"status": "error", "message": str(e)}

@frappe.whitelist(allow_guest=True)
def get_recommended_items(customer_id):
	return fetch_items_from_homepage("recommended_items", customer_id)

@frappe.whitelist(allow_guest=True)
def get_trending_items(customer_id):
	return fetch_items_from_homepage("trending_items", customer_id)

@frappe.whitelist(allow_guest=True)
def get_new_arrivals(customer_id):
	return fetch_items_from_homepage("new_arrivals", customer_id)

@frappe.whitelist(allow_guest=True)
def get_dental_items(customer_id):
	return fetch_items_from_homepage("dental_items", customer_id)

@frappe.whitelist(allow_guest=True)
def get_medical_items(customer_id):
	return fetch_items_from_homepage("medical_items", customer_id)

@frappe.whitelist(allow_guest=True)
def get_medical_laboratory_items(customer_id):
	return fetch_items_from_homepage("medical_laboratory_items", customer_id)

@frappe.whitelist(allow_guest=True)
def get_infection_control_items(customer_id):
	return fetch_items_from_homepage("infection_control_items", customer_id)

def fetch_items_from_homepage(item_field_name, customer_id=None):
	import random
	try:
		homepage_landing = frappe.get_doc("Homepage Landing", "Active Homepage Landing")
		all_items = getattr(homepage_landing, item_field_name, [])

		if len(all_items) <= 20:
			random_entries = random.sample(all_items, len(all_items))
		else:
			random_entries = random.sample(all_items, 20)

		base_url = frappe.utils.get_url()

		entries_data = []
		for entry in random_entries:
			website_item_code = entry.website_item

			image_url = frappe.db.get_value(
				"File",
				{"attached_to_doctype": "Website Item", "attached_to_name": website_item_code},
				"file_url"
			)
			thumbnail = f"{base_url}{image_url}" if image_url else None

			website_item_details = frappe.db.get_value(
				"Website Item",
				{"name": website_item_code},
				["medusa_id", "web_item_name", "item_group", "custom_overall_rating"],
				as_dict=True
			)

			is_wishlisted = 0
			if customer_id:
				is_wishlisted = frappe.db.exists(
					"Medusa Wishlist",
					{
						"parent": website_item_code,
						"medusa_customer_id": customer_id
					}
				)
				is_wishlisted = 1 if is_wishlisted else 0
			
			if website_item_details:
				entries_data.append({
					"product_id": website_item_details.medusa_id,
					"item_name": website_item_details.web_item_name,
					"item_group": website_item_details.item_group,
					"overall_rating": website_item_details.custom_overall_rating,
					"thumbnail": thumbnail,
					"is_wishlisted": is_wishlisted
				})

		return entries_data

	except Exception as e:
		frappe.log_error(message=str(e), title="Fetch Homepage Items Failed")
		return {"status": "error", "message": str(e)}

@frappe.whitelist(allow_guest=True)
def get_homepage_order_list():
	try:
		active_order_list_name = "Active Homepage Landing"
		
		homepage_order_list = frappe.get_doc("Homepage Landing", active_order_list_name)

		order_data = []

		for order in homepage_order_list.order:
			if order.label == "DENTAL":
				order_data.append("get_dental_items")
			elif order.label == "MEDICAL":
				order_data.append("get_medical_items")
			elif order.label == "INFECTION CONTROL":
				order_data.append("get_infection_control_items")
			else:
				order_data.append("get_medical_laboratory_items")
		
		return order_data

	except Exception as e:
		frappe.log_error(message=str(e), title="Fetch Active Homepage Order List Failed")
		return {"status": "error", "message": str(e)}

@frappe.whitelist(allow_guest=True)
def get_yt_videos_list():
	try:
		active_yt_videos = "Active Homepage Landing"
		
		active_yt_videos_doc = frappe.get_doc("Homepage Landing", active_yt_videos)

		entries_data = []

		for entry in active_yt_videos_doc.urls:
			website_item_code = entry.website_item if hasattr(entry, "website_item") else None
			website_item_details = None
			image_url = None

			if website_item_code:
				website_item_details = frappe.db.get_value(
					"Website Item",
					{"name": website_item_code},
					["web_item_name", "medusa_id"],
					as_dict=True
				)
				
				image_url = frappe.db.get_value(
					"File",
					{"attached_to_doctype": "Website Item", "attached_to_name": website_item_code},
					"file_url"
				)
			
			entry_data = {
				"url": entry.url,
				"title": website_item_details.web_item_name if website_item_details else None,
				"medusa_id": website_item_details.medusa_id if website_item_details else None,
				"thumbnail": f"https://medusa-erpnext-staging.aerele.in{image_url}" if image_url else None
			}

			entries_data.append(entry_data)

		return entries_data

	except Exception as e:
		frappe.log_error(message=str(e), title="Fetch Active YouTube Videos List Failed")
		return {"status": "error", "message": str(e)}

@frappe.whitelist(allow_guest=True)
def get_testimonials():
	try:
		homepage = frappe.get_doc("Homepage Landing", "Active Homepage Landing")

		testimonials_data = []
		for entry in homepage.testimonials:
			testimonials_data.append({
				"thumbnail": entry.image_url,
				"review": entry.review,
				"review_by": entry.review_by,
				"designation": entry.designation
			})
		
		return testimonials_data

	except Exception as e:
		frappe.log_error(message=str(e), title="Fetch Testimonials Failed")
		return {"status": "error", "message": str(e)}
