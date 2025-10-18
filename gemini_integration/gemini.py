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
from thefuzz import fuzz, process

from gemini_integration.utils import (
	find_best_match_for_doctype,
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


# --- DYNAMIC DOCTYPE REFERENCING (@DOC-NAME) ---


@log_activity
@handle_errors
def get_dynamic_doctype_map():
	"""Builds and caches a map of naming series prefixes to DocTypes.

	This is used to quickly identify the DocType of a referenced document ID.
	It combines dynamically found prefixes with a hardcoded list for common cases.

	Returns:
	    dict: A dictionary mapping prefixes to DocType names (e.g., {"PRJ": "Project"}).
	"""
	cache_key = "gemini_doctype_prefix_map"
	doctype_map = frappe.cache().get_value(cache_key)
	if doctype_map:
		return doctype_map

	doctype_map = {}
	all_doctypes = frappe.get_all("DocType", fields=["name", "autoname"])

	# Dynamically build the map from DocType autoname properties
	for doc in all_doctypes:
		autoname = doc.get("autoname")
		if not autoname or not isinstance(autoname, str):
			continue

		match = re.match(r"^([A-Z_]+)[\-./]", autoname, re.IGNORECASE)
		if match:
			prefix = match.group(1).upper()
			doctype_map[prefix] = doc.name

	# Add a hardcoded map as a fallback for common or non-standard naming series.
	# The dynamic map takes precedence.
	hardcoded_map = {
		"PRJ": "Project",
		"PROJ": "Project",
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

	frappe.cache().set_value(cache_key, doctype_map, expires_in_sec=3600)  # Cache for 1 hour
	return doctype_map


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


@log_activity
@handle_errors
def search_google_drive(credentials, query):
	"""Searches Google Drive for a query and returns a list of files.

	Args:
	    credentials (google.oauth2.credentials.Credentials): The user's credentials.
	    query (str): The search query.

	Returns:
	    list: A list of file objects, or an error message.
	"""
	try:
		service = build("drive", "v3", credentials=credentials)

		if query.strip():
			search_params = {"q": f"fullText contains '{query}'"}
		else:
			search_params = {"orderBy": "modifiedTime desc"}

		results = (
			service.files()
			.list(
				pageSize=10,
				fields="nextPageToken, files(id, name, webViewLink)",
				corpora="allDrives",
				includeItemsFromAllDrives=True,
				supportsAllDrives=True,
				**search_params,
			)
			.execute()
		)
		items = results.get("files", [])

		return items
	except HttpError as error:
		return f"An error occurred with Google Drive: {error}"


@log_activity
@handle_errors
def search_google_mail(credentials, query):
	"""Searches Gmail for a query and returns a list of emails.

	Args:
	    credentials (google.oauth2.credentials.Credentials): The user's credentials.
	    query (str): The search query.

	Returns:
	    list: A list of email objects, or an error message.
	"""
	try:
		service = build("gmail", "v1", credentials=credentials)

		if query.strip():
			search_query = f'"{query}" in:anywhere'
		else:
			search_query = "in:inbox"

		results = service.users().messages().list(userId="me", q=search_query, maxResults=10).execute()
		messages = results.get("messages", [])

		email_data = []
		if not messages:
			return []

		batch = service.new_batch_http_request()

		def create_callback(msg_id):
			def callback(request_id, response, exception):
				if not exception:
					email_data.append(response)

			return callback

		for msg in messages:
			msg_id = msg["id"]
			batch.add(
				service.users()
				.messages()
				.get(userId="me", id=msg_id, format="metadata", metadataHeaders=["Subject", "From", "Date"]),
				callback=create_callback(msg_id),
			)

		batch.execute()

		return email_data
	except HttpError as error:
		return f"An API error occurred during Gmail search: {error}"


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
	"""Handles chat interactions by assembling context from ERPNext and Google Workspace.

	Args:
	    prompt (str): The user's chat prompt.
	    model (str, optional): The model to use for the chat. Defaults to None.
	    conversation_id (str, optional): The ID of the existing conversation.
	        Defaults to None.

	Returns:
	    dict: A dictionary containing the response, thoughts, and conversation ID.
	"""

	conversation_history = []
	if conversation_id:
		try:
			conversation_doc = frappe.get_doc("Gemini Conversation", conversation_id)
			if conversation_doc.conversation:
				conversation_history = json.loads(conversation_doc.conversation)
		except frappe.DoesNotExistError:
			# Conversation not found, will create a new one
			pass

	# 1. Find all ERPNext document references starting with '@'
	references = re.findall(r'@([a-zA-Z0-9\s-]+)(?![\.\w])|@"([^"]+)"', prompt)
	doc_names = [item for tpl in references for item in tpl if item]
	thoughts = ""

	# 1a. Check for contact search intent if no specific @doc is mentioned.
	if not doc_names:
		# Regex to find patterns like "email from [Name]" or "find [Name]"
		contact_search_match = re.search(
			r"\b(email|mail|message|from|find|search for)\b\s+([A-Z][a-zA-Z\s]+)", prompt, re.IGNORECASE
		)
		if contact_search_match:
			person_name = contact_search_match.group(2).strip()

			creds = get_user_credentials()
			if creds:
				contact_result = search_google_contacts(creds, person_name)

				if contact_result.get("best_match"):
					contact = contact_result["best_match"]
					prompt = prompt.replace(person_name, contact["email"])
					thoughts += f"Contact search found '{contact['name']}' ({contact['email']}) for '{person_name}'.\n"

				elif contact_result.get("suggestions"):
					suggestions = contact_result["suggestions"]
					# Rename 'photo_url' to 'url' for consistency with doc suggestions
					for sugg in suggestions:
						sugg["url"] = sugg.pop("photo_url", None)
					return {
						"response": f"I found a few people named '{person_name}'. Which one did you mean?",
						"suggestions": suggestions,
						"thoughts": f"Contact search for '{person_name}' yielded {len(suggestions)} potential matches.",
						"conversation_id": conversation_id,
					}

				elif contact_result.get("error"):
					return {
						"response": f"Sorry, I encountered an error while searching for '{person_name}' in your contacts.",
						"thoughts": f"Contact search for '{person_name}' failed with an error.",
						"conversation_id": conversation_id,
					}

	# 2. If no '@' references are found, check for potential IDs the user forgot to mark.
	if not doc_names:
		doctype_map = get_dynamic_doctype_map()
		prefixes = list(doctype_map.keys())
		if prefixes:
			# Regex to find patterns like 'PRJ-00123' based on known prefixes.
			pattern = r"\b(" + "|".join(re.escape(p) for p in prefixes) + r")-[\w\d-]+"
			potential_ids = re.findall(pattern, prompt, re.IGNORECASE)
			if potential_ids:
				suggestions = [f"@{pid}" for pid in potential_ids]
				suggestion_str = ", ".join(suggestions)
				return (
					f"To ensure I pull the correct data from ERPNext, please use the '@' symbol before any document ID. "
					f"For example, try asking: 'What is the current status of {suggestion_str}?'"
				)

	# 2a. Check for counting/listing/searching queries
	search_query_match = re.search(
		r"\b(how many|count|list|show me all|find|search for)\b", prompt, re.IGNORECASE
	)
	if search_query_match and not doc_names:
		try:
			# More robust extraction of doctype and query
			doctype_match = re.search(
				r"\b(in|of|from|for)\s+([a-zA-Z\s]+)(?:\s+with|\s+where|\s+that are|\s+which are|\s+about|\s+related to|$)",
				prompt,
				re.IGNORECASE,
			)
			if not doctype_match:
				# Fallback for simple "list Sales Invoices"
				doctype_match = re.search(r"list\s+([a-zA-Z\s]+)", prompt, re.IGNORECASE)

			if doctype_match:
				doctype_str = doctype_match.group(2).strip()
				# Find the best matching doctype name
				doctype = find_best_match_for_doctype(doctype_str)
				if not doctype:
					return {
						"response": f"Sorry, I couldn't find a DocType called '{doctype_str}'. Please check the name and try again."
					}

				# Extract the query part more effectively
				query = prompt[doctype_match.end() :].strip()
				# Remove common joining phrases
				query = re.sub(
					pattern=r"^(with|where|that are|which are|about|related to)\s+",
					repl="",
					string=query,
					flags=re.IGNORECASE,
				)

				documents = search_erpnext_documents(doctype, query)

				# If the top result has a very high score, use it directly.
				if documents and documents[0]["score"] > 250:
					full_context = get_doc_context(documents[0]["doctype"], documents[0]["name"])
				# Otherwise, ask the user for confirmation.
				elif documents:
					suggestions_with_urls = []
					for doc in documents:
						doc["url"] = get_url_to_form(doc["doctype"], doc["name"])
						suggestions_with_urls.append(doc)
					return {
						"response": "I found a few documents that might be what you're looking for. Please select the correct one:",
						"suggestions": suggestions_with_urls,
						"thoughts": f"Search for '{query}' in '{doctype}' yielded {len(documents)} potential matches.",
						"conversation_id": conversation_id,
					}
				else:
					return {
						"response": f"I couldn't find any documents in '{doctype}' that matched your search for '{query}'.",
						"thoughts": f"Search for '{query}' in '{doctype}' yielded no results.",
						"conversation_id": conversation_id,
					}
			else:
				# This part is left as is if no doctype is found in the query.
				pass

		except Exception as e:
			frappe.log_error(f"Error parsing ERPNext search query: {e!s}")

	# 3. Gather context from all found ERPNext references.
	full_context = ""
	if doc_names:
		doctype_map = get_dynamic_doctype_map()
		all_doctype_names = [d.name for d in frappe.get_all("DocType")]

		for doc_name in doc_names:
			doc_name = doc_name.strip()
			found_doctype = None

			# This logic remains largely the same
			if "-" in doc_name:
				prefix = doc_name.split("-")[0].upper()
				mapped_doctype = doctype_map.get(prefix)
				if mapped_doctype and frappe.db.exists(mapped_doctype, doc_name):
					found_doctype = mapped_doctype

			if not found_doctype:
				best_match_doctype = find_best_match_for_doctype(doc_name)
				if best_match_doctype and frappe.db.exists(best_match_doctype, doc_name):
					found_doctype = best_match_doctype

			if not found_doctype:
				for dt in all_doctype_names:
					if frappe.db.exists(dt, doc_name):
						found_doctype = dt
						break

			if found_doctype:
				full_context += get_doc_context(found_doctype, doc_name) + "\n\n"
			else:
				# If not found, trigger the enhanced search to find suggestions
				all_doctypes = [d.name for d in frappe.get_all("DocType")]
				possible_matches = []
				for dt in all_doctypes:
					possible_matches.extend(search_erpnext_documents(dt, doc_name))

				if possible_matches:
					# Sort all found matches from all doctypes
					sorted_matches = sorted(possible_matches, key=lambda x: x["score"], reverse=True)
					suggestions_with_urls = []
					for doc in sorted_matches[:5]:
						doc["url"] = get_url_to_form(doc["doctype"], doc["name"])
						suggestions_with_urls.append(doc)
					return {
						"response": f"I couldn't find a document with the exact name '{doc_name}'. Did you mean one of these?",
						"suggestions": suggestions_with_urls,
						"thoughts": f"Direct lookup for '{doc_name}' failed. Fuzzy search across all DocTypes found {len(sorted_matches)} potential matches.",
						"conversation_id": conversation_id,
					}
				else:
					full_context += f"(System: Document '{doc_name}' could not be found.)\n\n"

	# 4. Gather context from Google Workspace and ERPNext files.
	google_context = ""
	uploaded_files = []
	creds = None
	if is_google_integrated():
		creds = get_user_credentials()

	if creds:
		# 4a. Look for direct references like @gdrive/file_id or @file/file_url
		gdrive_refs = re.findall(r"@gdrive/([\w-]+)", prompt)
		erpnext_file_refs = re.findall(r"@file/([\w\d\/\.-]+)", prompt)

		for file_id in gdrive_refs:
			# Get the file reference from the cache
			uploaded_file = frappe.cache().get_value(f"gemini_file_{file_id}")
			if uploaded_file:
				uploaded_files.append(uploaded_file)
				google_context += f"(System: Using uploaded Google Drive file '{file_id}' for analysis.)\n"
			else:
				file_content = get_drive_file_context(creds, file_id)
				if file_content:
					uploaded_file = upload_file_to_gemini(file_id, file_content)
					if uploaded_file:
						uploaded_files.append(uploaded_file)
						google_context += f"(System: Uploaded Google Drive file '{file_id}' for analysis.)\n"

		for file_url in erpnext_file_refs:
			file_content = get_erpnext_file_content(file_url)
			if file_content:
				uploaded_file = upload_file_to_gemini(file_url, file_content)
				if uploaded_file:
					uploaded_files.append(uploaded_file)
					google_context += f"(System: Uploaded ERPNext file '{file_url}' for analysis.)\n"

		# 4b. Perform keyword-based or general searches for any text not part of a direct reference.
		search_prompt = re.sub(r"@gdrive/[\w-]+", "", prompt).strip()
		search_prompt = re.sub(r"@file/[\w\d\/\.-]+", "", search_prompt).strip()
		search_prompt = re.sub(r"@gmail/[\w-]+", "", search_prompt).strip()

		gmail_triggered = re.search(r"\b(email|mail|gmail)\b", search_prompt.lower())
		drive_triggered = re.search(r"\b(drive|file|doc|document|sheet|slide)\b", search_prompt.lower())
		calendar_triggered = re.search(r"\b(calendar|event|meeting)\b", search_prompt.lower())

		if gmail_triggered:
			google_context += search_gmail(creds, search_prompt)

		if drive_triggered:
			google_context += search_drive(creds, search_prompt)

		if calendar_triggered:
			google_context += search_calendar(creds, search_prompt)

		# 4c. If no specific keywords or direct links were used, perform a general search.
		if not any([gmail_triggered, drive_triggered, calendar_triggered, gdrive_refs, erpnext_file_refs]):
			google_context += search_gmail(creds, search_prompt)
			google_context += "\n"
			google_context += search_drive(creds, search_prompt)

	# Assemble thoughts for the UI
	if "full_context" in locals() and full_context:
		thoughts += f"--- ERPNext Data Context ---\n{full_context}\n"

	if google_context:
		thoughts += f"--- Google Workspace Data Context ---\n{google_context}\n"

	# 5. Clean the prompt of all reference syntax before sending it to the AI.
	clean_prompt = re.sub(r'@([a-zA-Z0-9\s-]+)(?![\.\w])|@"([^"]+)"', "", prompt)
	clean_prompt = re.sub(r"@gdrive/[\w-]+", "", clean_prompt).strip()
	clean_prompt = re.sub(r"@file/[\w\d\/\.-]+", "", clean_prompt).strip()
	clean_prompt = re.sub(r"@gmail/[\w-]+", "", clean_prompt).strip()

	# 6. Assemble the final prompt with all context.
	system_instruction = frappe.db.get_single_value("Gemini Settings", "system_instruction")
	if not system_instruction:
		system_instruction = ""
	system_instruction += "\nDo not mention permission issues unless you are certain that a permission error is the cause of the problem."

	final_prompt = []
	if system_instruction:
		final_prompt.append(f"System Instruction: {system_instruction}")

	if thoughts:
		final_prompt.append(thoughts)

	# Add conversation history to the prompt
	if conversation_history:
		for entry in conversation_history:
			final_prompt.append(f"{entry['role']}: {entry['text']}")

	final_prompt.append(f"User query: {clean_prompt}")
	final_prompt.append(
		"\nBased on the user query and any provided context, please provide a helpful and comprehensive response."
	)

	if uploaded_files:
		final_prompt.extend(uploaded_files)

	response_text = generate_text(final_prompt, model, uploaded_files)

	# Save the conversation
	conversation_history.append({"role": "user", "text": prompt})
	conversation_history.append({"role": "gemini", "text": response_text})
	conversation_id = save_conversation(conversation_id, prompt, conversation_history)

	return {
		"response": response_text,
		"thoughts": thoughts.strip() if thoughts else "",
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
