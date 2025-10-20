import frappe

from gemini_integration.gemini import (
	analyze_risks,
	backfill_embeddings,
	generate_chat_response,
	generate_tasks,
	generate_text,
	record_feedback,
)
from gemini_integration.tools import search_drive as search_google_drive
from gemini_integration.tools import search_gmail as search_google_mail
from gemini_integration.utils import (
	get_google_auth_url,
	get_user_credentials,
	handle_errors,
	is_google_integrated,
	log_activity,
	process_google_callback,
)


@frappe.whitelist()
@log_activity
@handle_errors
def record_feedback_from_chat(search_query, doctype_name, document_name, is_helpful):
	"""Records user feedback from the chat interface.

	Args:
	    search_query (str): The query that was searched.
	    doctype_name (str): The name of the doctype that was searched.
	    document_name (str): The name of the document that was returned.
	    is_helpful (bool): Whether the user found the result helpful.

	Returns:
	    frappe.model.document.Document: The created feedback document.
	"""
	return record_feedback(search_query, doctype_name, document_name, is_helpful)


@frappe.whitelist()
@log_activity
@handle_errors
def generate(prompt, model=None):
	"""Generates text using the Gemini API.

	Args:
	    prompt (str): The text prompt to generate text from.
	    model (str, optional): The model to use for generation. Defaults to None.

	Returns:
	    str: The generated text.
	"""
	return generate_text(prompt, model)


@frappe.whitelist()
@log_activity
@handle_errors
def chat(prompt=None, model=None, conversation_id=None, use_google_search=False):
	"""Handles chat interactions with the Gemini API.

	Args:
	    prompt (str, optional): The user's chat prompt. Defaults to None.
	    model (str, optional): The model to use for the chat. Defaults to None.
	    conversation_id (str, optional): The ID of the existing conversation.
	        Defaults to None.
	    use_google_search (bool, optional): Whether to enable Google Search for this query.
	        Defaults to False.

	Returns:
	    dict: A dictionary containing the chat response and conversation ID.
	"""
	if not prompt:
		frappe.throw("A prompt is required.")
	return generate_chat_response(prompt, model, conversation_id, use_google_search)


@frappe.whitelist()
def stream_chat(prompt=None, model=None, conversation_id=None, use_google_search=False):
	"""Handles streaming chat interactions with the Gemini API."""
	if not prompt:
		frappe.throw("A prompt is required.")

	frappe.response["type"] = "csv"
	frappe.response["doctype"] = "Gemini Chat"
	frappe.response["filename"] = "response.txt"

	def streamer():
		for chunk in generate_chat_response(
			prompt, model, conversation_id, use_google_search, stream=True
		):
			yield chunk

	frappe.response["result"] = streamer()


@frappe.whitelist()
@log_activity
@handle_errors
def get_project_tasks(project_id, template):
	"""Generates project tasks based on a project ID and template.

	Args:
	    project_id (str): The ID of the project to generate tasks for.
	    template (str): The template to use for generating tasks.

	Returns:
	    list: A list of generated tasks.
	"""
	return generate_tasks(project_id, template)


@frappe.whitelist()
@log_activity
@handle_errors
def get_project_risks(project_id):
	"""Analyzes and returns the risks for a given project.

	Args:
	    project_id (str): The ID of the project to analyze.

	Returns:
	    list: A list of identified risks.
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
	    state (str, optional): The state parameter from the initial request.
	        Defaults to None.
	    error (str, optional): Any error returned by Google. Defaults to None.
	"""
	process_google_callback(code, state, error)


@frappe.whitelist()
@log_activity
@handle_errors
def check_google_integration():
	"""Checks if the current user has integrated their Google account.

	Returns:
	    bool: True if the account is integrated, False otherwise.
	"""
	return is_google_integrated()


@frappe.whitelist()
@log_activity
@handle_errors
def search_drive(query):
	"""Searches for files in Google Drive.

	Args:
	    query (str): The search query.

	Returns:
	    list: A list of files matching the query.
	"""
	creds = get_user_credentials()
	if not creds:
		frappe.throw("Google account not integrated.")
	return search_google_drive(creds, query)


@frappe.whitelist()
@log_activity
@handle_errors
def search_mail(query):
	"""Searches for emails in a user's Gmail account.

	Args:
	    query (str): The search query.

	Returns:
	    list: A list of emails matching the query.
	"""
	creds = get_user_credentials()
	if not creds:
		frappe.throw("Google account not integrated.")
	return search_google_mail(creds, query)


@frappe.whitelist()
def get_conversations():
	"""Retrieves all Gemini conversations for the current user.

	Returns:
	    list: A list of conversations, sorted by modification date.
	"""
	return frappe.get_all(
		"Gemini Conversation",
		filters={"user": frappe.session.user},
		fields=["name", "title"],
		order_by="modified desc",
	)


@frappe.whitelist()
def get_conversation(conversation_id):
	"""Retriees a specific Gemini conversation.

	Args:
	    conversation_id (str): The ID of the conversation to retrieve.

	Returns:
	    frappe.model.document.Document: The conversation document.
	"""
	doc = frappe.get_doc("Gemini Conversation", conversation_id)
	if doc.user != frappe.session.user:
		frappe.throw("You are not authorized to view this conversation.")
	return doc


@frappe.whitelist()
def enqueue_backfill_embeddings():
	"""Enqueues the backfill_embeddings function to run as a background job."""
	frappe.enqueue(
		"gemini_integration.gemini.backfill_embeddings",
		queue="long",
		timeout=1500,
	)
	return {"status": "success", "message": "Embedding backfill process has been started."}
