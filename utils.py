import functools
import logging
import re
import traceback

import frappe
from thefuzz import fuzz

from gemini_integration.mcp import mcp


def get_log_level():
	"""Retrieves the log level from Gemini Settings.

	Returns:
	    str: The configured log level ("Debug", "Warning", "Error"),
	         or "Error" if settings are not found.
	"""
	try:
		return frappe.db.get_single_value("Gemini Settings", "log_level")
	except Exception:
		return "Error"


def log_activity(func):
	"""A decorator to log function calls and results for debugging purposes.

	This decorator will only log activity if the log level in Gemini Settings
	is set to "Debug".

	Args:
	    func (function): The function to be decorated.

	Returns:
	    function: The wrapped function.
	"""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		log_level = get_log_level()
		if log_level == "Debug":
			frappe.log(
				f"Calling function {func.__name__} with args: {args}, kwargs: {kwargs}",
				"Gemini Integration Debug",
			)

		result = func(*args, **kwargs)

		if log_level == "Debug":
			frappe.log(f"Function {func.__name__} returned: {result}", "Gemini Integration Debug")

		return result

	return wrapper


def handle_errors(func):
	"""A decorator to handle exceptions in a centralized way.

	This decorator catches any exception from the decorated function, logs it
	with a full traceback, and then throws a generic, user-friendly error
	message to the UI. Logging only occurs if the log level is set to
	"Error", "Warning", or "Debug".

	Args:
	    func (function): The function to be decorated.

	Returns:
	    function: The wrapped function.
	"""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		try:
			return func(*args, **kwargs)
		except Exception as e:
			log_level = get_log_level()
			if log_level in ["Error", "Warning", "Debug"]:
				# Log the error with traceback
				frappe.log_error(
					message=f"An error occurred in {func.__name__}: {e!s}\n{traceback.format_exc()}",
					title="Gemini Integration Error",
				)

			# Throw a user-friendly error message
			frappe.throw("An unexpected error occurred. Please contact the system administrator.")

	return wrapper


@mcp.tool()
@log_activity
@handle_errors
def get_doc_context(doctype: str, docname: str) -> str:
	"""Fetches and formats a document's data for context."""
	try:
		doc = frappe.get_doc(doctype, docname)
		doc_dict = doc.as_dict()
		context = f"Context for {doctype} '{docname}':\n"
		for field, value in doc_dict.items():
			if value and not isinstance(value, list):
				context += f"- {field}: {value}\n"
		doc_url = frappe.utils.get_url_to_form(doctype, docname)
		context += f"\nLink: {doc_url}"
		return context
	except frappe.DoesNotExistError:
		return f"(System: Document '{docname}' of type '{doctype}' not found.)\n"
	except Exception as e:
		frappe.log_error(f"Error fetching doc context for {doctype} {docname}: {e!s}")
		return f"(System: Could not retrieve context for {doctype} {docname}.)\n"


@mcp.tool()
@log_activity
@handle_errors
def search_erpnext_documents(doctype: str, query: str, limit: int = 10) -> list:
	"""Searches for documents in ERPNext with a query and returns a list of documents."""
	try:
		# Include 'name' field for searching, as it's often the primary identifier.
		fields = ["name"] + [
			df.fieldname
			for df in frappe.get_meta(doctype).fields
			if df.fieldtype in ["Data", "Text", "Small Text", "Long Text", "Text Editor", "Select"]
		]
		all_docs = frappe.get_all(doctype, fields=list(set(fields)))  # Use set to avoid duplicate fields

		matching_docs = []
		for doc in all_docs:
			# Include the doctype name in the searchable text to improve context-aware search.
			doc_text = f"{doctype} " + " ".join([str(doc.get(field, "")) for field in fields])

			# token_set_ratio is good for matching phrases and ignoring word order.
			score = fuzz.token_set_ratio(query.lower(), doc_text.lower())

			if score > 75:  # Adjusted threshold for token_set_ratio
				matching_docs.append({"name": doc.name, "score": score})

		# Sort by score in descending order and take the top results
		sorted_matches = sorted(matching_docs, key=lambda x: x["score"], reverse=True)
		documents = sorted_matches[:limit]

		return documents
	except Exception as e:
		frappe.log_error(f"Error searching ERPNext documents for doctype {doctype}: {e!s}")
		return []


@mcp.tool()
@log_activity
@handle_errors
def get_dynamic_doctype_map() -> dict:
	"""Builds and caches a map of naming series prefixes to DocTypes."""
	cache_key = "gemini_doctype_prefix_map"
	doctype_map = frappe.cache().get_value(cache_key)
	if doctype_map:
		return doctype_map

	doctype_map = {}
	all_doctypes = frappe.get_all("DocType", fields=["name", "autoname"])
	for doc in all_doctypes:
		autoname = doc.get("autoname")
		if isinstance(autoname, str):
			match = re.match(r"^([A-Z_]+)[\-./]", autoname, re.IGNORECASE)
			if match:
				doctype_map[match.group(1).upper()] = doc.name

	hardcoded_map = {
		"PRJ": "Project",
		"TASK": "Task",
		"SO": "Sales Order",
		"PO": "Purchase Order",
		"QUO": "Quotation",
		"SI": "Sales Invoice",
		"PI": "Purchase Invoice",
		"CUST": "Customer",
		"SUPP": "Supplier",
		"ITEM": "Item",
		"LEAD": "Lead",
		"OPP": "Opportunity",
	}
	hardcoded_map.update(doctype_map)
	doctype_map = hardcoded_map

	frappe.cache().set_value(cache_key, doctype_map, expires_in_sec=3600)
	return doctype_map
