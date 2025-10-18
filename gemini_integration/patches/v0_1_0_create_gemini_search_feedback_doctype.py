import frappe


def execute():
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": "Gemini Search Feedback",
			"module": "Gemini Integration",
			"custom": 0,
			"fields": [
				{"fieldname": "search_query", "fieldtype": "Data", "label": "Search Query", "reqd": 1},
				{"fieldname": "document_name", "fieldtype": "Data", "label": "Document Name", "reqd": 1},
				{"fieldname": "doctype_name", "fieldtype": "Data", "label": "DocType Name", "reqd": 1},
				{"fieldname": "is_helpful", "fieldtype": "Check", "label": "Is Helpful"},
			],
			"permissions": [
				{
					"role": "System Manager",
					"read": 1,
					"write": 1,
					"create": 1,
					"delete": 1,
					"submit": 0,
					"cancel": 0,
					"amend": 0,
					"print": 1,
					"email": 1,
					"report": 1,
					"import": 0,
					"export": 1,
					"share": 1,
				}
			],
		}
	).insert(ignore_if_duplicate=True)
