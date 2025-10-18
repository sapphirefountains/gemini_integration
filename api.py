import frappe

from gemini_integration.gemini import (
	analyze_risks,
	generate_chat_response,
	generate_tasks,
	generate_text,
	get_google_auth_url,
	is_google_integrated,
	process_google_callback,
)
from gemini_integration.utils import handle_errors, log_activity


@frappe.whitelist()
@log_activity
@handle_errors
def generate(prompt, model=None, generation_config=None):
	"""Generates text using the Gemini API."""
	if generation_config and isinstance(generation_config, str):
		import json

		generation_config = json.loads(generation_config)
	return generate_text(prompt, model, generation_config=generation_config)


@frappe.whitelist()
@log_activity
@handle_errors
def chat(prompt, model=None, conversation_id=None):
	"""Handles chat interactions with the Gemini API."""
	return generate_chat_response(prompt, model, conversation_id)


@frappe.whitelist()
@log_activity
@handle_errors
def get_project_tasks(project_id, template):
	"""Generates project tasks based on a project ID and template."""
	return generate_tasks(project_id, template)


@frappe.whitelist()
@log_activity
@handle_errors
def get_project_risks(project_id):
	"""Analyzes and returns the risks for a given project."""
	return analyze_risks(project_id)


@frappe.whitelist()
@log_activity
@handle_errors
def get_auth_url():
	"""Retrieves the Google OAuth 2.0 authorization URL."""
	return get_google_auth_url()


@frappe.whitelist(allow_guest=True)
@log_activity
@handle_errors
def handle_google_callback(code=None, state=None, error=None):
	"""Handles the callback from Google after user authorization."""
	process_google_callback(code, state, error)


@frappe.whitelist()
@log_activity
@handle_errors
def check_google_integration():
	"""Checks if the current user has integrated their Google account."""
	return is_google_integrated()


@frappe.whitelist()
def get_conversations():
	"""Retrieves all Gemini conversations for the current user."""
	return frappe.get_all(
		"Gemini Conversation",
		filters={"user": frappe.session.user},
		fields=["name", "title"],
		order_by="modified desc",
	)


@frappe.whitelist()
def get_conversation(conversation_id):
	"""Retrieves a specific Gemini conversation."""
	doc = frappe.get_doc("Gemini Conversation", conversation_id)
	if doc.user != frappe.session.user:
		frappe.throw("You are not authorized to view this conversation.")
	return doc
