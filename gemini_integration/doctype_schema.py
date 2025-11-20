import frappe
from frappe.model.meta import get_meta


def get_doctype_schema_summary(doctype: str) -> dict:
	"""
	Generates a simplified schema summary for a given DocType, optimized for an LLM.

	:param doctype: The name of the DocType.
	:return: A dictionary containing the schema summary.
	"""
	meta = get_meta(doctype)

	schema_summary = {"doctype_name": meta.name, "description": meta.description or "", "fields": {}}

	# Field types to explicitly exclude as they are not queryable data fields.
	excluded_field_types = [
		"Section Break",
		"Column Break",
		"Tab Break",
		"Button",
		"HTML",
		"Image",
		"Read Only",
		"Table",
		"Attach",
		"Attach Image",
		"Password",
		"Code",
		"Geolocation",
		"Signature",
	]

	# Add 'name' field by default as it's the primary key.
	if meta.get_field("name"):
		schema_summary["fields"]["name"] = {
			"label": "ID",
			"type": "Data",
			"description": f"The unique identifier for the {meta.name}.",
		}

	for field in meta.fields:
		# Exclude non-queryable or hidden fields
		if field.fieldtype in excluded_field_types or field.hidden:
			continue

		field_info = {"label": field.label, "type": field.fieldtype, "description": field.description or ""}

		if field.fieldtype == "Select" and field.options:
			field_info["options"] = [opt for opt in field.options.split("\n") if opt]

		if field.fieldtype == "Link" and field.options:
			field_info["description"] = (
				f"{field_info['description']} " f"This links to the {field.options} DocType."
			).strip()

		schema_summary["fields"][field.fieldname] = field_info

	return schema_summary
