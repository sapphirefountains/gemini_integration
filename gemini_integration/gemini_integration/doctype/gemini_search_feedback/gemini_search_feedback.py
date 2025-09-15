# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class GeminiSearchFeedback(Document):
	"""A class representing the Gemini Search Feedback document type.

	This document stores user feedback on the relevance of search results,
	which can be used to improve the search algorithm over time.
	"""
	pass
