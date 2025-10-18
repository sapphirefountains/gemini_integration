import base64
import functools
import logging
import traceback
from datetime import datetime, timedelta

import frappe
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from thefuzz import fuzz, process

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
	"""Fetches and formats a document's data for context.

	Args:
	    doctype (str): The type of the document to fetch.
	    docname (str): The name of the document to fetch.

	Returns:
	    str: A formatted string containing the document's context or an error message.
	"""
	try:
		doc = frappe.get_doc(doctype, docname)
		doc_dict = doc.as_dict()
		context = f"Context for {doctype} '{docname}':\n"
		# Loop through the document dictionary and format the data for readability.
		# Child tables (lists) are excluded for brevity.
		for field, value in doc_dict.items():
			if value and not isinstance(value, list):
				context += f"- {field}: {value}\n"

		doc_url = get_url_to_form(doctype, docname)
		context += f"\nLink: {doc_url}"
		return context
	except frappe.DoesNotExistError:
		# If the document is not found, try to find the best match using fuzzy search
		all_docs = frappe.get_all(doctype, fields=["name"])
		all_doc_names = [d["name"] for d in all_docs]

		best_match = process.extractOne(docname, all_doc_names)
		if best_match and best_match[1] > 80:  # 80 is a good threshold for confidence
			return f"(System: Document '{docname}' of type '{doctype}' not found. Did you mean '{best_match[0]}'?)\n"
		else:
			return f"(System: Document '{docname}' of type '{doctype}' not found.)\n"
	except Exception as e:
		frappe.log_error(f"Error fetching doc context: {e!s}")
		return f"(System: Could not retrieve context for {doctype} {docname}.)\n"


@mcp.tool()
@log_activity
@handle_errors
def search_erpnext_documents(doctype: str, query: str, limit: int = 5) -> list:
	"""Searches for documents in ERPNext with a query, returning a scored and ranked list.

	Args:
	    doctype (str): The DocType to search within.
	    query (str): The search query.
	    limit (int, optional): The maximum number of documents to return.
	        Defaults to 5.

	Returns:
	    list: A list of scored and ranked documents.
	"""
	try:
		meta = frappe.get_meta(doctype)

		# Define weights for different field types
		title_field = meta.get_title_field()
		search_fields = meta.get_search_fields()

		field_weights = {
			"name": 3.0,
		}
		if title_field:
			field_weights[title_field] = 3.0

		for f in search_fields:
			if f not in field_weights:
				field_weights[f] = 1.5

		# Get all text-like fields
		fields_to_fetch = list(field_weights.keys())
		for df in meta.fields:
			if (
				df.fieldtype in ["Data", "Text", "Small Text", "Long Text", "Text Editor", "Select"]
				and df.fieldname not in fields_to_fetch
			):
				fields_to_fetch.append(df.fieldname)

		all_docs = frappe.get_all(doctype, fields=fields_to_fetch)

		scored_docs = []
		for doc in all_docs:
			total_score = 0

			# Use token_set_ratio for better matching of unordered words
			full_text = " ".join([str(doc.get(f, "")) for f in fields_to_fetch if f not in field_weights])
			total_score += fuzz.token_set_ratio(query, full_text)

			# Apply weighted scores for important fields
			for field, weight in field_weights.items():
				field_value = str(doc.get(field, ""))
				if field_value:
					total_score += fuzz.token_set_ratio(query, field_value) * weight

			# Factor in user feedback for "learning"
			feedback_score = frappe.db.sql(
				"""
                SELECT SUM(CASE WHEN is_helpful = 1 THEN 1 ELSE -1 END)
                FROM `tabGemini Search Feedback`
                WHERE doctype_name = %s AND document_name = %s
            """,
				(doctype, doc.name),
				as_list=True,
			)

			if feedback_score and feedback_score[0][0]:
				total_score += feedback_score[0][0] * 10  # Add a significant bonus/penalty

			if total_score > 0:
				label = (title_field and doc.get(title_field)) or doc.name
				scored_docs.append(
					{"name": doc.name, "doctype": doctype, "score": total_score, "label": label}
				)

		# Sort by score descending
		sorted_docs = sorted(scored_docs, key=lambda x: x["score"], reverse=True)

		return sorted_docs[:limit]

	except Exception as e:
		frappe.log_error(f"Error searching ERPNext documents: {e!s}")
		return []


from google.oauth2.credentials import Credentials

@mcp.tool()
@log_activity
@handle_errors
def search_gmail(credentials: Credentials, query: str) -> str:
	"""Searches Gmail for a query and returns message subjects and snippets.

	Args:
	    credentials (google.oauth2.credentials.Credentials): The user's credentials.
	    query (str): The search query.

	Returns:
	    str: A formatted string of email context, or an error message.
	"""
	try:
		service = build("gmail", "v1", credentials=credentials)

		if query.strip():
			search_query = f'"{query}" in:anywhere'
		else:
			search_query = "in:inbox"

		results = service.users().messages().list(userId="me", q=search_query, maxResults=5).execute()
		messages = results.get("messages", [])

		email_context = "Recent emails matching your query:\n"
		if not messages:
			return "No recent emails found matching your query."

		batch = service.new_batch_http_request()
		email_data = {}

		def create_callback(msg_id):
			def callback(request_id, response, exception):
				if exception:
					frappe.log_error(
						f"Gmail batch callback error for msg {msg_id}: {exception}", "Gemini Gmail Error"
					)
				else:
					email_data[msg_id] = response

			return callback

		for msg in messages:
			msg_id = msg["id"]
			batch.add(
				service.users()
				.messages()
				.get(userId="me", id=msg_id, format="metadata", metadataHeaders=["Subject"]),
				callback=create_callback(msg_id),
			)

		batch.execute()

		for msg in messages:
			msg_id = msg["id"]
			msg_data = email_data.get(msg_id)
			if msg_data:
				subject = next(
					(h["value"] for h in msg_data["payload"]["headers"] if h["name"] == "Subject"),
					"No Subject",
				)
				snippet = msg_data.get("snippet", "")
				email_context += f"- Subject: {subject}\n  Snippet: {snippet}\n"

		return email_context
	except HttpError as error:
		frappe.log_error(
			message=f"Google Gmail API Error for query '{query}': {error.content}", title="Gemini Gmail Error"
		)
		return "An API error occurred during Gmail search. Please check the Error Log for details.\n"


@mcp.tool()
@log_activity
@handle_errors
def search_drive(credentials: Credentials, query: str) -> str:
	"""Searches Google Drive for a query or lists recent files.

	Args:
	    credentials (google.oauth2.credentials.Credentials): The user's credentials.
	    query (str): The search query.

	Returns:
	    str: A formatted string of file context, or an error message.
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
				pageSize=5,
				fields="nextPageToken, files(id, name, webViewLink)",
				corpora="allDrives",
				includeItemsFromAllDrives=True,
				supportsAllDrives=True,
				**search_params,
			)
			.execute()
		)
		items = results.get("files", [])

		if not items:
			return "No files found in Google Drive matching your query."

		drive_context = "Recent files from Google Drive matching your query:\n"
		for item in items:
			drive_context += f"- Name: {item['name']}, Link: {item['webViewLink']}\n"
		return drive_context
	except HttpError as error:
		return f"An error occurred with Google Drive: {error}"


@mcp.tool()
@log_activity
@handle_errors
def search_calendar(credentials: Credentials, query: str) -> str:
	"""Lists upcoming calendar events for the next 7 days.

	Args:
	    credentials (google.oauth2.credentials.Credentials): The user's credentials.
	    query (str): The search query (currently unused).

	Returns:
	    str: A formatted string of calendar events, or an error message.
	"""
	try:
		service = build("calendar", "v3", credentials=credentials)
		now = datetime.utcnow()
		time_min = now.isoformat() + "Z"
		time_max = (now + timedelta(days=7)).isoformat() + "Z"

		calendar_list = service.calendarList().list().execute()
		all_events = []

		for calendar_list_entry in calendar_list.get("items", []):
			calendar_id = calendar_list_entry["id"]
			events_result = (
				service.events()
				.list(
					calendarId=calendar_id,
					timeMin=time_min,
					timeMax=time_max,
					maxResults=10,
					singleEvents=True,
					orderBy="startTime",
				)
				.execute()
			)

			for event in events_result.get("items", []):
				event["calendar_name"] = calendar_list_entry.get("summary", calendar_id)
				all_events.append(event)

		if not all_events:
			return "No upcoming calendar events found in the next 7 days."

		sorted_events = sorted(all_events, key=lambda x: x["start"].get("dateTime", x["start"].get("date")))

		calendar_context = "Upcoming calendar events in the next 7 days:\n"
		for event in sorted_events:
			start = event["start"].get("dateTime", event["start"].get("date"))
			summary = event.get("summary", "Untitled Event")
			calendar_name = event["calendar_name"]
			calendar_context += f"- {summary} at {start} (from Calendar: {calendar_name})\n"
		return calendar_context
	except HttpError as error:
		return f"An error occurred with Google Calendar: {error}"


@mcp.tool()
@log_activity
@handle_errors
def get_drive_file_context(credentials: Credentials, file_id: str) -> str:
	"""Fetches a Drive file's metadata and content, supporting Shared Drives.

	Args:
	    credentials (google.oauth2.credentials.Credentials): The user's credentials.
	    file_id (str): The ID of the Google Drive file.

	Returns:
	    str: The formatted context of the file, or an error message.
	"""
	try:
		service = build("drive", "v3", credentials=credentials)
		file_meta = (
			service.files()
			.get(
				fileId=file_id,
				fields="id, name, webViewLink, modifiedTime, owners, mimeType",
				supportsAllDrives=True,
			)
			.execute()
		)

		context = f"Context for Google Drive File: {file_meta.get('name', 'Untitled')}\n"
		context += f"- Link: {file_meta.get('webViewLink', 'Link not available')}\n"

		mime_type = file_meta.get("mimeType", "")
		content = ""

		if "google-apps.document" in mime_type:
			content_bytes = service.files().export_media(fileId=file_id, mimeType="text/plain").execute()
			content = content_bytes.decode("utf-8")
		elif mime_type == "text/plain":
			content_bytes = service.files().get_media(fileId=file_id, supportsAllDrives=True).execute()
			content = content_bytes.decode("utf-8")
		else:
			content = "(Content preview is not available for this file type.)"

		# Truncate content to avoid excessive length
		context += f"Content Snippet:\n{content[:3000]}"
		return context
	except HttpError as error:
		frappe.log_error(
			message=f"Google Drive API Error for fileId {file_id}: {error.content}",
			title="Gemini Google Drive Error",
		)
		if error.resp.status == 404:
			return f"(System: A 404 Not Found error occurred for Google Drive file {file_id}. This means the file does not exist or you do not have permission to access it. Please double-check the file ID and your permissions in Google Drive. More details may be in the Error Log.)\n"
		return f"An API error occurred while fetching Google Drive file {file_id}. Please check the Error Log for details.\n"
	except Exception as e:
		frappe.log_error(f"Error fetching drive file context for {file_id}: {e!s}")
		return f"(System: Could not retrieve context for Google Drive file {file_id}.)\n"


@mcp.tool()
@log_activity
@handle_errors
def get_gmail_message_context(credentials: Credentials, message_id: str) -> str:
	"""Fetches a specific Gmail message's headers and body.

	Args:
	    credentials (google.oauth2.credentials.Credentials): The user's credentials.
	    message_id (str): The ID of the Gmail message.

	Returns:
	    str: The formatted context of the email, or an error message.
	"""
	try:
		service = build("gmail", "v1", credentials=credentials)
		msg_data = service.users().messages().get(userId="me", id=message_id, format="full").execute()

		headers = {h["name"]: h["value"] for h in msg_data["payload"]["headers"]}
		link = f"https://mail.google.com/mail/#all/{msg_data['threadId']}"

		content = "(Could not extract email body.)"
		payload = msg_data.get("payload", {})
		if "parts" in payload:
			for part in payload["parts"]:
				if part["mimeType"] == "text/plain":
					data = part["body"].get("data")
					if data:
						content = base64.urlsafe_b64decode(data).decode("utf-8")
					break
		else:
			data = payload.get("body", {}).get("data")
			if data:
				content = base64.urlsafe_b64decode(data).decode("utf-8")

		context = "Context for Gmail Message:\n"
		context += f"- Subject: {headers.get('Subject', 'No Subject')}\n"
		context += f"- From: {headers.get('From', 'N/A')}\n"
		context += f"- Link: {link}\n"
		context += f"Body Snippet:\n{content[:3000]}"
		return context
	except HttpError as error:
		return f"An error occurred while fetching Gmail message {message_id}: {error}\n"
	except Exception as e:
		frappe.log_error(f"Error fetching gmail context for {message_id}: {e!s}")
		return f"(System: Could not retrieve context for Gmail message {message_id}.)\n"


@mcp.tool()
@log_activity
@handle_errors
def find_best_match_for_doctype(doctype_name: str) -> str:
	"""Finds the best match for a DocType name using fuzzy search.

	Args:
	    doctype_name (str): The name of the DocType to search for.

	Returns:
	    str: The best matching DocType name, or None if no good match is found.
	"""
	all_doctypes = frappe.get_all("DocType", fields=["name"])
	all_doctype_names = [d["name"] for d in all_doctypes]

	best_match = process.extractOne(doctype_name, all_doctype_names)
	if best_match and best_match[1] > 80:  # Confidence threshold
		return best_match[0]
	return None


@mcp.tool()
@log_activity
@handle_errors
def search_google_contacts(credentials: Credentials, name: str) -> dict:
	"""Searches Google Contacts for a person by name and returns the best match.

	Args:
	    credentials (google.oauth2.credentials.Credentials): The user's credentials.
	    name (str): The name of the person to search for.

	Returns:
	    dict: A dictionary containing the best match or a list of suggestions.
	"""
	try:
		people_service = build("people", "v1", credentials=credentials)
		gmail_service = build("gmail", "v1", credentials=credentials)

		# Search for the contact
		results = (
			people_service.people()
			.searchContacts(query=name, pageSize=5, readMask="names,emailAddresses,photos")
			.execute()
		)

		people = results.get("results", [])
		if not people:
			return {"suggestions": []}

		scored_contacts = []
		for person_result in people:
			person = person_result.get("person", {})
			display_name = person.get("names", [{}])[0].get("displayName", "N/A")
			email = person.get("emailAddresses", [{}])[0].get("value")
			photo_url = person.get("photos", [{}])[0].get("url")

			if not email:
				continue

			# Calculate a confidence score
			score = fuzz.token_set_ratio(name, display_name) / 100.0

			# Check for recent emails to boost score
			try:
				recent_emails = (
					gmail_service.users()
					.messages()
					.list(userId="me", q=f"from:{email} or to:{email}", maxResults=5)
					.execute()
					.get("messages", [])
				)
				if recent_emails:
					score *= 1.2  # Boost score by 20% for recent communication
			except HttpError:
				pass  # Ignore errors if we can't search gmail

			# Ensure score doesn't exceed 1.0
			score = min(score, 1.0)

			scored_contacts.append(
				{"name": display_name, "email": email, "photo_url": photo_url, "score": score}
			)

		# Sort by score descending
		sorted_contacts = sorted(scored_contacts, key=lambda x: x["score"], reverse=True)

		threshold = frappe.db.get_single_value("Gemini Settings", "contact_confidence_threshold") or 0.95

		if sorted_contacts and sorted_contacts[0]["score"] >= threshold:
			return {"best_match": sorted_contacts[0]}
		else:
			return {"suggestions": sorted_contacts}

	except HttpError as error:
		frappe.log_error(
			f"Google People API Error for query '{name}': {str(error.content)[:100]}", "Gemini Contact Search Error"
		)
		return {"error": "An API error occurred during contact search."}
