import ast
import base64
import functools
import json
import logging
import re
import traceback
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from io import BytesIO

import frappe
import numpy as np
from frappe.utils import get_url_to_form
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload
from thefuzz import fuzz, process

from gemini_integration.mcp import mcp
from gemini_integration.utils import generate_embedding, get_user_credentials, handle_errors, log_activity


def cosine_similarity(v1, v2):
	"""Calculates the cosine similarity between two vectors."""
	return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))


def find_similar_documents(query_embedding, doctype=None, limit=5):
	"""Finds similar documents using vector similarity search on document chunks."""
	filters = {}
	if doctype:
		filters["ref_doctype"] = doctype

	all_embeddings = frappe.get_all(
		"Gemini Embedding",
		fields=["ref_doctype", "ref_docname", "embedding", "content"],
		filters=filters,
	)

	if not all_embeddings:
		return []

	# Calculate scores for all chunks
	all_matching_chunks = []
	for emb_info in all_embeddings:
		# Skip if embedding is missing or invalid
		if not emb_info.get("embedding") or not isinstance(emb_info["embedding"], str):
			continue
		try:
			stored_embedding = np.array(json.loads(emb_info["embedding"]))
		except (json.JSONDecodeError, TypeError):
			continue

		score = cosine_similarity(query_embedding, stored_embedding)
		if score > 0.75:  # Similarity threshold
			all_matching_chunks.append(
				{
					"doctype": emb_info["ref_doctype"],
					"name": emb_info["ref_docname"],
					"score": score,
					"content": emb_info.get("content", ""),
				}
			)

	if not all_matching_chunks:
		return []

	# Group chunks by document and find the best chunk for each document
	best_chunks_per_doc = {}
	for chunk in all_matching_chunks:
		doc_key = (chunk["doctype"], chunk["name"])
		if doc_key not in best_chunks_per_doc or chunk["score"] > best_chunks_per_doc[doc_key]["score"]:
			best_chunks_per_doc[doc_key] = chunk

	# Convert the dictionary of best chunks back to a list
	scored_docs = list(best_chunks_per_doc.values())

	return sorted(scored_docs, key=lambda x: x["score"], reverse=True)[:limit]


def _get_doctype_fields(doctype_name: str) -> list[str]:
	"""
	Retrieves a list of fields for a given DocType, filtered by user permissions
	and compatibility for AI context.
	"""
	try:
		# Get the maximum permission level the current user has for reading this doctype.
		user_roles = frappe.get_roles()
		# System Manager can read all fields, so we can skip the query for them.
		if "System Manager" in user_roles:
			max_read_permlevel = 999
		else:
			max_read_permlevel_res = frappe.db.sql(
				"""
				SELECT MAX(permlevel)
				FROM `tabDocPerm`
				WHERE `role` IN %(roles)s
				AND `parent` = %(doctype)s
				AND `read` = 1
			""",
				{"roles": user_roles, "doctype": doctype_name},
			)
			max_read_permlevel = (
				max_read_permlevel_res[0][0]
				if max_read_permlevel_res and max_read_permlevel_res[0][0] is not None
				else -1
			)

		meta = frappe.get_meta(doctype_name)
		fields_to_fetch = ["name"]  # 'name' is always essential

		# Define field types that are not useful for the AI context
		excluded_field_types = {
			"HTML",
			"Image",
			"Attach",
			"Attach Image",
			"Code",
			"JSON",
			"Text Editor",
			"Password",
			"Button",
			"Section Break",
			"Column Break",
			"Tab Break",
		}

		for df in meta.fields:
			# Check 1: User's max permlevel must be >= the field's permlevel.
			if df.permlevel > max_read_permlevel:
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
			f"Error dynamically fetching fields for DocType '{doctype_name}'", frappe.get_traceback()
		)
		# Fallback to a minimal, safe list of fields that does not depend on the meta object
		return ["name", "modified"]


@mcp.tool()
@log_activity
@handle_errors
def fetch_erpnext_data(doctype: str, filters: dict, fields: list[str]) -> str:
	"""
	Fetches a list of records from a specified DocType with specific filters and fields.
	This is a powerful, generic tool for data retrieval.

	Args:
		doctype (str): The DocType to query (e.g., 'Sales Order').
		filters (dict): A dictionary of filters to apply (e.g., {'status': 'Draft'}).
		fields (list[str]): A list of the field names to retrieve (e.g., ['name', 'customer']).

	Returns:
		str: A JSON string containing the list of matching records or an error message.
	"""
	# --- Argument Sanitization ---
	# LLM may pass a string representation of a list, so we safely parse it.
	if isinstance(fields, str):
		try:
			fields = ast.literal_eval(fields)
			if not isinstance(fields, list):
				fields = [fields]
		except (ValueError, SyntaxError):
			return json.dumps({"error": "Invalid format for 'fields'. Expected a list of strings."})

	# The Gemini API can pass a special MapComposite object instead of a dict.
	# We need to convert it to a standard dictionary for Frappe.
	if filters and not isinstance(filters, dict):
		try:
			filters = dict(filters)
		except (TypeError, ValueError):
			return json.dumps({"error": "Invalid format for 'filters'. Expected a dictionary."})

	# --- Safeguard 1: DocType Allowlist ---
	try:
		settings = frappe.get_single("Gemini Settings")
		allowed_doctypes = [d.doctype_to_query for d in settings.get("queryable_doctypes", [])]
		if doctype not in allowed_doctypes:
			return json.dumps(
				{
					"error": f"Access to the '{doctype}' DocType is not permitted. Please select from the allowed list."
				}
			)
	except Exception:
		frappe.log_error("Failed to retrieve or parse 'Queryable DocTypes' from Gemini Settings.")
		return json.dumps({"error": "Could not verify DocType permissions due to a configuration error."})

	# --- Safeguard 2: Field Denylist ---
	field_denylist = ["password", "api_key", "secret", "private_key", "api_secret"]
	for field in fields:
		if field.lower() in field_denylist:
			return json.dumps({"error": f"Access to the sensitive field '{field}' is not allowed."})

	# --- Safeguard 3: Field Validation ---
	try:
		meta = frappe.get_meta(doctype)
		valid_fields = {df.fieldname for df in meta.fields}
		valid_fields.add("name")  # 'name' is always valid

		for field in fields:
			if field not in valid_fields:
				return json.dumps({"error": f"Field '{field}' is not a valid field for DocType '{doctype}'."})

	except frappe.DoesNotExistError:
		return json.dumps({"error": f"DocType '{doctype}' does not exist."})

	try:
		# --- Safeguard 4: Hardcoded Result Limit ---
		data = frappe.get_list(doctype, filters=filters, fields=fields, limit_page_length=25)
		return json.dumps(data)

	except Exception:
		frappe.log_error(
			message=f"Error in fetch_erpnext_data for {doctype}: {frappe.get_traceback()}",
			title="Gemini Tool Error",
		)
		# Provide a more user-friendly error message
		return json.dumps(
			{
				"error": f"An error occurred while querying the '{doctype}' DocType. This could be due to invalid filters or fields."
			}
		)


fetch_erpnext_data.service = "erpnext"


@mcp.tool()
@log_activity
@handle_errors
def send_email(to: str, subject: str, body: str, confirmed: bool = False) -> str:
	"""
	Prepares a draft or sends an email.

	IMPORTANT:
	1. First, call this function with confirmed=False. This will return a draft of the email.
	2. Present this draft to the user for approval.
	3. If the user approves, call the function again with the same parameters and confirmed=True to send the email.

	Args:
	    to (str): The recipient's email address.
	    subject (str): The subject of the email.
	    body (str): The body of the email.
	    confirmed (bool): If False, returns a draft. If True, sends the email. Defaults to False.

	Returns:
	    str: The draft of the email for user confirmation or a success/failure message.
	"""
	if not confirmed:
		draft = "**Email Draft for your approval:**\n\n"
		draft += f"**To:** {to}\n"
		draft += f"**Subject:** {subject}\n"
		draft += f"**Body:**\n{body}\n\n"
		draft += "Please confirm if you want to send this email."
		return draft

	try:
		credentials = get_user_credentials()
		if not credentials:
			return "Could not get user credentials. Please make sure you have authenticated with Google."

		service = build("gmail", "v1", credentials=credentials)
		message = MIMEText(body)
		message["to"] = to
		message["subject"] = subject

		raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
		create_message = {"raw": raw_message}

		send_message = service.users().messages().send(userId="me", body=create_message).execute()
		return f"Email sent successfully with Message ID: {send_message['id']}"

	except HttpError as error:
		frappe.log_error(f"An error occurred with Gmail: {error}", "Gemini Gmail Error")
		return "An error occurred while sending the email. Please check the logs for details."
	except Exception as e:
		frappe.log_error(f"An unexpected error occurred in send_email: {e}", "Gemini Gmail Error")
		return "An unexpected error occurred. Please contact the system administrator."


send_email.service = "gmail"


@mcp.tool()
@log_activity
@handle_errors
def search_contact_for_email(name: str) -> str:
	"""Searches Google Contacts for a person by name to find their email address.

	Args:
	    name (str): The name of the person to search for.

	Returns:
	    str: A JSON string containing the best match's email, a list for disambiguation, or a not found message.
	"""
	try:
		credentials = get_user_credentials()
		if not credentials:
			return json.dumps(
				{
					"error": "Could not get user credentials. Please make sure you have authenticated with Google."
				}
			)
		people_service = build("people", "v1", credentials=credentials)

		# Search for the contact
		results = (
			people_service.people()
			.searchContacts(query=name, pageSize=5, readMask="names,emailAddresses")
			.execute()
		)

		people = results.get("results", [])
		if not people:
			return json.dumps(
				{"status": "not_found", "message": f"No contact found matching the name '{name}'."}
			)

		contacts_with_email = []
		for person_result in people:
			person = person_result.get("person", {})
			display_name = person.get("names", [{}])[0].get("displayName", "N/A")
			email_addresses = person.get("emailAddresses", [])

			if email_addresses:
				primary_email = email_addresses[0].get("value")
				if primary_email:
					score = fuzz.token_set_ratio(name, display_name)
					contacts_with_email.append({"name": display_name, "email": primary_email, "score": score})

		if not contacts_with_email:
			return json.dumps(
				{"status": "not_found", "message": f"No contact with an email address found for '{name}'."}
			)

		# Sort by score descending
		sorted_contacts = sorted(contacts_with_email, key=lambda x: x["score"], reverse=True)

		# If top match has a much higher score, return it as a confident match
		if len(sorted_contacts) > 1 and sorted_contacts[0]["score"] > sorted_contacts[1]["score"] * 1.5:
			return json.dumps({"status": "found", "email": sorted_contacts[0]["email"]})

		# If there's only one result with a decent score
		if len(sorted_contacts) == 1 and sorted_contacts[0]["score"] > 70:
			return json.dumps({"status": "found", "email": sorted_contacts[0]["email"]})

		# Otherwise, return a list for the user to clarify
		return json.dumps(
			{
				"status": "disambiguation",
				"message": "Found multiple contacts. Please clarify which one you mean.",
				"contacts": sorted_contacts,
			}
		)

	except HttpError as error:
		frappe.log_error(
			f"Google People API Error for query '{name}': {str(error.content)[:100]}",
			"Gemini Contact Search Error",
		)
		return json.dumps({"status": "error", "message": "An API error occurred during contact search."})


search_contact_for_email.service = "google"


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
def search_erpnext_documents(query: str, doctype: str | None = None, limit: int = 5) -> dict:
	"""Searches for documents in ERPNext with a query, returning a dictionary of results.
	This tool implements a "waterfall" logic:
	1. Exact ID Match: Fast check for specific document IDs (e.g., 'CRM-OPP-2025-00631').
	2. Semantic Search: If not an ID, uses vector embeddings to find conceptually similar documents.
	3. Fuzzy Text Search: As a final fallback, performs a broader, less precise text search.

	Args:
	    query (str): The search query.
	    doctype (str, optional): The specific DocType to search within. If None, it
	        searches across all non-single DocTypes. Defaults to None.
	    limit (int, optional): The maximum number of documents to return.
	        Defaults to 5.

	Returns:
	    dict: A dictionary containing the search results, structured for programmatic use.
	"""
	try:
		limit = int(limit)

		# --- Priority #1: Exact ID Match ---
		# Use a flexible regex to detect if the query is a likely document ID, then verify its existence.
		if re.match(r"^([A-Z]{2,}[-.]?)+(\d{4,})([-.]?\d+)*$", query.strip(), re.IGNORECASE):
			# If a specific doctype is provided, check only that one.
			# Otherwise, check all non-single DocTypes.
			doctypes_to_check = (
				[doctype] if doctype else frappe.get_all("DocType", filters={"issingle": 0}, pluck="name")
			)
			for dt in doctypes_to_check:
				if frappe.db.exists(dt, query):
					# If a match is found, fetch the full document and return it as a confident match.
					doc = frappe.get_doc(dt, query)
					doc_dict = json.loads(frappe.as_json(doc))
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

		# --- Priority #2: Semantic Embedding Search ---
		query_embedding = generate_embedding(query)
		if query_embedding:
			similar_docs = find_similar_documents(np.array(query_embedding), doctype, limit)

			# Filter out results below the base threshold
			relevant_docs = [doc for doc in similar_docs if doc.get("score", 0) >= 0.75]

			if relevant_docs:
				# Confident Match: If top score is 1.5x higher than the second, we have a clear winner.
				if len(relevant_docs) == 1 or (
					len(relevant_docs) > 1 and relevant_docs[0]["score"] >= relevant_docs[1]["score"] * 1.5
				):
					top_doc_info = relevant_docs[0]
					doc = frappe.get_doc(top_doc_info["doctype"], top_doc_info["name"])
					doc_dict = json.loads(frappe.as_json(doc))
					meta = frappe.get_meta(top_doc_info["doctype"])
					title_field = meta.get_title_field()
					label = (title_field and doc.get(title_field)) or doc.name

					context = f"Found a confident match for '{query}' based on semantic similarity: {label} (ID: {top_doc_info['name']}, Type: {top_doc_info['doctype']}).\n\nFull details:\n"
					for field, value in doc_dict.items():
						if value:
							if isinstance(value, list):
								context += f"- {field}: (Contains a list of {len(value)} items)\n"
							else:
								context += f"- {field}: {value}\n"
					doc_url = get_url_to_form(top_doc_info["doctype"], top_doc_info["name"])
					context += f"\nLink: {doc_url}"
					return {"type": "confident_match", "doc": doc_dict, "string_representation": context}

				# Disambiguation: If there are multiple relevant results but no clear winner, ask the user.
				results_string = "I found a few potential matches. Which one did you mean?\n"
				for doc in relevant_docs:
					meta = frappe.get_meta(doc["doctype"])
					title_field = meta.get_title_field()
					label = (
						title_field and frappe.db.get_value(doc["doctype"], doc["name"], title_field)
					) or doc["name"]
					doc_url = get_url_to_form(doc["doctype"], doc["name"])
					results_string += f"- <a href='{doc_url}' target='_blank'>{label}</a> (ID: {doc['name']}, Type: {doc['doctype']}, Score: {doc['score']:.2f})\n"
					if doc.get("content"):
						results_string += f"  - Matching Content: \"...{doc['content'][:150]}...\"\n"
				return {
					"type": "disambiguation",
					"docs": relevant_docs,
					"string_representation": results_string,
				}

		# --- Priority #3: Fuzzy Text Search (Fallback) ---
		default_doctypes = [
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
		]
		doctypes_to_search = [doctype] if doctype else default_doctypes
		all_scored_docs = []

		for dt in doctypes_to_search:
			try:
				meta = frappe.get_meta(dt)
				fields_to_fetch = _get_doctype_fields(dt)
				text_like_fields = [
					f.fieldname
					for f in meta.fields
					if f.fieldtype
					in ["Data", "Text", "Small Text", "Long Text", "Select", "Link", "Read Only"]
					and f.fieldname in fields_to_fetch
				]
				if not text_like_fields:
					continue
				or_filters = [[field, "like", f"%{query}%"] for field in text_like_fields]
				candidate_docs = frappe.get_all(
					dt, fields=fields_to_fetch, or_filters=or_filters, limit_page_length=20
				)

				if not candidate_docs:
					continue

				title_field = meta.get_title_field()
				search_fields = meta.get_search_fields()
				field_weights = {"name": 3.0}
				if title_field and title_field in fields_to_fetch:
					field_weights[title_field] = 3.0
				for f in search_fields:
					if f not in field_weights and f in fields_to_fetch:
						field_weights[f] = 1.5

				for doc in candidate_docs:
					total_score = 0
					full_text = " ".join(
						[str(doc.get(f, "")) for f in fields_to_fetch if f not in field_weights]
					)
					total_score += fuzz.token_set_ratio(query, full_text)
					for field, weight in field_weights.items():
						field_value = str(doc.get(field, ""))
						if field_value:
							total_score += fuzz.token_set_ratio(query, field_value) * weight

					if total_score > 70:
						label = (title_field and doc.get(title_field)) or doc.name
						all_scored_docs.append(
							{"name": doc.name, "doctype": dt, "score": total_score, "label": label}
						)

			except frappe.DoesNotExistError:
				continue

		if all_scored_docs:
			sorted_docs = sorted(all_scored_docs, key=lambda x: x["score"], reverse=True)
			if len(sorted_docs) == 1 or (
				len(sorted_docs) > 1 and sorted_docs[0]["score"] > sorted_docs[1]["score"] * 1.5
			):
				top_doc_info = sorted_docs[0]
				doc = frappe.get_doc(top_doc_info["doctype"], top_doc_info["name"])
				doc_dict = json.loads(frappe.as_json(doc))
				context = f"Found a confident match for '{query}': {top_doc_info['label']} (ID: {top_doc_info['name']}, Type: {top_doc_info['doctype']}).\n\nFull details:\n"
				for field, value in doc_dict.items():
					if value and not isinstance(value, list):
						context += f"- {field}: {value}\n"
				doc_url = get_url_to_form(top_doc_info["doctype"], top_doc_info["name"])
				context += f"\nLink: {doc_url}"
				return {"type": "confident_match", "doc": doc_dict, "string_representation": context}
			else:
				results_string = f"Found multiple potential matches for '{query}'. Please clarify:\n"
				disambiguation_docs = []
				for doc in sorted_docs[:limit]:
					doc_url = get_url_to_form(doc["doctype"], doc["name"])
					results_string += f"- <a href='{doc_url}' target='_blank'>{doc['label']}</a> (ID: {doc['name']}, Type: {doc['doctype']}, Score: {doc['score']:.2f})\n"
					disambiguation_docs.append(doc)
				return {
					"type": "disambiguation",
					"docs": disambiguation_docs,
					"string_representation": results_string,
				}

		# --- Final "No Results" Output ---
		no_results_message = f"I couldn't find any documents matching your query for '{query}'. You could try rephrasing your search, or if you know the specific ID, you can use that directly."
		return {"type": "no_match", "string_representation": no_results_message}

	except Exception:
		frappe.log_error(
			message=f"Error in search_erpnext_documents: {frappe.get_traceback()}",
			title="Gemini Search Error",
		)
		error_string = (
			"An error occurred while searching for documents. Please check the Error Log for details."
		)
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
				{
					"error": "Could not get user credentials. Please make sure you have authenticated with Google."
				}
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
			f"Google People API Error for query '{name}': {str(error.content)[:100]}",
			"Gemini Contact Search Error",
		)
		return json.dumps({"error": "An API error occurred during contact search."})


search_google_contacts.service = "google"


@mcp.tool()
@log_activity
@handle_errors
def create_drive_file(file_name: str, file_content: str, folder_id: str | None = None) -> str:
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

		fh = BytesIO(file_content.encode("utf-8"))
		media = MediaIoBaseUpload(fh, mimetype="text/plain")

		file = (
			service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink").execute()
		)
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
		fh = BytesIO(file_content.encode("utf-8"))
		media = MediaIoBaseUpload(fh, mimetype="text/plain")

		service.files().update(fileId=file_id, media_body=media).execute()
		return "File updated successfully."
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
	    confirm (bool): Confirmation to delete. Defaults to False.

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
def modify_gmail_label(
	message_id: str, add_labels: list[str] | None = None, remove_labels: list[str] | None = None
) -> str:
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
			body["addLabelIds"] = add_labels
		if remove_labels:
			body["removeLabelIds"] = remove_labels

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
	    confirm (bool): Confirmation to delete. Defaults to False.

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
def create_google_calendar_event(
	summary: str, start_time: str, end_time: str, attendees: list[str] | None = None
) -> str:
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
			"summary": summary,
			"start": {
				"dateTime": start_time,
				"timeZone": frappe.db.get_single_value("System Settings", "time_zone"),
			},
			"end": {
				"dateTime": end_time,
				"timeZone": frappe.db.get_single_value("System Settings", "time_zone"),
			},
		}
		if attendees:
			event["attendees"] = [{"email": email} for email in attendees]

		created_event = service.events().insert(calendarId="primary", body=event).execute()
		return f"Event created successfully. Link: {created_event.get('htmlLink')}"
	except HttpError as error:
		return f"An error occurred with Google Calendar: {error}"


create_google_calendar_event.service = "calendar"


@mcp.tool()
@log_activity
@handle_errors
def update_google_calendar_event(
	event_id: str,
	summary: str | None = None,
	start_time: str | None = None,
	end_time: str | None = None,
	attendees: list[str] | None = None,
) -> str:
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
		event = service.events().get(calendarId="primary", eventId=event_id).execute()

		if summary:
			event["summary"] = summary
		if start_time:
			event["start"]["dateTime"] = start_time
		if end_time:
			event["end"]["dateTime"] = end_time
		if attendees:
			event["attendees"] = [{"email": email} for email in attendees]

		updated_event = service.events().update(calendarId="primary", eventId=event_id, body=event).execute()
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
	    confirm (bool): Confirmation to delete. Defaults to False.

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
		service.events().delete(calendarId="primary", eventId=event_id).execute()
		return "Event deleted successfully."
	except HttpError as error:
		return f"An error occurred with Google Calendar: {error}"


delete_google_calendar_event.service = "calendar"


@mcp.tool()
@log_activity
@handle_errors
def create_comment(reference_doctype: str, reference_name: str, comment: str, confirmed: bool = False) -> str:
	"""
	Adds a comment to a document or asks for confirmation.

	Args:
	    reference_doctype (str): The DocType of the document to comment on.
	    reference_name (str): The name of the document to comment on.
	    comment (str): The content of the comment.
	    confirmed (bool): If False, returns a draft. If True, creates the comment.

	Returns:
	    str: A summary for confirmation or a success/failure message.
	"""
	if not confirmed:
		return f"""**Comment Draft for your approval:**

**On Document:** {reference_doctype} - {reference_name}
**Comment:**
{comment}

Please confirm if you want to add this comment."""

	if not frappe.has_permission(reference_doctype, "write", reference_name):
		return f"You do not have permission to add comments to {reference_doctype} {reference_name}."

	try:
		new_comment = frappe.new_doc("Comment")
		new_comment.comment_type = "Comment"
		new_comment.reference_doctype = reference_doctype
		new_comment.reference_name = reference_name
		new_comment.content = comment
		new_comment.insert(ignore_permissions=True)  # Permissions already checked
		return f"Comment successfully added to {reference_doctype} {reference_name}."
	except Exception as e:
		frappe.log_error(f"Error creating comment: {e}", "Gemini Tool Error")
		return "An error occurred while creating the comment."


create_comment.service = "erpnext"


@mcp.tool()
@log_activity
@handle_errors
def create_task(
	subject: str,
	project: str | None = None,
	description: str | None = None,
	priority: str | None = None,
	assigned_to: str | None = None,
	exp_end_date: str | None = None,
	confirmed: bool = False,
) -> str:
	"""
	Creates a new Task in ERPNext or asks for confirmation.

	Args:
	    subject (str): The subject or title of the task.
	    project (str, optional): The project this task belongs to. Defaults to None.
	    description (str, optional): A detailed description of the task. Defaults to None.
	    priority (str, optional): Priority of the task (e.g., 'Low', 'Medium', 'High'). Defaults to None.
	    assigned_to (str, optional): The full name of the person to assign the task to. Defaults to None.
	    exp_end_date (str, optional): The expected end date for the task (e.g., '2024-12-31'). Defaults to None.
	    confirmed (bool): If False, returns a draft. If True, creates the task.

	Returns:
	    str: A summary for confirmation or a success/failure message.
	"""
	if not confirmed:
		draft = "**Task Draft for your approval:**\n\n"
		draft += f"**Subject:** {subject}\n"
		if project:
			draft += f"**Project:** {project}\n"
		if description:
			draft += f"**Description:** {description}\n"
		if priority:
			draft += f"**Priority:** {priority}\n"
		if assigned_to:
			draft += f"**Assigned To:** {assigned_to}\n"
		if exp_end_date:
			draft += f"**Due Date:** {exp_end_date}\n"
		draft += "\nPlease confirm if you want to create this task."
		return draft

	if not frappe.has_permission("Task", "create"):
		return "You do not have permission to create Tasks."

	try:
		task = frappe.new_doc("Task")
		task.subject = subject
		if project:
			task.project = project
		if description:
			task.description = description
		if priority and priority in ["Low", "Medium", "High"]:
			task.priority = priority
		if exp_end_date:
			task.exp_end_date = exp_end_date

		assignee_email = None
		if assigned_to:
			user = frappe.db.get_value("User", {"full_name": assigned_to}, "email")
			if user:
				assignee_email = user
			else:
				user = frappe.db.get_value("User", {"email": assigned_to}, "email")
				if user:
					assignee_email = user

			if not assignee_email:
				return f"Could not find a user with the name or email '{assigned_to}' to assign the task to."

		task.insert(ignore_permissions=True)

		if assignee_email:
			task.add_assignee(assignee_email)

		task_url = get_url_to_form("Task", task.name)
		return f"Task '{subject}' created successfully. Link: {task_url}"
	except Exception as e:
		frappe.log_error(f"Error creating task: {e}", "Gemini Tool Error")
		return "An error occurred while creating the task."


create_task.service = "erpnext"


@mcp.tool()
@log_activity
@handle_errors
def update_document_status(doctype: str, docname: str, status: str, confirmed: bool = False) -> str:
	"""
	Updates the status of a document (e.g., Task, Project) or asks for confirmation.

	Args:
	    doctype (str): The DocType of the document to update.
	    docname (str): The name of the document to update.
	    status (str): The new status to set for the document.
	    confirmed (bool): If False, returns a draft. If True, updates the status.

	Returns:
	    str: A summary for confirmation or a success/failure message.
	"""
	if not confirmed:
		return f"""**Status Update Confirmation:**

**Document:** {doctype} - {docname}
**New Status:** {status}

Please confirm if you want to apply this status change."""

	if not frappe.has_permission(doctype, "write", docname):
		return f"You do not have permission to update the status of {doctype} {docname}."

	try:
		doc = frappe.get_doc(doctype, docname)
		doc.status = status
		doc.save(ignore_permissions=True)  # Permissions already checked
		doc_url = get_url_to_form(doctype, docname)
		return f"Status of {doctype} {docname} updated to '{status}'. Link: {doc_url}"
	except Exception as e:
		frappe.log_error(f"Error updating document status: {e}", "Gemini Tool Error")
		return "An error occurred while updating the document status."


from gemini_integration.utils import generate_text as gemini_generate_text

update_document_status.service = "erpnext"


@mcp.tool()
@log_activity
@handle_errors
def generate_text(prompt: str) -> str:
	"""
	Generates text using the Gemini model. This is a general-purpose tool for text creation.

	Args:
	    prompt (str): The prompt for the model.

	Returns:
	    str: The generated text.
	"""
	return gemini_generate_text(prompt)


generate_text.service = "erpnext"


@mcp.tool()
@log_activity
@handle_errors
def project_health_check(project_name: str) -> str:
	"""
	Provides a health check on a project.

	Args:
	    project_name (str): The name of the project to check.

	Returns:
	    str: A Markdown formatted report of the project's health.
	"""
	project = search_erpnext_documents(query=project_name, doctype="Project")

	if project["type"] != "confident_match":
		return project["string_representation"]

	project_data = project["doc"]

	tasks = fetch_erpnext_data(
		doctype="Task",
		filters={"project": project_data["name"]},
		fields=["name", "subject", "status", "exp_end_date"],
	)

	comments = fetch_erpnext_data(
		doctype="Comment",
		filters={"reference_doctype": "Project", "reference_name": project_data["name"]},
		fields=["name", "comment_by", "content"],
	)

	emails = search_gmail(query=project_name)

	prompt = f"""
    Analyze the following project data, tasks, comments, and emails to generate a comprehensive health report in Markdown format.
    Your analysis should identify potential risks by examining the language and content of the provided information.
    Look for signs of delays, budget issues, scope creep, negative sentiment, or resource constraints.
    Structure the report with clear headings for each section (e.g., Budget, Timeline, Risks).

    Project Data: {project_data}
    Tasks: {tasks}
    Comments: {comments}
    Emails: {emails}
    """

	health_report = gemini_generate_text(prompt)

	return health_report


project_health_check.service = "erpnext"
