import base64
import functools
import json
import logging
import traceback
from datetime import datetime, timedelta
from io import BytesIO
from email.mime.text import MIMEText
from googleapiclient.http import MediaIoBaseUpload
import base64


import frappe
from frappe.utils import get_url_to_form
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from thefuzz import fuzz, process

from gemini_integration.mcp import mcp
from gemini_integration.utils import get_user_credentials, handle_errors, log_activity


def _get_doctype_fields(doctype_name: str) -> list[str]:
	"""
	Retrieves a list of fields for a given DocType, filtered by user permissions
	and compatibility for AI context.
	"""
	try:
		meta = frappe.get_meta(doctype_name)
		fields_to_fetch = ["name"]  # 'name' is always essential

		# Define field types that are not useful for the AI context
		excluded_field_types = {
			"HTML", "Image", "Attach", "Attach Image", "Code", "JSON",
			"Text Editor", "Password", "Button", "Section Break", "Column Break", "Tab Break"
		}

		for df in meta.fields:
			# Check 1: User has at least read permission for the field
			if not frappe.has_permission(doctype_name, "read", fieldname=df.fieldname):
				continue

			# Check 2: Field is not hidden
			if df.hidden:
				continue

			# Check 3: Field type is not in the exclusion list
			if df.fieldtype in excluded_field_types:
				continue

			# Check 4: Field exists as a database column
			if not frappe.db.has_column(doctype_name, df.fieldname):
				continue

			# Check 5: Field is not already in our list
			if df.fieldname not in fields_to_fetch:
				fields_to_fetch.append(df.fieldname)

		return fields_to_fetch

	except Exception:
		frappe.log_error(
			f"Error dynamically fetching fields for DocType '{doctype_name}'",
			frappe.get_traceback()
		)
		# Fallback to a minimal, safe list of fields that does not depend on the meta object
		return ["name", "modified"]


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
		for field, value in doc_dict.items():
			if value:
				if isinstance(value, list):
					# This is likely a child table. Mention its existence but not its content.
					context += f"- {field}: (Contains a list of {len(value)} items)\n"
				else:
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

get_doc_context.service = "erpnext"

@mcp.tool()
@log_activity
@handle_errors
def search_erpnext_documents(query: str, doctype: str = None, limit: int = 5) -> dict:
	"""Searches for documents in ERPNext with a query, returning a dictionary of results.
	If no doctype is specified, it searches across a default set of DocTypes.

	Args:
	    query (str): The search query.
	    doctype (str, optional): The DocType to search within. Defaults to None.
	    limit (int, optional): The maximum number of documents to return.
	        Defaults to 5.

	Returns:
	    dict: A dictionary containing the search results, structured for programmatic use.
	"""
	try:
		# --- Start: Prioritized Direct Document ID Lookup ---
		# If a query looks like a specific document ID, try to fetch it directly first.
		doctypes_for_direct_check = (
			[doctype]
			if doctype
			else [
				"Project",
				"Customer",
				"Supplier",
				"Item",
				"Sales Order",
				"Purchase Order",
				"Lead",
				"Opportunity",
				"Task",
				"Issue",
				"Quotation",
				"Sales Invoice",
			]
		)

		for dt in doctypes_for_direct_check:
			try:
				if frappe.db.exists(dt, query):
					# If found, retrieve the full document and return it as a confident match.
					doc = frappe.get_doc(dt, query)
					doc_dict = doc.as_dict()
					meta = frappe.get_meta(dt)
					title_field = meta.get_title_field()
					label = (title_field and doc.get(title_field)) or doc.name

					context = f"Found an exact match for '{query}': {label} (ID: {doc.name}, Type: {dt}).\n\nFull details:\n"
					for field, value in doc_dict.items():
						if value:
							if isinstance(value, list):
								context += f"- {field}: (Contains a list of {len(value)} items)\n"
							else:
								context += f"- {field}: {value}\n"
					doc_url = get_url_to_form(dt, doc.name)
					context += f"\nLink: {doc_url}"
					return {"type": "confident_match", "doc": doc_dict, "string_representation": context}
			except Exception:
				# This could fail if the doctype in the default list doesn't exist in the instance.
				# We can safely ignore it and proceed to the broader search.
				pass
		# --- End: Prioritized Direct Document ID Lookup ---

		# If no direct match is found, proceed with the original fuzzy search logic.
		limit = int(limit)

		# If a specific doctype is provided, search only that. Otherwise, search a default list
		# of common doctypes to find the most relevant document.
		default_doctypes = [
			"Project",
			"Customer",
			"Supplier",
			"Item",
			"Sales Order",
			"Purchase Order",
			"Lead",
			"Opportunity",
		]
		doctypes_to_search = [doctype] if doctype else default_doctypes
		all_scored_docs = []

		for dt in doctypes_to_search:
			try:
				meta = frappe.get_meta(dt)
			except frappe.DoesNotExistError:
				# This can happen if a default doctype is not present in the user's instance.
				# We can silently ignore it and continue.
				continue

			fields_to_fetch = _get_doctype_fields(dt)
			title_field = meta.get_title_field()
			search_fields = meta.get_search_fields()

			field_weights = {"name": 3.0}
			if title_field and title_field in fields_to_fetch:
				field_weights[title_field] = 3.0
			for f in search_fields:
				if f not in field_weights and f in fields_to_fetch:
					field_weights[f] = 1.5

			all_docs = frappe.get_all(dt, fields=fields_to_fetch)

			for doc in all_docs:
				total_score = 0
				full_text = " ".join(
					[str(doc.get(f, "")) for f in fields_to_fetch if f not in field_weights]
				)
				total_score += fuzz.token_set_ratio(query, full_text)

				for field, weight in field_weights.items():
					field_value = str(doc.get(field, ""))
					if field_value:
						total_score += fuzz.token_set_ratio(query, field_value) * weight

				feedback_score = frappe.db.sql(
					"""
                    SELECT SUM(CASE WHEN is_helpful = 1 THEN 1 ELSE -1 END)
                    FROM `tabGemini Search Feedback`
                    WHERE doctype_name = %s AND document_name = %s
                """,
					(dt, doc.name),
					as_list=True,
				)
				if feedback_score and feedback_score[0][0]:
					total_score += feedback_score[0][0] * 10

				# Add a threshold to only include reasonably confident matches
				if total_score > 70:
					label = (title_field and doc.get(title_field)) or doc.name
					all_scored_docs.append(
						{"name": doc.name, "doctype": dt, "score": total_score, "label": label}
					)

		# Sort all collected documents by score
		sorted_docs = sorted(all_scored_docs, key=lambda x: x["score"], reverse=True)

		if not sorted_docs:
			search_scope = f"in DocType '{doctype}'" if doctype else "across the system"
			string_repr = f"No documents {search_scope} found matching your query '{query}'."
			return {"type": "no_match", "string_representation": string_repr}

		# If the top match is significantly better than the second, retrieve its full context
		if len(sorted_docs) == 1 or (
			len(sorted_docs) > 1 and sorted_docs[0]["score"] > sorted_docs[1]["score"] * 1.5
		):
			top_doc_info = sorted_docs[0]
			doc = frappe.get_doc(top_doc_info["doctype"], top_doc_info["name"])
			doc_dict = doc.as_dict()
			context = f"Found a confident match for '{query}': {top_doc_info['label']} (ID: {top_doc_info['name']}, Type: {top_doc_info['doctype']}).\n\nFull details:\n"
			for field, value in doc_dict.items():
				if value:
					if isinstance(value, list):
						context += f"- {field}: (Contains a list of {len(value)} items)\n"
					else:
						context += f"- {field}: {value}\n"
			doc_url = get_url_to_form(top_doc_info["doctype"], top_doc_info["name"])
			context += f"\nLink: {doc_url}"
			return {"type": "confident_match", "doc": doc_dict, "string_representation": context}

		# Otherwise, return a list of top results for disambiguation
		results_string = (
			f"Found multiple potential matches for your query '{query}'. Please clarify which one you mean:\n"
		)
		disambiguation_docs = []
		for doc in sorted_docs[:limit]:
			results_string += (
				f"- {doc['label']} (ID: {doc['name']}, Type: {doc['doctype']}, Score: {doc['score']:.2f})\n"
			)
			disambiguation_docs.append(doc)

		return {"type": "disambiguation", "docs": disambiguation_docs, "string_representation": results_string}

	except Exception as e:
		frappe.log_error(
			message=f"Error in search_erpnext_documents: {frappe.get_traceback()}",
			title="Gemini Search Error",
		)
		error_string = "An error occurred while searching for documents. Please check the Error Log for details."
		return {"type": "error", "string_representation": error_string}

search_erpnext_documents.service = "erpnext"


# Note: Google Workspace tools were reviewed for float->int casting issues,
# but none were found to have integer parameters that would be affected.
@mcp.tool()
@log_activity
@handle_errors
def search_gmail(query: str) -> str:
	"""Searches Gmail for a query and returns message subjects and snippets.

	Args:
	    query (str): The search query.

	Returns:
	    str: A formatted string of email context, or an error message.
	"""
	try:
		credentials = get_user_credentials()
		if not credentials:
			return "Could not get user credentials. Please make sure you have authenticated with Google."
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

search_gmail.service = "gmail"

@mcp.tool()
@log_activity
@handle_errors
def search_drive(query: str) -> str:
	"""Searches Google Drive for a query or lists recent files.

	Args:
	    query (str): The search query.

	Returns:
	    str: A formatted string of file context, or an error message.
	"""
	try:
		credentials = get_user_credentials()
		if not credentials:
			return "Could not get user credentials. Please make sure you have authenticated with Google."
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

search_drive.service = "drive"

@mcp.tool()
@log_activity
@handle_errors
def search_calendar(query: str) -> str:
	"""Searches calendar events for the next 7 days.

	Args:
	    query (str): The search query.

	Returns:
	    str: A formatted string of calendar events, or an error message.
	"""
	try:
		credentials = get_user_credentials()
		if not credentials:
			return "Could not get user credentials. Please make sure you have authenticated with Google."
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
					q=query,
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

search_calendar.service = "calendar"

@mcp.tool()
@log_activity
@handle_errors
def get_drive_file_context(file_id: str) -> str:
	"""Fetches a Drive file's metadata and content, supporting Shared Drives.

	Args:
	    file_id (str): The ID of the Google Drive file.

	Returns:
	    str: The formatted context of the file, or an error message.
	"""
	try:
		credentials = get_user_credentials()
		if not credentials:
			return "Could not get user credentials. Please make sure you have authenticated with Google."
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

get_drive_file_context.service = "drive"

@mcp.tool()
@log_activity
@handle_errors
def get_gmail_message_context(message_id: str) -> str:
	"""Fetches a specific Gmail message's headers and body.

	Args:
	    message_id (str): The ID of the Gmail message.

	Returns:
	    str: The formatted context of the email, or an error message.
	"""
	try:
		credentials = get_user_credentials()
		if not credentials:
			return "Could not get user credentials. Please make sure you have authenticated with Google."
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

get_gmail_message_context.service = "gmail"

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

find_best_match_for_doctype.service = "erpnext"

@mcp.tool()
@log_activity
@handle_errors
def search_google_contacts(name: str) -> str:
	"""Searches Google Contacts for a person by name and returns the best match.

	Args:
	    name (str): The name of the person to search for.

	Returns:
	    str: A JSON string containing the best match or a list of suggestions.
	"""
	try:
		credentials = get_user_credentials()
		if not credentials:
			return json.dumps(
				{"error": "Could not get user credentials. Please make sure you have authenticated with Google."}
			)
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
			return json.dumps({"suggestions": []})

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
			return json.dumps({"best_match": sorted_contacts[0]})
		else:
			return json.dumps({"suggestions": sorted_contacts})

	except HttpError as error:
		frappe.log_error(
			f"Google People API Error for query '{name}': {str(error.content)[:100]}", "Gemini Contact Search Error"
		)
		return json.dumps({"error": "An API error occurred during contact search."})

search_google_contacts.service = "google"


@mcp.tool()
@log_activity
@handle_errors
def create_drive_file(file_name: str, file_content: str, folder_id: str = None) -> str:
	"""Creates a new file in Google Drive.

	Args:
	    file_name (str): The name of the file to create.
	    file_content (str): The content of the file.
	    folder_id (str, optional): The ID of the folder to create the file in. Defaults to None.

	Returns:
	    str: A confirmation message with the link to the new file, or an error message.
	"""
	try:
		credentials = get_user_credentials()
		if not credentials:
			return "Could not get user credentials. Please make sure you have authenticated with Google."
		service = build("drive", "v3", credentials=credentials)
		file_metadata = {"name": file_name}
		if folder_id:
			file_metadata["parents"] = [folder_id]

		fh = BytesIO(file_content.encode('utf-8'))
		media = MediaIoBaseUpload(fh, mimetype='text/plain')

		file = service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink").execute()
		return f"File '{file_name}' created successfully. Link: {file.get('webViewLink')}"
	except HttpError as error:
		return f"An error occurred with Google Drive: {error}"

create_drive_file.service = "drive"


@mcp.tool()
@log_activity
@handle_errors
def update_drive_file(file_id: str, file_content: str) -> str:
	"""Updates the content of an existing file in Google Drive.

	Args:
	    file_id (str): The ID of the file to update.
	    file_content (str): The new content of the file.

	Returns:
	    str: A confirmation message or an error message.
	"""
	try:
		credentials = get_user_credentials()
		if not credentials:
			return "Could not get user credentials. Please make sure you have authenticated with Google."
		service = build("drive", "v3", credentials=credentials)
		fh = BytesIO(file_content.encode('utf-8'))
		media = MediaIoBaseUpload(fh, mimetype='text/plain')

		file = service.files().update(fileId=file_id, media_body=media).execute()
		return f"File updated successfully."
	except HttpError as error:
		return f"An error occurred with Google Drive: {error}"

update_drive_file.service = "drive"


@mcp.tool()
@log_activity
@handle_errors
def delete_drive_file(file_id: str, confirm: bool = False) -> str:
	"""Deletes a file from Google Drive.

	Args:
	    file_id (str): The ID of the file to delete.
	    confirm (bool, optional): Confirmation to delete. Defaults to False.

	Returns:
	    str: A confirmation message or an error message.
	"""
	if not confirm:
		return "Please confirm that you want to delete this file by calling this function again with confirm=True."
	try:
		credentials = get_user_credentials()
		if not credentials:
			return "Could not get user credentials. Please make sure you have authenticated with Google."
		service = build("drive", "v3", credentials=credentials)
		service.files().delete(fileId=file_id).execute()
		return "File deleted successfully."
	except HttpError as error:
		return f"An error occurred with Google Drive: {error}"

delete_drive_file.service = "drive"


@mcp.tool()
@log_activity
@handle_errors
def send_gmail_message(to: str, subject: str, body: str) -> str:
	"""Sends an email using Gmail.

	Args:
	    to (str): The recipient's email address.
	    subject (str): The subject of the email.
	    body (str): The body of the email.

	Returns:
	    str: A confirmation message or an error message.
	"""
	try:
		credentials = get_user_credentials()
		if not credentials:
			return "Could not get user credentials. Please make sure you have authenticated with Google."
		service = build("gmail", "v1", credentials=credentials)
		message = MIMEText(body)
		message['to'] = to
		message['subject'] = subject
		raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
		create_message = {'raw': raw_message}
		send_message = (service.users().messages().send(userId="me", body=create_message).execute())
		return f"Email sent successfully with Message ID: {send_message['id']}"
	except HttpError as error:
		return f"An error occurred with Gmail: {error}"

send_gmail_message.service = "gmail"


@mcp.tool()
@log_activity
@handle_errors
def modify_gmail_label(message_id: str, add_labels: list[str] = None, remove_labels: list[str] = None) -> str:
	"""Adds or removes labels from a Gmail message.

	Args:
	    message_id (str): The ID of the message to modify.
	    add_labels (list[str], optional): A list of label IDs to add. Defaults to None.
	    remove_labels (list[str], optional): A list of label IDs to remove. Defaults to None.

	Returns:
	    str: A confirmation message or an error message.
	"""
	try:
		credentials = get_user_credentials()
		if not credentials:
			return "Could not get user credentials. Please make sure you have authenticated with Google."
		service = build("gmail", "v1", credentials=credentials)
		body = {}
		if add_labels:
			body['addLabelIds'] = add_labels
		if remove_labels:
			body['removeLabelIds'] = remove_labels

		if not body:
			return "Please specify labels to add or remove."

		service.users().messages().modify(userId="me", id=message_id, body=body).execute()
		return "Labels modified successfully."
	except HttpError as error:
		return f"An error occurred with Gmail: {error}"

modify_gmail_label.service = "gmail"


@mcp.tool()
@log_activity
@handle_errors
def delete_gmail_message(message_id: str, confirm: bool = False) -> str:
	"""Deletes a Gmail message (moves to trash).

	Args:
	    message_id (str): The ID of the message to delete.
	    confirm (bool, optional): Confirmation to delete. Defaults to False.

	Returns:
	    str: A confirmation message or an error message.
	"""
	if not confirm:
		return "Please confirm that you want to delete this message by calling this function again with confirm=True."
	try:
		credentials = get_user_credentials()
		if not credentials:
			return "Could not get user credentials. Please make sure you have authenticated with Google."
		service = build("gmail", "v1", credentials=credentials)
		service.users().messages().trash(userId="me", id=message_id).execute()
		return "Message moved to trash successfully."
	except HttpError as error:
		return f"An error occurred with Gmail: {error}"

delete_gmail_message.service = "gmail"


@mcp.tool()
@log_activity
@handle_errors
def create_google_calendar_event(summary: str, start_time: str, end_time: str, attendees: list[str] = None) -> str:
	"""Creates a new event in Google Calendar.

	Args:
	    summary (str): The summary/title of the event.
	    start_time (str): The start time of the event in ISO format (e.g., '2024-01-01T10:00:00-07:00').
	    end_time (str): The end time of the event in ISO format.
	    attendees (list[str], optional): A list of attendee email addresses. Defaults to None.

	Returns:
	    str: A confirmation message with a link to the event, or an error message.
	"""
	try:
		credentials = get_user_credentials()
		if not credentials:
			return "Could not get user credentials. Please make sure you have authenticated with Google."
		service = build("calendar", "v3", credentials=credentials)
		event = {
			'summary': summary,
			'start': {
				'dateTime': start_time,
				'timeZone': frappe.db.get_single_value('System Settings', 'time_zone'),
			},
			'end': {
				'dateTime': end_time,
				'timeZone': frappe.db.get_single_value('System Settings', 'time_zone'),
			},
		}
		if attendees:
			event['attendees'] = [{'email': email} for email in attendees]

		created_event = service.events().insert(calendarId='primary', body=event).execute()
		return f"Event created successfully. Link: {created_event.get('htmlLink')}"
	except HttpError as error:
		return f"An error occurred with Google Calendar: {error}"

create_google_calendar_event.service = "calendar"


@mcp.tool()
@log_activity
@handle_errors
def update_google_calendar_event(event_id: str, summary: str = None, start_time: str = None, end_time: str = None, attendees: list[str] = None) -> str:
	"""Updates an existing event in Google Calendar.

	Args:
	    event_id (str): The ID of the event to update.
	    summary (str, optional): The new summary/title of the event. Defaults to None.
	    start_time (str, optional): The new start time of the event in ISO format. Defaults to None.
	    end_time (str, optional): The new end time of the event in ISO format. Defaults to None.
	    attendees (list[str], optional): The new list of attendee email addresses. Defaults to None.

	Returns:
	    str: A confirmation message or an error message.
	"""
	try:
		credentials = get_user_credentials()
		if not credentials:
			return "Could not get user credentials. Please make sure you have authenticated with Google."
		service = build("calendar", "v3", credentials=credentials)

		# Get the existing event to update it
		event = service.events().get(calendarId='primary', eventId=event_id).execute()

		if summary:
			event['summary'] = summary
		if start_time:
			event['start']['dateTime'] = start_time
		if end_time:
			event['end']['dateTime'] = end_time
		if attendees:
			event['attendees'] = [{'email': email} for email in attendees]

		updated_event = service.events().update(calendarId='primary', eventId=event_id, body=event).execute()
		return f"Event updated successfully. Link: {updated_event.get('htmlLink')}"

	except HttpError as error:
		return f"An error occurred with Google Calendar: {error}"

update_google_calendar_event.service = "calendar"


@mcp.tool()
@log_activity
@handle_errors
def delete_google_calendar_event(event_id: str, confirm: bool = False) -> str:
	"""Deletes an event from Google Calendar.

	Args:
	    event_id (str): The ID of the event to delete.
	    confirm (bool, optional): Confirmation to delete. Defaults to False.

	Returns:
	    str: A confirmation message or an error message.
	"""
	if not confirm:
		return "Please confirm that you want to delete this event by calling this function again with confirm=True."
	try:
		credentials = get_user_credentials()
		if not credentials:
			return "Could not get user credentials. Please make sure you have authenticated with Google."
		service = build("calendar", "v3", credentials=credentials)
		service.events().delete(calendarId='primary', eventId=event_id).execute()
		return "Event deleted successfully."
	except HttpError as error:
		return f"An error occurred with Google Calendar: {error}"

delete_google_calendar_event.service = "calendar"
