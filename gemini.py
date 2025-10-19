import base64
import io
import json
import re
from datetime import datetime, timedelta

import frappe
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
from frappe.utils import get_site_url, get_url_to_form
from google.generativeai import files
from google.oauth2.credentials import Credentials

# Google API Imports
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from PyPDF2 import PdfReader

from gemini_integration.mcp import mcp
from gemini_integration.utils import (
	get_doc_context,
	get_dynamic_doctype_map,
	handle_errors,
	log_activity,
	search_erpnext_documents,
)

# --- GEMINI API CONFIGURATION AND BASIC GENERATION ---


@log_activity
@handle_errors
def configure_gemini():
	"""Configures the Google Generative AI client with the API key from settings."""
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
def generate_text(prompt, model_name=None, uploaded_files=None, generation_config=None):
	"""Generates text using a specified Gemini model."""
	if not configure_gemini():
		frappe.throw("Gemini integration is not configured. Please set the API Key in Gemini Settings.")

	if not model_name:
		model_name = frappe.db.get_single_value("Gemini Settings", "default_model") or "gemini-2.5-pro"

	if generation_config is None:
		generation_config = {}
	if "max_output_tokens" not in generation_config:
		if model_name in ["gemini-2.5-pro", "gemini-2.5-flash"]:
			generation_config["max_output_tokens"] = 8192

	try:
		model_instance = genai.GenerativeModel(model_name)
		if uploaded_files:
			response = model_instance.generate_content(
				[prompt, *uploaded_files], generation_config=generation_config
			)
		else:
			response = model_instance.generate_content([prompt], generation_config=generation_config)
		return response.text
	except Exception as e:
		frappe.log_error(f"Gemini API Error: {e!s}", "Gemini Integration")
		frappe.throw(
			"An error occurred while communicating with the Gemini API. Please check the Error Log for details."
		)


# --- URL CONTEXT FETCHING ---


@log_activity
def extract_urls(text):
	"""Extracts all URLs from a given text."""
	url_pattern = r"https?://[^\s/$.?#].[^\s]*"
	return re.findall(url_pattern, text)


@handle_errors
def get_html_content(url):
	"""Fetches and extracts text content from a HTML URL."""
	try:
		response = requests.get(url, timeout=10)
		response.raise_for_status()
		soup = BeautifulSoup(response.content, "html.parser")
		return soup.get_text(separator=" ", strip=True)
	except requests.RequestException as e:
		frappe.log_error(f"Error fetching URL {url}: {e}", "Gemini URL Fetcher")
		return None


@handle_errors
def get_pdf_content(url):
	"""Fetches and extracts text content from a PDF URL."""
	try:
		response = requests.get(url, timeout=20)
		response.raise_for_status()
		with io.BytesIO(response.content) as f:
			reader = PdfReader(f)
			text = ""
			for page in reader.pages:
				text += page.extract_text() or ""
		return text
	except requests.RequestException as e:
		frappe.log_error(f"Error fetching PDF from {url}: {e}", "Gemini URL Fetcher")
		return None
	except Exception as e:
		frappe.log_error(f"Error parsing PDF from {url}: {e}", "Gemini URL Fetcher")
		return None


@log_activity
def get_url_context(urls):
	"""Fetches content from a list of URLs, respecting a blacklist, and returns a formatted context string."""
	full_context = ""
	settings = frappe.get_single("Gemini Settings")
	blacklist_str = settings.get("url_blacklist", "")
	blacklist = [item.strip() for item in blacklist_str.split("\n") if item.strip()]

	for url in urls:
		is_blacklisted = any(bl_item in url for bl_item in blacklist)

		if is_blacklisted:
			full_context += f"(System: The URL '{url}' was skipped because it is on the blacklist.)\n\n"
			continue

		try:
			headers = requests.head(url, timeout=5, allow_redirects=True)
			headers.raise_for_status()
			content_type = headers.headers.get("Content-Type", "")

			content = None
			if "application/pdf" in content_type:
				content = get_pdf_content(url)
			elif "text/html" in content_type:
				content = get_html_content(url)
			else:
				# Fallback for other text-based content types
				content = get_html_content(url)

			if content is not None:
				full_context += f"Content from URL '{url}':\n{content[:5000]}\n\n"  # Limit content length
			else:
				# This happens if get_pdf_content or get_html_content return None.
				# Their internal errors are already logged. We throw a clear error here.
				frappe.throw(f"Failed to retrieve or parse content from URL: {url}")
		except requests.RequestException as e:
			frappe.throw(f"Could not access URL: {url}. Error: {e}")

	return full_context


# --- OAUTH AND GOOGLE API FUNCTIONS ---


@log_activity
@handle_errors
def get_google_settings():
	"""Retrieves Google settings from Social Login Keys."""
	settings = frappe.get_doc("Social Login Key", "Google")
	if not settings or not settings.enable_social_login:
		frappe.throw("Google Login is not enabled in Social Login Keys.")
	return settings


@log_activity
@handle_errors
def get_google_flow():
	"""Builds the Google OAuth 2.0 Flow object for authentication."""
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
	scopes = [
		"https://www.googleapis.com/auth/userinfo.email",
		"openid",
		"https://www.googleapis.com/auth/gmail.readonly",
		"https://www.googleapis.com/auth/drive.readonly",
		"https://www.googleapis.com/auth/calendar.readonly",
		"https://www.googleapis.com/auth/contacts.readonly",
	]
	return Flow.from_client_config(client_secrets, scopes=scopes, redirect_uri=redirect_uri)


@log_activity
@handle_errors
def get_google_auth_url():
	"""Generates the authorization URL for the user to grant consent."""
	flow = get_google_flow()
	authorization_url, state = flow.authorization_url(access_type="offline", prompt="consent")
	frappe.cache().set_value(f"google_oauth_state_{frappe.session.user}", state, expires_in_sec=600)
	return authorization_url


@log_activity
@handle_errors
def process_google_callback(code, state, error):
	"""Handles the OAuth callback from Google, exchanges the code for tokens, and stores them."""
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
		userinfo_service = build("oauth2", "v2", credentials=creds)
		user_info = userinfo_service.userinfo().get().execute()
		google_email = user_info.get("email")

		doc_name = frappe.db.get_value("Google User Token", {"user": frappe.session.user}, "name")
		if doc_name:
			token_doc = frappe.get_doc("Google User Token", doc_name)
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

	frappe.respond_as_web_page(
		"Successfully Connected!",
		"<div style='text-align: center; padding: 40px;'><h2>Your Google Account has been successfully connected.</h2><p>You can now close this tab.</p></div>",
		indicator_color="green",
	)


@log_activity
@handle_errors
def is_google_integrated():
	"""Checks if a valid token exists for the current user."""
	return frappe.db.exists("Google User Token", {"user": frappe.session.user})


@log_activity
@handle_errors
def get_user_credentials():
	"""Retrieves stored credentials for the current user."""
	if not is_google_integrated():
		return None
	try:
		doc_name = frappe.db.get_value("Google User Token", {"user": frappe.session.user}, "name")
		if not doc_name:
			return None
		token_doc = frappe.get_doc("Google User Token", doc_name)
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


# --- MAIN CHAT FUNCTIONALITY ---




@log_activity
@handle_errors
def generate_chat_response(
	prompt, model=None, conversation_id=None, selected_options=None, generation_config=None
):
	"""
	Orchestrates chat interactions using a tool-calling model.
	"""
	configure_gemini()
	# The new implementation will use the tool-calling features of the `google-generativeai` library.
	# It will pass the MCP tool definitions to the Gemini model, execute the function calls
	# requested by the model, and return the final response.

	# 1. Define the tool-calling model
	model_name = model or frappe.db.get_single_value("Gemini Settings", "default_model") or "gemini-1.5-pro"
	# Pass the MCP tools to the model
	tool_model = genai.GenerativeModel(model_name, tools=list(mcp._tool_registry.values()))

	# 2. Start a chat session
	chat = tool_model.start_chat()
	# 3. Send the user's prompt
	response = chat.send_message(prompt)

	# 4. Handle function calls
	while response.function_calls:
		# Execute the function calls requested by the model
		for func_call in response.function_calls:
			# Get the tool definition from the MCP instance
			tool = mcp._tool_registry.get(func_call.name)
			if not tool:
				# If the tool is not found, return an error to the model
				response = chat.send_message(
					f"Tool {func_call.name} not found.", role="function", is_response=True
				)
				continue

			# Execute the tool's function with the provided arguments
			try:
				result = tool.fn(**func_call.args)
				# Send the result back to the model
				response = chat.send_message(
					{"function_response": {"name": func_call.name, "content": result}},
					is_response=True,
				)
			except Exception as e:
				# If an error occurs during tool execution, return an error to the model
				response = chat.send_message(
					f"Error executing tool {func_call.name}: {e}", role="function", is_response=True
				)

	# 5. Save the conversation
	conversation_history = []
	if conversation_id:
		try:
			conv_doc = frappe.get_doc("Gemini Conversation", conversation_id)
			if conv_doc.conversation:
				conversation_history = json.loads(conv_doc.conversation)
		except frappe.DoesNotExistError:
			pass

	conversation_history.append({"role": "user", "text": prompt})
	conversation_history.append({"role": "gemini", "text": response.text})
	new_conversation_id = save_conversation(conversation_id, prompt, conversation_history)

	# 6. Return the final response
	return {
		"response": response.text,
		"conversation_id": new_conversation_id,
		"clarification_needed": False,
	}


def save_conversation(conversation_id, title, conversation):
	"""Saves or updates a conversation in the database."""
	if not conversation_id:
		doc = frappe.new_doc("Gemini Conversation")
		doc.title = title[:140]
		doc.user = frappe.session.user
	else:
		doc = frappe.get_doc("Gemini Conversation", conversation_id)

	doc.conversation = json.dumps(conversation)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


# --- PROJECT-SPECIFIC FUNCTIONS ---
@log_activity
@handle_errors
def generate_tasks(project_id, template):
	"""Generates a list of tasks for a project using Gemini."""
	if not frappe.db.exists("Project", project_id):
		return {"error": "Project not found."}
	project = frappe.get_doc("Project", project_id)
	prompt = f'Based on the project details and the template \'{template}\', generate a list of tasks.\nProject: {json.dumps(project.as_dict(), default=str)}\n\nReturn ONLY a valid JSON list of objects with keys "subject" and "description".'
	response_text = generate_text(prompt)
	try:
		return json.loads(response_text)
	except json.JSONDecodeError:
		return {"error": "Failed to parse a valid JSON response from the AI."}


@log_activity
@handle_errors
def analyze_risks(project_id):
	"""Analyzes a project for potential risks using Gemini."""
	if not frappe.db.exists("Project", project_id):
		return {"error": "Project not found."}
	project = frappe.get_doc("Project", project_id)
	prompt = f'Analyze the project for potential risks (e.g., timeline, budget, scope creep).\nProject: {json.dumps(project.as_dict(), default=str)}\n\nReturn ONLY a valid JSON list of objects with keys "risk_name" and "risk_description".'
	response_text = generate_text(prompt)
	try:
		return json.loads(response_text)
	except json.JSONDecodeError:
		return {"error": "Failed to parse a JSON response from the AI."}
