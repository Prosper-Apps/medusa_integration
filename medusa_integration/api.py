import requests
import frappe
import json
from frappe import _
from medusa_integration.constants import get_headers, get_url
from medusa_integration.utils import send_request

# @frappe.whitelist()
# def greet(name=None):
#     return f"Hello, {name}"

# @frappe.whitelist(allow_guest=True)
# def create_customer():
#     data = json.loads(frappe.request.data)
#     customer = frappe.get_doc({
#         "doctype": "Customer",
#         "medusa_id": data.get("id"),
#         "customer_name": data.get("first_name") + " " + data.get("last_name"),
#         "customer_type": data.get("business_type"),
#         "email_id": data.get("email"),
#         "is_business": data.get("is_business"),
#         "t_c_acceptance": data.get("t_c_acceptance"),
#         "offers_agreement": data.get("offers_agreement"),
#     })
#     customer.insert(ignore_permissions=True)
#     return {"message": _("Customer created successfully"), "customer_id": customer.name}

def export_item(self, method):
	item_group = frappe.get_doc("Item Group", self.item_group)

	if not item_group.medusa_id:
		create_medusa_collection(self=item_group, method=None)

	payload = {
					"title": self.item_name, #self.item_code,
					"discountable": False,
					"is_giftcard": False,
					"collection_id": item_group.medusa_id,
					"description": self.description,
					"status": "published",
					"brand_name": self.brand
	}

	if get_url()[1] and not self.medusa_id:
		args = frappe._dict({
						"method" : "POST",
						"url" : f"{get_url()[0]}/admin/products",
						"headers": get_headers(with_token=True),
						"payload": json.dumps(payload),
						"throw_message": "Error while exporting Item to Medusa"
		})

		# self.medusa_id = send_request(args).get("product").get("id")
		self.db_set("medusa_id", send_request(args).get("product").get("id"))
		medusa_var_id = create_medusa_variant(self.medusa_id)
		print(medusa_var_id)
		self.db_set("medusa_variant_id", medusa_var_id)
		# self.db_set("medusa_variant_id", send_request(args).get("product").get("id"))

	elif self.medusa_id and self.get_doc_before_save():
		payload.pop("is_giftcard")
		payload.pop("brand_name")
		args = frappe._dict({
						"method" : "POST",
						"url" : f"{get_url()[0]}/admin/products/{self.medusa_id}",
						"headers": get_headers(with_token=True),
						"payload": json.dumps(payload),
						"throw_message": "Error while updating Item in Medusa"
		})
		send_request(args)

def export_website_item(self, method):
	item_group = frappe.get_doc("Item Group", self.item_group)

	if not item_group.medusa_id:
		create_medusa_collection(self=item_group, method=None)
	
	item = frappe.get_doc("Item", self.item_code)
	#origin_country = frappe.get_value("Item", {"item_code": self.item_code}, "country_of_origin")
	
	payload = {
					"title": self.web_item_name,
					"discountable": False,
					"is_giftcard": False,
					"collection_id": item_group.medusa_id,
					"description": self.web_long_description,
					"status": "published" if self.published else "draft",
					"origin_country": "IN" # item.country_of_origin
	}

	if get_url()[1] and not self.get_doc_before_save():
		args = frappe._dict({
						"method" : "POST",
						"url" : f"{get_url()[0]}/admin/products",
						"headers": get_headers(with_token=True),
						"payload": json.dumps(payload),
						"throw_message": "Error while exporting Website Item to Medusa"
		})

		self.medusa_id = send_request(args).get("product").get("id")
		self.medusa_variant_id = create_medusa_variant(self.medusa_id, self.on_backorder, item.country_of_origin)
		# update_medusa_variant(product_id, variant_id, option_id)

	if self.medusa_id and self.get_doc_before_save():
		payload.pop("is_giftcard")
		args = frappe._dict({
						"method" : "POST",
						"url" : f"{get_url()[0]}/admin/products/{self.medusa_id}",
						"headers": get_headers(with_token=True),
						"payload": json.dumps(payload),
						"throw_message": "Error while updating Website Item in Medusa"
		})
		send_request(args)

def create_medusa_variant(product_id, backorder = False, country_of_origin = None):
	option_id = create_medusa_option(product_id)
	#item = frappe.get_doc("Item", item_code)
	payload = json.dumps({
							"title": "Default",
							"material": None,
							"mid_code": None,
							"hs_code": None,
							"origin_country": "IN", # country_of_origin
							"sku": None,
							"ean": None,
							"upc": None,
							"barcode": None,
							"inventory_quantity": 0,
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
							"throw_message": "Error while creating Item Variant in Medusa"
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
					"throw_message": "Error while creating Item Option in Medusa"
	})
	
	return send_request(args).get("product").get("options")[0].get("id")

def create_medusa_collection(self, method):
	if get_url()[1] and not self.get_doc_before_save():
		payload = json.dumps({
					"title": self.name,
		})
		args = frappe._dict({
		"method" : "POST",
		"url" : f"{get_url()[0]}/admin/collections",
		"headers": get_headers(with_token=True),
		"payload": payload,
		"throw_message": "Error while exporting Item Group to Medusa"
		})

		self.db_set("medusa_id", send_request(args).get("collection").get("id"))
	
def create_medusa_price_list(self, method):
	doc = frappe.get_doc("Item", self.item_code)
	payload = json.dumps({
		"name": self.item_code,
		"description": self.item_description,
		"type": "override", # or "sale"
		"customer_groups": [],
		"status": "active",
		"starts_at": self.valid_from,
		"ends_at": self.valid_upto,
		"prices": [
			{
				"amount": self.price_list_rate * 100,
				"variant_id": doc.medusa_variant_id,
				"currency_code": "usd"
			}
		]
	})
	
	if get_url()[1] and not self.get_doc_before_save():
		args = frappe._dict({	
			"method" : "POST",
			"url" : f"{get_url()[0]}/admin/price-lists",
			"headers": get_headers(with_token=True),
			"payload": payload,
			"throw_message": "Error while exporting Item Price to Medusa"
		})
		response = send_request(args).get("price_list")
		self.db_set("medusa_id", response.get("id"))

		prices = response.get("prices", [])
		self.db_set("medusa_price_id", prices[0].get("id"))

		# self.db_set("medusa_id", send_request(args).get("price_list").get("id"))
	
	if self.medusa_id and self.get_doc_before_save():
		payload = json.dumps({
			"prices": [
				{
					"id": self.medusa_price_id,
					"amount": self.price_list_rate * 100,
					"variant_id": doc.medusa_variant_id,
					"currency_code": "usd"
				}
			]
		})
		args = frappe._dict({	
			"method" : "POST",
			"url" : f"{get_url()[0]}/admin/price-lists/{self.medusa_id}",
			"headers": get_headers(with_token=True),
			"payload": payload,
			"throw_message": "Error while updating Item Price in Medusa"
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
			"throw_message": "Error while exporting Customer to Medusa"
		})
		self.db_set("medusa_id", send_request(args).get("customer").get("id"))

def file_validation_wrapper(self, method):
	# Call the namecheck function
	namecheck(self, method)
	print("Namecheck done")
	
	upload_image_to_medusa(self, method)
	print("Images uploaded")	

def upload_image_to_medusa(self, method):
	print("Entered Image upload")
	print("Name: ", self.attached_to_name)
	print("Doctype: ", self.attached_to_doctype) # Website item atteched to name check in FILE
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
		print("Web Item Name inside image getter: ", self.attached_to_doctype)
		images = frappe.get_all("File", filters={
						"attached_to_doctype": self.attached_to_doctype,
						"attached_to_name": self.attached_to_name,
						"attached_to_field": ["not in", ["image", "website_image"]]
				})
		print(images)
		image_urls = []

		for image in images:
			doc = frappe.get_doc("File", image)
			image_path = doc.get_full_path()
			print("Image path: ", image_path)
			url = f"{get_url()[0]}/admin/uploads"
			print("Upload URL: ", url)
			headers = get_headers(with_token=True)
			headers.pop('Content-Type', None)  # Remove the Content-Type header to let requests set it
			payload = {}
			print(1)
			with open(image_path, 'rb') as image_file:
				print(2)
				files = {'files': (image_path, image_file, 'image/jpeg')}
				print(3)
				response = requests.post(url, headers=headers, data=payload, files=files)
				print(4)
				print(response)
				print(response.text)
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
		print("Image path: ", image_path)
		url = f"{get_url()[0]}/admin/uploads"
		print("Upload URL: ", url)
		headers = get_headers(with_token=True)
		headers.pop('Content-Type', None)  # Remove the Content-Type header to let requests set it
		payload = {}
		print(1)
		with open(image_path, 'rb') as image_file:
			print(2)
			files = {'files': (image_path, image_file, 'image/jpeg')}
			print(3)
			response = requests.post(url, headers=headers, data=payload, files=files)
			print(4)
			print(response)
			print(response.text)
			if response.status_code == 200:
				uploaded_image_url = response.json().get('uploads')[0].get('url')
				print("Image uploaded")
				print("Image URL: ",uploaded_image_url)
				image_url = uploaded_image_url
				print("2nd Image URL: ", image_url)
			else:
				frappe.throw("Failed to upload image to Medusa")

		attach_thumbnail_to_product(image_url, medusa_id)

def attach_thumbnail_to_product(image_url, product_id):
	print("Image URLs: ", image_url)
	print("Product ID: ", product_id)
	url = f"{get_url()[0]}/admin/products/{product_id}"
	print("Product URL: ",url)
	headers = get_headers(with_token=True)
	payload = json.dumps({"thumbnail": image_url})

	args = frappe._dict({
		"method": "POST",
		"url": url,
		"headers": headers,
		"payload": payload,
		"throw_message": "Error while attaching thumbnail to the Medusa product"
	})
	send_request(args)

def attach_image_to_product(image_urls, product_id):
	print("Image URLs: ", image_urls)
	print("Product ID: ", product_id)
	url = f"{get_url()[0]}/admin/products/{product_id}"
	print("Product URL: ",url)
	headers = get_headers(with_token=True)
	payload = json.dumps({"images": image_urls})

	args = frappe._dict({
		"method": "POST",
		"url": url,
		"headers": headers,
		"payload": payload,
		"throw_message": "Error while attaching image to the Medusa product"
	})
	send_request(args)

def namecheck(self, method):
	if ' ' in self.file_name:
		frappe.throw("Invalid name format!<br>File name cannot contain spaces")

def export_old_data(doctype):
	record = frappe.get_all(doctype, limit = 5)
	print(record)
	method = ""
	for r in record:
		doc = frappe.get_doc(doctype, r)
		export_item(doc, method)
	
doctypes = []
def export_multiple_doc(doctypes: list):
	for d in doctypes:
		export_old_data(d)


def clear_medusa_id(): #clear_medusa_id() for Item Group
    # Get all documents in the "Item Group" doctype
    item_groups = frappe.get_all("Item Group", fields=["name"])
    
    # Iterate through each document and set the medusa_id to an empty string
    for item_group in item_groups:
        frappe.db.set_value("Item Group", item_group.name, "medusa_id", "")

    # Commit the changes to the database
    frappe.db.commit()

import frappe

def clear_medusa_fields(): #For items
    # Get all documents in the "Item" doctype
    items = frappe.get_all("Item", filters={"medusa_id": ["!=", ""]}, fields=["name"])
    print(items)

    # Iterate through each document and set the medusa_id and medusa_variant_id to an empty string
    for item in items:
        frappe.db.set_value("Item", item.name, {"medusa_id": "", "medusa_variant_id": ""})

    # Commit the changes to the database
    frappe.db.commit()

clear_medusa_fields()
