import base64
import json
import re
from datetime import datetime, timedelta

import frappe
import google.generativeai as genai
import requests
from frappe.utils import get_site_url, get_url_to_form
from google.generativeai import files
from google.oauth2.credentials import Credentials

# Google API Imports
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from gemini_integration.tools import (
	get_doc_context,
	handle_errors,
	log_activity,
	search_calendar,
	search_drive,
	search_erpnext_documents,
	search_gmail,
	search_google_contacts,
)

# --- GEMINI API CONFIGURATION AND BASIC GENERATION ---


@log_activity
@handle_errors
def configure_gemini():
	"""Configures the Google Generative AI client with the API key from settings.

	Returns:
	    bool: True if configuration is successful, None otherwise.
	"""
	settings = frappe.get_single("Gemini Settings")
	api_key = settings.get_password("api_key")
	if not api_key:
		frappe.log_error("Gemini API Key not found in Gemini Settings.", "Gemini Integration")
		return None
	try:
		genai.configure(api_key=api_key)
		return True
	except Exception as e:
		frappe.log_error(f"Failed to configure Gemini: {e!s}", "Gemini Integration")
		return None


@log_activity
@handle_errors
def generate_text(prompt, model_name=None, uploaded_files=None):
	"""Generates text using a specified Gemini model.

	Args:
	    prompt (str): The text prompt for the model.
	    model_name (str, optional): The name of the model to use.
	        If not provided, the default model from settings will be used.
	        Defaults to None.
	    uploaded_files (list, optional): A list of uploaded files to include
	        in the context. Defaults to None.

	Returns:
	    str: The generated text from the model.
	"""
	if not configure_gemini():
		frappe.throw("Gemini integration is not configured. Please set the API Key in Gemini Settings.")

	if not model_name:
		model_name = frappe.db.get_single_value("Gemini Settings", "default_model") or "gemini-2.5-pro"

	try:
		model_instance = genai.GenerativeModel(model_name)
		if uploaded_files:
			response = model_instance.generate_content([prompt] + uploaded_files)
		else:
			response = model_instance.generate_content(prompt)
		return response.text
	except Exception as e:
		frappe.log_error(f"Gemini API Error: {e!s}", "Gemini Integration")
		frappe.throw(
			"An error occurred while communicating with the Gemini API. Please check the Error Log for details."
		)


# --- OAUTH AND GOOGLE API FUNCTIONS ---


@log_activity
@handle_errors
def get_google_settings():
	"""Retrieves Google settings from Social Login Keys.

	Returns:
	    frappe.model.document.Document: The Google Social Login Key document.
	"""
	settings = frappe.get_doc("Social Login Key", "Google")
	if not settings or not settings.enable_social_login:
		frappe.throw("Google Login is not enabled in Social Login Keys.")
	return settings


@log_activity
@handle_errors
def get_google_flow():
	"""Builds the Google OAuth 2.0 Flow object for authentication.

	Returns:
	    google_auth_oauthlib.flow.Flow: The configured Google OAuth 2.0 Flow object.
	"""
	settings = get_google_settings()
	redirect_uri = (
		get_site_url(frappe.local.site) + "/api/method/gemini_integration.api.handle_google_callback"
	)
	client_secrets = {
		"web": {
			"client_id": settings.client_id,
			"client_secret": settings.get_password("client_secret"),
			"auth_uri": "https://accounts.google.com/o/oauth2/auth",
			"token_uri": "https://oauth2.googleapis.com/token",
		}
	}
	# Scopes define the level of access to the user's Google data.
	scopes = [
		"https://www.googleapis.com/auth/userinfo.email",
		"openid",
		"https://www.googleapis.com/auth/gmail.modify",
		"https://www.googleapis.com/auth/drive",
		"https://www.googleapis.com/auth/calendar",
		"https://www.googleapis.com/auth/contacts.readonly",
	]
	return Flow.from_client_config(client_secrets, scopes=scopes, redirect_uri=redirect_uri)


@log_activity
@handle_errors
def get_google_auth_url():
	"""Generates the authorization URL for the user to grant consent.

	Returns:
	    str: The Google authorization URL.
	"""
	flow = get_google_flow()
	authorization_url, state = flow.authorization_url(access_type="offline", prompt="consent")
	# Store the state in cache to prevent CSRF attacks.
	frappe.cache().set_value(f"google_oauth_state_{frappe.session.user}", state, expires_in_sec=600)
	return authorization_url


@log_activity
@handle_errors
def process_google_callback(code, state, error):
	"""Handles the OAuth callback from Google, exchanges the code for tokens, and stores them.

	Args:
	    code (str): The authorization code received from Google.
	    state (str): The state parameter for CSRF protection.
	    error (str): Any error returned by Google.
	"""
	if error:
		frappe.log_error(f"Google OAuth Error: {error}", "Gemini Integration")
		frappe.respond_as_web_page(
			"Google Authentication Failed", f"An error occurred: {error}", http_status_code=401
		)
		return

	cached_state = frappe.cache().get_value(f"google_oauth_state_{frappe.session.user}")
	if not cached_state or cached_state != state:
		frappe.log_error("Google OAuth State Mismatch", "Gemini Integration")
		frappe.respond_as_web_page(
			"Authentication Failed", "State mismatch. Please try again.", http_status_code=400
		)
		return

	try:
		flow = get_google_flow()
		flow.fetch_token(code=code)
		creds = flow.credentials

		# Get user's email to store alongside the token for reference.
		userinfo_service = build("oauth2", "v2", credentials=creds)
		user_info = userinfo_service.userinfo().get().execute()
		google_email = user_info.get("email")

		# Create or update the Google User Token document for the current user.
		if frappe.db.exists("Google User Token", {"user": frappe.session.user}):
			token_doc = frappe.get_doc("Google User Token", {"user": frappe.session.user})
		else:
			token_doc = frappe.new_doc("Google User Token")
			token_doc.user = frappe.session.user

		token_doc.google_email = google_email
		token_doc.access_token = creds.token
		if creds.refresh_token:
			token_doc.refresh_token = creds.refresh_token
		token_doc.scopes = " ".join(creds.scopes) if creds.scopes else ""
		token_doc.save(ignore_permissions=True)
		frappe.db.commit()

	except Exception as e:
		frappe.log_error(str(e), "Gemini Google Callback")
		frappe.respond_as_web_page(
			"Error", "An unexpected error occurred while saving your credentials.", http_status_code=500
		)
		return

	# Show a success page to the user.
	frappe.respond_as_web_page(
		"Successfully Connected!",
		"""<div style='text-align: center; padding: 40px;'>
              <h2>Your Google Account has been successfully connected.</h2>
              <p>You can now close this tab and return to the Gemini Chat page in ERPNext.</p>
           </div>""",
		indicator_color="green",
	)


@log_activity
@handle_errors
def is_google_integrated():
	"""Checks if a valid token exists for the current user.

	Returns:
	    bool: True if a token exists, False otherwise.
	"""
	return frappe.db.exists("Google User Token", {"user": frappe.session.user})


@log_activity
@handle_errors
def get_user_credentials():
	"""Retrieves stored credentials for the current user from the database.

	Returns:
	    google.oauth2.credentials.Credentials: The user's credentials, or None if not found.
	"""
	if not is_google_integrated():
		return None
	try:
		token_doc = frappe.get_doc("Google User Token", {"user": frappe.session.user})
		return Credentials(
			token=token_doc.access_token,
			refresh_token=token_doc.refresh_token,
			token_uri="https://oauth2.googleapis.com/token",
			client_id=get_google_settings().client_id,
			client_secret=get_google_settings().get_password("client_secret"),
			scopes=token_doc.scopes.split(" ") if token_doc.scopes else [],
		)
	except Exception as e:
		frappe.log_error(f"Could not get user credentials: {e}", "Gemini Integration")
		return None


# --- GOOGLE SERVICE-SPECIFIC FUNCTIONS ---


# --- GOOGLE SERVICE-SPECIFIC FUNCTIONS ---


@log_activity
@handle_errors
def get_drive_file_for_analysis(credentials, file_id):
	"""Gets a Google Drive file, uploads it to Gemini, and returns the file reference.

	Args:
	    credentials (google.oauth2.credentials.Credentials): The user's credentials.
	    file_id (str): The ID of the Google Drive file.

	Returns:
	    google.generativeai.files.File: The uploaded file object, or None on failure.
	"""
	try:
		# Get the file content from Google Drive
		file_content = get_drive_file_context(credentials, file_id)

		if file_content:
			# Upload the file to Gemini
			uploaded_file = upload_file_to_gemini(file_id, file_content)
			if uploaded_file:
				# Store the file reference in the cache
				frappe.cache().set_value(f"gemini_file_{file_id}", uploaded_file)
				return uploaded_file
	except Exception as e:
		frappe.log_error(f"Error getting drive file for analysis: {e!s}")
		return None


@log_activity
@handle_errors
def upload_file_to_gemini(file_name, file_content):
	"""Uploads a file to the Gemini API.

	Args:
	    file_name (str): The name of the file.
	    file_content (bytes): The content of the file.

	Returns:
	    google.generativeai.files.File: The uploaded file object, or None on failure.
	"""
	try:
		# Upload the file to the Gemini API
		uploaded_file = genai.upload_file(path=file_content, display_name=file_name)
		return uploaded_file
	except Exception as e:
		frappe.log_error(f"Gemini File API Error: {e!s}", "Gemini Integration")
		return None


@log_activity
@handle_errors
def get_erpnext_file_content(file_url):
	"""Gets the content of an ERPNext file.

	Args:
	    file_url (str): The URL of the file in ERPNext.

	Returns:
	    bytes: The content of the file, or None on failure.
	"""
	try:
		# Get the file from ERPNext
		file_doc = frappe.get_doc("File", {"file_url": file_url})
		return file_doc.get_content()
	except Exception as e:
		frappe.log_error(f"ERPNext File Error: {e!s}", "Gemini Integration")
		return None


# --- MAIN CHAT FUNCTIONALITY ---


@log_activity
@handle_errors
def generate_chat_response(prompt, model=None, conversation_id=None):
	"""Handles chat interactions by routing them to the correct MCP tools.

	Args:
	    prompt (str): The user's chat prompt.
	    model (str, optional): The model to use for the chat. Defaults to None.
	    conversation_id (str, optional): The ID of the existing conversation. Defaults to None.

	Returns:
	    dict: A dictionary containing the response, thoughts, and conversation ID.
	"""
	from gemini_integration.mcp import mcp

	conversation_history = []
	if conversation_id:
		try:
			conversation_doc = frappe.get_doc("Gemini Conversation", conversation_id)
			if conversation_doc.conversation:
				conversation_history = json.loads(conversation_doc.conversation)
		except frappe.DoesNotExistError:
			pass

	# 1. Determine which toolsets to use based on @-mentions
	mentioned_services = re.findall(r"@(\w+)", prompt)
	if not mentioned_services:
		mentioned_services = ["erpnext"]  # Default to ERPNext if no service is mentioned

	# 2. Get user credentials if any Google services are mentioned
	# This part can be improved to be more dynamic based on tool requirements
	kwargs = {}
	google_services = ["gmail", "drive", "calendar"]
	if any(service in mentioned_services for service in google_services):
		creds = get_user_credentials()
		if creds:
			kwargs["credentials"] = creds
		else:
			# Handle case where user is not authenticated with Google
			return {
				"response": "Please connect your Google account to use this feature.",
				"thoughts": "User is not authenticated with Google.",
				"conversation_id": conversation_id,
			}

	# 3. Execute the prompt using the MCP server
	response = mcp.run(prompt, **kwargs)

	# 5. Save the conversation
	conversation_history.append({"role": "user", "text": prompt})
	conversation_history.append({"role": "gemini", "text": response["response"]})
	conversation_id = save_conversation(conversation_id, prompt, conversation_history)

	return {
		"response": response["response"],
		"thoughts": response["thoughts"],
		"conversation_id": conversation_id,
	}


def save_conversation(conversation_id, title, conversation):
	"""Saves or updates a conversation in the database.

	Args:
	    conversation_id (str): The ID of the conversation to update, or None to create a new one.
	    title (str): The title of the conversation.
	    conversation (list): The list of conversation entries.

	Returns:
	    str: The name of the saved conversation document.
	"""
	if not conversation_id:
		# Create a new conversation
		doc = frappe.new_doc("Gemini Conversation")
		doc.title = title[:140]
		doc.user = frappe.session.user
	else:
		# Update an existing conversation
		doc = frappe.get_doc("Gemini Conversation", conversation_id)

	doc.conversation = json.dumps(conversation)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


@log_activity
@handle_errors
def record_feedback(search_query, doctype_name, document_name, is_helpful):
	"""Records user feedback on search results to improve future searches.

	Args:
	    search_query (str): The query that was searched.
	    doctype_name (str): The name of the doctype that was searched.
	    document_name (str): The name of the document that was returned.
	    is_helpful (bool): Whether the user found the result helpful.

	Returns:
	    dict: A dictionary with the status of the operation.
	"""
	try:
		feedback_doc = frappe.new_doc("Gemini Search Feedback")
		feedback_doc.search_query = search_query
		feedback_doc.doctype_name = doctype_name
		feedback_doc.document_name = document_name
		feedback_doc.is_helpful = int(is_helpful)
		feedback_doc.save(ignore_permissions=True)
		frappe.db.commit()
		return {"status": "success"}
	except Exception as e:
		frappe.log_error(f"Error recording feedback: {e!s}", "Gemini Integration")
		return {"status": "error", "message": str(e)}


# --- PROJECT-SPECIFIC FUNCTIONS ---
@log_activity
@handle_errors
def generate_tasks(project_id, template):
	"""Generates a list of tasks for a project using Gemini.

	Args:
	    project_id (str): The ID of the project.
	    template (str): The template to use for task generation.

	Returns:
	    dict: A dictionary containing the generated tasks or an error message.
	"""
	if not frappe.db.exists("Project", project_id):
		return {"error": "Project not found."}

	project = frappe.get_doc("Project", project_id)
	project_details = project.as_dict()

	prompt = f"""
    Based on the following project details and the selected template '{template}', generate a list of tasks.
    Project Details: {json.dumps(project_details, indent=2, default=str)}

    Please return ONLY a valid JSON list of objects. Each object should have two keys: "subject" and "description".
    Example: [{{"subject": "Initial client meeting", "description": "Discuss project scope and deliverables."}}, ...]    """

	response_text = generate_text(prompt)
	try:
		tasks = json.loads(response_text)
		return tasks
	except json.JSONDecodeError:
		return {"error": "Failed to parse a valid JSON response from the AI. Please try again."}


@log_activity
@handle_errors
def analyze_risks(project_id):
	"""Analyzes a project for potential risks using Gemini.

	Args:
	    project_id (str): The ID of the project to analyze.

	Returns:
	    dict: A dictionary containing the identified risks or an error message.
	"""
	if not frappe.db.exists("Project", project_id):
		return {"error": "Project not found."}

	project = frappe.get_doc("Project", project_id)
	project_details = project.as_dict()

	prompt = f"""
    Analyze the following project for potential risks (e.g., timeline, budget, scope creep, resource constraints).
    Project Details: {json.dumps(project_details, indent=2, default=str)}

    Please return ONLY a valid JSON list of objects. Each object should have two keys: "risk_name" (a short title) and "risk_description".
    Example: [{{"risk_name": "Scope Creep", "risk_description": "The project description is vague, which could lead to additional client requests not in the original scope."}}, ...]    """

	response_text = generate_text(prompt)
	try:
		risks = json.loads(response_text)
		return risks
	except json.JSONDecodeError:
		return {"error": "Failed to parse a JSON response from the AI. Please try again."}
