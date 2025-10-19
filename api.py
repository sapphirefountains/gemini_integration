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
	"""Generates text using the Gemini API.

	Args:
		prompt (str): The text prompt to send to the model.
		model (str, optional): The name of the Gemini model to use. Defaults to None.
		generation_config (dict or str, optional): Configuration for the generation
			process. If a string is provided, it will be parsed as JSON. Defaults to None.

	Returns:
		The generated text from the Gemini API.
	"""
	if generation_config and isinstance(generation_config, str):
		import json

		generation_config = json.loads(generation_config)
	return generate_text(prompt, model, generation_config=generation_config)


@frappe.whitelist()
@log_activity
@handle_errors
def chat(prompt, model=None, conversation_id=None):
	"""Handles chat interactions with the Gemini API.

	Args:
		prompt (str): The user's message.
		model (str, optional): The name of the Gemini model to use. Defaults to None.
		conversation_id (str, optional): The ID of an existing conversation to continue.
			Defaults to None.

	Returns:
		The chat response from the Gemini API.
	"""
	return generate_chat_response(prompt, model, conversation_id)


@frappe.whitelist()
@log_activity
@handle_errors
def get_project_tasks(project_id, template):
	"""Generates project tasks based on a project ID and template.

	Args:
		project_id (str): The ID of the project.
		template (str): The template to use for generating tasks.

	Returns:
		The generated project tasks.
	"""
	return generate_tasks(project_id, template)


@frappe.whitelist()
@log_activity
@handle_errors
def get_project_risks(project_id):
	"""Analyzes and returns the risks for a given project.

	Args:
		project_id (str): The ID of the project.

	Returns:
		An analysis of the project's risks.
	"""
	return analyze_risks(project_id)


@frappe.whitelist()
@log_activity
@handle_errors
def get_auth_url():
	"""Retrieves the Google OAuth 2.0 authorization URL.

	Returns:
		str: The authorization URL.
	"""
	return get_google_auth_url()


@frappe.whitelist(allow_guest=True)
@log_activity
@handle_errors
def handle_google_callback(code=None, state=None, error=None):
	"""Handles the callback from Google after user authorization.

	Args:
		code (str, optional): The authorization code from Google. Defaults to None.
		state (str, optional): The state parameter for CSRF protection. Defaults to None.
		error (str, optional): Any error returned by Google. Defaults to None.
	"""
	process_google_callback(code, state, error)


@frappe.whitelist()
@log_activity
@handle_errors
def check_google_integration():
	"""Checks if the current user has integrated their Google account.

	Returns:
		bool: True if the user has integrated their Google account, False otherwise.
	"""
	return is_google_integrated()


@frappe.whitelist()
def get_conversations():
	"""Retrieves all Gemini conversations for the current user.

	Returns:
		list[dict]: A list of conversation documents, each containing the 'name' and 'title'.
	"""
	return frappe.get_all(
		"Gemini Conversation",
		filters={"user": frappe.session.user},
		fields=["name", "title"],
		order_by="modified desc",
	)


@frappe.whitelist()
def get_conversation(conversation_id):
	"""Retrieves a specific Gemini conversation.

	Args:
		conversation_id (str): The ID of the conversation to retrieve.

	Returns:
		frappe.model.document.Document: The conversation document.

	Raises:
		frappe.PermissionError: If the user is not authorized to view the conversation.
	"""
	doc = frappe.get_doc("Gemini Conversation", conversation_id)
	if doc.user != frappe.session.user:
		frappe.throw("You are not authorized to view this conversation.")
	return doc
