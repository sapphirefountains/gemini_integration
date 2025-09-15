# Copyright (c) 2025, Sapphire Fountains and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class GoogleUserToken(Document):
	"""A class representing the Google User Token document type.

	This document stores the OAuth 2.0 tokens for a user's Google account,
	allowing the system to make authorized API calls on their behalf.
	"""
	pass
