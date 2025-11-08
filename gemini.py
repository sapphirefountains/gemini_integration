import base64
import io
import json
import re
from datetime import datetime, timedelta

import frappe
import google.generativeai as genai
from google.generativeai import types
import markdown
import requests
from bs4 import BeautifulSoup
from frappe.utils import get_site_url, get_url_to_form
from google.oauth2.credentials import Credentials

# Google API Imports
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from PyPDF2 import PdfReader

from gemini_integration.mcp import mcp
from gemini_integration.utils import (
	get_doc_context,
	get_drive_file_context,
	get_dynamic_doctype_map,
	handle_errors,
	log_activity,
	search_erpnext_documents,
)

# --- GEMINI API CONFIGURATION AND BASIC GENERATION ---


@log_activity
@handle_errors
def configure_gemini():
	"""Configures and returns the Google GenAI client with the API key from settings.

	Returns:
		google.genai.Client or None: The configured client instance, or None if configuration fails.
	"""
	settings = frappe.get_single("Gemini Settings")
	api_key = settings.get_password("api_key")
	if not api_key:
		frappe.log_error("Gemini API Key not found in Gemini Settings.", "Gemini Integration")
		return None
	try:
		# The new SDK uses a client object.
		client = genai.Client(api_key=api_key)
		return client
	except Exception as e:
		frappe.log_error(f"Failed to configure Gemini: {e!s}", "Gemini Integration")
		return None


@log_activity
@handle_errors
def generate_text(prompt, model_name=None, uploaded_files=None, config=None):
	"""Generates text using a specified Gemini model via the new GenAI SDK.

	Args:
		prompt (str): The text prompt to send to the model.
		model_name (str, optional): The name of the Gemini model to use. Defaults to the
			one specified in settings or 'gemini-2.5-pro'.
		uploaded_files (list, optional): A list of files to include in the prompt.
			Defaults to None.
		config (dict, optional): Configuration for the generation process.
			Defaults to None.

	Returns:
		str: The generated text from the model.

	Raises:
		frappe.Throw: If the Gemini integration is not configured.
	"""
	client = configure_gemini()
	if not client:
		frappe.throw("Gemini integration is not configured. Please set the API Key in Gemini Settings.")

	model_to_use = (
		model_name or frappe.db.get_single_value("Gemini Settings", "default_model") or "gemini-1.5-pro"
	)

	generation_config = config or {}
	if "max_output_tokens" not in generation_config:
		if model_to_use in ["gemini-2.5-pro", "gemini-2.5-flash"]:
			generation_config["max_output_tokens"] = 8192

	contents = [prompt]
	if uploaded_files:
		contents.extend(uploaded_files)

	try:
		# The new SDK uses a stateless function on the client's `models` service.
		response = client.models.generate_content(
			model=model_to_use, contents=contents, config=generation_config
		)
		return response.text
	except Exception as e:
		frappe.log_error(f"Gemini API Error: {e!s}", "Gemini Integration")
		frappe.throw(
			"An error occurred while communicating with the Gemini API. Please check the Error Log for details."
		)


@log_activity
@handle_errors
def generate_embedding(text, model_name="embedding-001"):
	"""Generates an embedding for a given text using the new GenAI SDK.

	Args:
		text (str): The text to embed.
		model_name (str, optional): The name of the embedding model to use.
			Defaults to 'embedding-001'.

	Returns:
		list[float] or None: The generated embedding vector, or None if an error occurs.
	"""
	client = configure_gemini()
	if not client:
		frappe.throw("Gemini integration is not configured.")
	try:
		# The new SDK uses a stateless function on the client's `models` service.
		result = client.models.embed_content(model=f"models/{model_name}", contents=text)
		# The new SDK returns a pydantic model, access embedding via attribute
		return result.embedding
	except Exception as e:
		frappe.log_error(f"Gemini Embedding Error: {e!s}", "Gemini Integration")
		return None


def get_text_representation_for_doc(doc):
	"""Creates a unified text string from a document's fields for embedding.

	This function is more sophisticated and includes:
	- Metadata: creation, owner, modified, modified_by, status, and docstatus.
	- Field Weighting: Fetches rules from Gemini Settings to repeat important fields.
	- Child Table Data: Includes data from child tables as HTML tables.

	Args:
		doc (frappe.model.document.Document): The document to process.

	Returns:
		str: A single string concatenating the document's important fields.
	"""
	text_parts = []
	meta = frappe.get_meta(doc.doctype)
	settings = frappe.get_single("Gemini Settings")

	# 1. Add Metadata
	metadata = []
	if hasattr(doc, "creation") and doc.creation:
		metadata.append(f"Document created on {doc.creation.strftime('%B %d, %Y')}")
	if hasattr(doc, "owner"):
		metadata.append(f"by {doc.owner}")
	if hasattr(doc, "modified") and doc.modified:
		metadata.append(f"last modified on {doc.modified.strftime('%B %d, %Y')}")
	if hasattr(doc, "modified_by"):
		metadata.append(f"by {doc.modified_by}")
	if hasattr(doc, "status"):
		metadata.append(f"with status '{doc.status}'")
	if hasattr(doc, "docstatus"):
		docstatus_map = {0: "Draft", 1: "Submitted", 2: "Cancelled"}
		metadata.append(f"and is currently {docstatus_map.get(doc.docstatus, 'Unknown')}")

	if metadata:
		# Filter out empty strings before joining
		full_metadata_str = ", ".join(filter(None, metadata))
		text_parts.append(f"This document is a {doc.doctype}. {full_metadata_str}.")

	# 2. Field Weighting Setup
	field_weights = {}
	if settings.field_weights:
		for item in settings.field_weights:
			if item.doctype_name == doc.doctype:
				field_weights[item.field_name] = item.weight

	# 3. Process main fields with weighting
	for field in meta.fields:
		if field.fieldtype in ["Data", "Text", "Small Text", "Long Text", "Select"]:
			value = doc.get(field.fieldname)
			if value:
				# Default weight is 1
				weight = field_weights.get(field.fieldname, 1)
				field_text = f"{field.label}: {value}"
				text_parts.extend([field_text] * weight)

	# 4. Process Child Tables
	for field in meta.fields:
		if field.fieldtype == "Table":
			child_docs = doc.get(field.fieldname)
			if not child_docs:
				continue

			text_parts.append(f"\n--- {field.label} ---\n")
			child_meta = frappe.get_meta(field.options)

			# Header
			headers = [child_field.label for child_field in child_meta.fields if child_field.in_list_view]
			md_table = f"| {' | '.join(headers)} |\n"
			md_table += f"| {' | '.join(['---'] * len(headers))} |\n"

			# Rows
			for child_doc in child_docs:
				row_values = []
				for child_field in child_meta.fields:
					if child_field.in_list_view:
						value = child_doc.get(child_field.fieldname)
						row_values.append(str(value) if value is not None else "")
				md_table += f"| {' | '.join(row_values)} |\n"

			# Convert to HTML
			html_table = markdown.markdown(md_table, extensions=["tables"])
			text_parts.append(html_table)

	return "\n".join(text_parts)


@log_activity
@handle_errors
def generate_embedding_for_doc(doc, on_save=True):
	"""Generates and saves an embedding for a specific document.

	Args:
		doc (frappe.model.document.Document): The document to embed.
		on_save (bool): A flag to indicate if the call is from a save hook.
	"""
	text_representation = get_text_representation_for_doc(doc)
	if not text_representation:
		return

	embedding = generate_embedding(text_representation)
	if not embedding:
		return

	# Save the embedding
	embedding_doc_name = frappe.db.get_value(
		"Gemini Embedding",
		{"ref_doctype": doc.doctype, "ref_docname": doc.name},
		"name",
	)
	if embedding_doc_name:
		embedding_doc = frappe.get_doc("Gemini Embedding", embedding_doc_name)
	else:
		embedding_doc = frappe.new_doc("Gemini Embedding")
		embedding_doc.ref_doctype = doc.doctype
		embedding_doc.ref_docname = doc.name

	embedding_doc.embedding = json.dumps(embedding)
	embedding_doc.save(ignore_permissions=True)
	if on_save:
		frappe.db.commit()


# --- URL CONTEXT FETCHING ---


@log_activity
def extract_urls(text):
	"""Extracts all URLs from a given text.

	Args:
		text (str): The text to search for URLs.

	Returns:
		list[str]: A list of URLs found in the text.
	"""
	url_pattern = r"https?://[^\s/$.?#].[^\s]*"
	return re.findall(url_pattern, text)


@handle_errors
def get_html_content(url):
	"""Fetches and extracts text content from a HTML URL.

	Args:
		url (str): The URL of the HTML page.

	Returns:
		str or None: The extracted text content, or None if an error occurs.
	"""
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
	"""Fetches and extracts text content from a PDF URL.

	Args:
		url (str): The URL of the PDF file.

	Returns:
		str or None: The extracted text content, or None if an error occurs.
	"""
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
	"""Fetches content from a list of URLs, respecting a blacklist, and returns a formatted context string.

	Args:
		urls (list[str]): A list of URLs to fetch content from.

	Returns:
		str: A formatted string containing the content from the URLs.
	"""
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
	"""Retrieves Google settings from Social Login Keys.

	Returns:
		frappe.model.document.Document: The 'Social Login Key' document for Google.

	Raises:
		frappe.Throw: If Google Login is not enabled.
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
		google_auth_oauthlib.flow.Flow: The configured Flow object.
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
	"""Generates the authorization URL for the user to grant consent.

	Returns:
		str: The Google authorization URL.
	"""
	flow = get_google_flow()
	authorization_url, state = flow.authorization_url(access_type="offline", prompt="consent")
	frappe.cache().set_value(f"google_oauth_state_{frappe.session.user}", state, expires_in_sec=600)
	return authorization_url


@log_activity
@handle_errors
def process_google_callback(code, state, error):
	"""Handles the OAuth callback from Google, exchanges the code for tokens, and stores them.

	Args:
		code (str): The authorization code from Google.
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
	"""Checks if a valid token exists for the current user.

	Returns:
		bool: True if a token exists, False otherwise.
	"""
	return frappe.db.exists("Google User Token", {"user": frappe.session.user})


@log_activity
@handle_errors
def get_user_credentials():
	"""Retrieves stored credentials for the current user.

	Returns:
		google.oauth2.credentials.Credentials or None: The user's credentials,
		or None if not found or an error occurs.
	"""
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


def _uppercase_schema_values(obj):
	"""Recursively converts all JSON schema 'type' values to uppercase.

	Args:
		obj (dict or list): The JSON schema object or a part of it.

	Returns:
		dict or list: The schema with 'type' values uppercased.
	"""
	if isinstance(obj, dict):
		# Handle the case where 'type' is a key
		if "type" in obj and isinstance(obj["type"], str):
			obj["type"] = obj["type"].upper()
		# Recurse through dictionary values
		return {k: _uppercase_schema_values(v) for k, v in obj.items()}
	elif isinstance(obj, list):
		# Recurse through list elements
		return [_uppercase_schema_values(elem) for elem in obj]
	else:
		return obj


def _sanitize_tools(mcp_instance):
	"""Sanitizes tool definitions from the MCP registry to be compatible with the Google Generative AI SDK.

	This involves:
	1. Whitelisting only the 'name', 'description', and 'parameters' keys.
	2. Ensuring the parameter schema has a top-level 'type: object'.
	3. Recursively converting all schema 'type' values to uppercase.

	Args:
		mcp_instance (gemini_integration.mcp.MCP): The MCP instance containing the tool registry.

	Returns:
		list[dict]: A list of sanitized tool definitions ready for the Google SDK.
	"""
	sanitized_tools = []
	if not hasattr(mcp_instance, "_tool_registry"):
		return []

	# Accessing the private registry is the intended pattern for this library.
	for _tool_name, tool_def in mcp_instance._tool_registry.items():
		# 1. Whitelist keys and rename 'input_schema' to 'parameters'.
		# The 'fn' key contains the actual function object, which is not serializable
		# and not needed by the Google API.
		parameters = tool_def.get("input_schema", {})

		# 2. Ensure the parameter schema has the required top-level 'type: object'.
		if "properties" in parameters and parameters.get("type") != "object":
			parameters = {
				"type": "object",
				"properties": parameters.get("properties", {}),
				"required": parameters.get("required", []),
			}

		sanitized_tool = {
			"name": tool_def.get("name"),
			"description": tool_def.get("description"),
			"parameters": parameters,
		}

		# 3. Recursively convert all schema type values to uppercase for SDK compatibility.
		sanitized_tool = _uppercase_schema_values(sanitized_tool)
		sanitized_tools.append(sanitized_tool)

	return sanitized_tools


@log_activity
@handle_errors
def generate_chat_response(
	prompt, model=None, conversation_id=None, selected_options=None, config=None
):
	"""Orchestrates chat interactions using the new GenAI SDK.

	This is the main entry point for handling user chat requests. It performs the
	following steps:
	1. Configures the Gemini client.
	2. Loads existing conversation history.
	3. Fetches and injects context from any URLs in the prompt.
	4. Configures the model with available tools and system instructions.
	5. Initializes the chat and enters a loop to handle tool calls.
	6. Executes tool calls and sends the results back to the model.
	7. Saves the updated conversation history.
	8. Returns the final response to the user.

	Args:
		prompt (str): The user's chat message.
		model (str, optional): The Gemini model to use. Defaults to settings.
		conversation_id (str, optional): The ID of the conversation to continue.
		selected_options (dict, optional): Not currently used.
		config (dict, optional): Configuration for the generation process.

	Returns:
		dict: A dictionary containing the response text and conversation ID.
	"""
	# --- 1. Initial Setup and Configuration ---
	client = configure_gemini()
	if not client:
		frappe.throw("Gemini integration is not configured. Please set the API Key in Gemini Settings.")

	# --- 2. Load Conversation History ---
	conversation_history = []
	if conversation_id:
		try:
			conv_doc = frappe.get_doc("Gemini Conversation", conversation_id)
			if conv_doc.conversation:
				stored_history = json.loads(conv_doc.conversation)
				for item in stored_history:
					role = "user" if item["role"] == "user" else "model"
					if item["role"] != "tool_context":
						conversation_history.append({"role": role, "parts": [item["text"]]})
		except (frappe.DoesNotExistError, json.JSONDecodeError):
			conversation_id = None  # Start new if history is invalid

	# --- 3. URL and Document Context Injection ---
	urls = extract_urls(prompt)
	if urls:
		url_context = get_url_context(urls)
		prompt += f"\n\n--- Content from URLs ---\n{url_context}"

	# --- 4. Tool and Model Configuration ---
	gemini_settings = frappe.get_single("Gemini Settings")
	model_name = model or gemini_settings.default_model or "gemini-1.5-pro"
	all_tools = _sanitize_tools(mcp)
	if gemini_settings.enable_google_search:
		all_tools.append(types.Tool(google_search=types.GoogleSearch()))

	# --- 5. System Instruction & Config Setup ---
	system_instruction = gemini_settings.system_instruction or (
		"You are a helpful assistant integrated into ERPNext..."
	)
	generation_config = config or {}
	generation_config.update(
		{
			"tools": all_tools,
			"system_instruction": system_instruction,
		}
	)

	# --- 6. Initialize Chat ---
	# The new SDK creates a chat session from the client.
	chat = client.chats.create(model=model_name, history=conversation_history)
	final_response_text = ""
	max_tool_calls = 10
	current_prompt = prompt

	# --- 7. Main Tool-Calling Loop ---
	for _ in range(max_tool_calls):
		response = chat.send_message(message=current_prompt, config=generation_config)
		function_call = response.candidates[0].content.parts[0].function_call

		if not function_call:
			try:
				final_response_text = response.text
			except ValueError:
				final_response_text = "Model did not provide a text response."
				frappe.log_error("ValueError accessing response.text", "Gemini Response Error")
			break

		tool = mcp._tool_registry.get(function_call.name)
		frappe.log_error(
			f"Gemini Function Call: {function_call.name} with args {function_call.args}", "Gemini Debug"
		)

		if not tool:
			result_content = f"Error: Tool '{function_call.name}' not found."
		else:
			try:
				result_content = tool["fn"](**function_call.args)
			except Exception:
				result_content = "Error: Exception during tool execution."
				frappe.log_error(
					frappe.get_traceback(), f"Gemini Tool Execution Error: {function_call.name}"
				)

		function_response = types.Content(
			parts=[types.Part(function_response={"name": function_call.name, "response": {"content": result_content}})]
		)
		frappe.log_error(f"Gemini Function Response: {function_response}", "Gemini Debug")
		current_prompt = function_response
	else:
		final_response_text = "Exceeded maximum tool calls."

	# --- 8. Save and Return Final Response ---
	full_history = []
	if conversation_id:
		try:
			conv_doc = frappe.get_doc("Gemini Conversation", conversation_id)
			if conv_doc.conversation:
				full_history = json.loads(conv_doc.conversation)
		except (frappe.DoesNotExistError, json.JSONDecodeError):
			pass

	full_history.append({"role": "user", "text": prompt})
	full_history.append({"role": "gemini", "text": final_response_text})

	new_conversation_id = save_conversation(conversation_id, prompt, full_history)

	return {
		"response": final_response_text,
		"conversation_id": new_conversation_id,
		"clarification_needed": False,
	}


def save_conversation(conversation_id, title, conversation):
	"""Saves or updates a conversation in the database.

	Args:
		conversation_id (str or None): The ID of the conversation to update, or None
			to create a new one.
		title (str): The title for a new conversation.
		conversation (list[dict]): The full conversation history to save.

	Returns:
		str: The name of the saved conversation document.
	"""
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
	"""Generates a list of tasks for a project using Gemini.

	Args:
		project_id (str): The ID of the project to generate tasks for.
		template (str): The template to use for task generation.

	Returns:
		dict or list: A list of task objects or an error dictionary.
	"""
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
	"""Analyzes a project for potential risks using Gemini.

	Args:
		project_id (str): The ID of the project to analyze.

	Returns:
		dict or list: A list of risk objects or an error dictionary.
	"""
	if not frappe.db.exists("Project", project_id):
		return {"error": "Project not found."}
	project = frappe.get_doc("Project", project_id)
	prompt = f'Analyze the project for potential risks (e.g., timeline, budget, scope creep).\nProject: {json.dumps(project.as_dict(), default=str)}\n\nReturn ONLY a valid JSON list of objects with keys "risk_name" and "risk_description".'
	response_text = generate_text(prompt)
	try:
		return json.loads(response_text)
	except json.JSONDecodeError:
		return {"error": "Failed to parse a JSON response from the AI."}
