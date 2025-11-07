import json

import frappe


def execute():
	"""
	Migrates data from the old `Table MultiSelect` field to the new child table.
	"""
	# Check if the new child table 'Embedding Doctype' is empty. If not, the migration
	# may have already run, so we'll skip it to avoid creating duplicates.
	if frappe.db.count("Embedding Doctype", {"parent": "Gemini Settings"}):
		return

	# Singleton settings are stored as a JSON string in the `tabSingles` table.
	settings_json = frappe.db.get_value("Singles", {"doctype": "Gemini Settings"}, "value")

	if not settings_json:
		# No settings were ever saved, so there is nothing to migrate.
		return

	try:
		settings_data = json.loads(settings_json)
	except (json.JSONDecodeError, TypeError):
		# The stored value is not valid JSON, so we cannot safely migrate data.
		return

	# The data for a `Table MultiSelect` field is stored as a list of dictionaries.
	old_doctype_list = settings_data.get("embedding_doctypes")

	if not isinstance(old_doctype_list, list):
		# If the key doesn't exist or is not a list, there's nothing to migrate.
		return

	# Get the 'Gemini Settings' document to append the new child records to.
	settings_doc = frappe.get_doc("Gemini Settings")
	settings_doc.embedding_doctypes = []  # Clear any existing entries first.

	migrated_count = 0
	for item in old_doctype_list:
		if not isinstance(item, dict):
			continue

		# The implicit link field in a Table MultiSelect is named 'doctype'.
		doctype_name = item.get("doctype")

		# Ensure the DocType actually exists before creating a link to it.
		if doctype_name and frappe.db.exists("DocType", doctype_name):
			settings_doc.append("embedding_doctypes", {"doctype_name": doctype_name})
			migrated_count += 1

	if migrated_count > 0:
		# Save the document, ignoring permissions and mandatory fields,
		# as this is a background migration.
		settings_doc.flags.ignore_permissions = True
		settings_doc.flags.ignore_mandatory = True
		settings_doc.save()
