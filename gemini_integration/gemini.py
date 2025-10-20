import base64
import copy
import json
import re
from datetime import datetime, timedelta

import base64
import copy
import json
import re
from datetime import datetime, timedelta

import base64
import copy
import json
import re
from datetime import datetime, timedelta

import base64
import copy
import json
import re
from datetime import datetime, timedelta

import base64
import copy
import json
import re
from datetime import datetime, timedelta

import base64
import copy
import json
import re
from datetime import datetime, timedelta

import base64
import copy
import json
import re
from datetime import datetime, timedelta

import base64
import copy
import json
import re
from datetime import datetime, timedelta

import base64
import copy
import json
import re
from datetime import datetime, timedelta

import base64
import copy
import json
import re
from datetime import datetime, timedelta

import base64
import copy
import json
import re
from datetime import datetime, timedelta

import base64
import copy
import json
import re
from datetime import datetime, timedelta

import base64
import copy
import json
import re
from datetime import datetime, timedelta

import base64
import copy
import json
import re
from datetime import datetime, timedelta

import base64
import copy
import json
import re
from datetime import datetime, timedelta

import base64
import copy
import json
import re
from datetime import datetime, timedelta

import base64
import copy
import json
import re
from datetime import datetime, timedelta

import frappe
import google.generativeai as genai
import requests
from frappe.utils import get_site_url, get_url_to_form

# Google API Imports
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
from gemini_integration.utils import configure_gemini, generate_embedding

# --- GEMINI API CONFIGURATION AND BASIC GENERATION ---


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


@log_activity
@handle_errors
def generate_image(prompt):
	"""Generates an image using the Gemini 2.5 Flash Image model.

	Args:
	    prompt (str): The text prompt for the image generation.

	Returns:
	    str: The public URL of the generated image file, or None on failure.
	"""
	if not configure_gemini():
		frappe.throw("Gemini integration is not configured. Please set the API Key in Gemini Settings.")

	try:
		model_instance = genai.GenerativeModel("gemini-2.5-flash-image")
		response = model_instance.generate_content(prompt)

		image_data = None
		for part in response.candidates[0].content.parts:
			if part.inline_data:
				image_data = part.inline_data.data
				break

		if image_data:
			# Create a unique filename
			file_name = f"gemini-generated-{frappe.utils.now_datetime().strftime('%Y%m%d-%H%M%S')}.png"
			# Create a new Frappe File document
			file_doc = frappe.new_doc("File")
			file_doc.file_name = file_name
			file_doc.content = image_data
			file_doc.is_private = 0  # Make it a public file
			file_doc.save(ignore_permissions=True)
			return file_doc.file_url

		return None

	except Exception as e:
		frappe.log_error(f"Gemini Image Generation API Error: {e!s}", "Gemini Integration")
		frappe.throw(
			"An error occurred while generating the image. Please check the Error Log for details."
		)




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


def _get_doctype_from_prompt(prompt: str) -> str | None:
	"""Analyzes a prompt to find the best matching DocType name using keywords.

	Args:
	    prompt (str): The user's input prompt.

	Returns:
	    str | None: The best matching DocType name, or None if no clear match is found.
	"""
	from gemini_integration.tools import find_best_match_for_doctype

	# A mapping of keywords to the DocType they most likely represent.
	# The keys are keywords/synonyms, and the values are the official DocType names.
	doctype_keywords = {
		"project": "Project",
		"projects": "Project",
		"customer": "Customer",
		"customers": "Customer",
		"supplier": "Supplier",
		"suppliers": "Supplier",
		"item": "Item",
		"items": "Item",
		"product": "Item",
		"products": "Item",
		"sales order": "Sales Order",
		"sales orders": "Sales Order",
		"so": "Sales Order",
		"purchase order": "Purchase Order",
		"purchase orders": "Purchase Order",
		"po": "Purchase Order",
		"lead": "Lead",
		"leads": "Lead",
		"opportunity": "Opportunity",
		"opportunities": "Opportunity",
		"task": "Task",
		"tasks": "Task",
		"issue": "Issue",
		"issues": "Issue",
		"quotation": "Quotation",
		"quotations": "Quotation",
		"sales invoice": "Sales Invoice",
		"sales invoices": "Sales Invoice",
		"si": "Sales Invoice",
		"purchase invoice": "Purchase Invoice",
		"purchase invoices": "Purchase Invoice",
		"pi": "Purchase Invoice",
		"employee": "Employee",
		"employees": "Employee",
	}

	# Find all keywords present in the prompt (case-insensitive)
	found_keywords = []
	for keyword in doctype_keywords:
		# Use word boundaries to avoid matching parts of words (e.g., 'so' in 'some')
		if re.search(rf"\b{re.escape(keyword)}\b", prompt, re.IGNORECASE):
			found_keywords.append(keyword)

	if not found_keywords:
		return None

	# If multiple keywords are found, we could add logic to prioritize.
	# For now, we'll use the first one found that maps to a valid DocType.
	for keyword in found_keywords:
		potential_doctype = doctype_keywords[keyword]
		# Verify that the mapped DocType actually exists in the system
		# by calling the tool function directly.
		matched_doctype = find_best_match_for_doctype(potential_doctype)
		if matched_doctype:
			return matched_doctype

	return None


def _uppercase_schema_types(schema):
	"""Recursively converts all 'type' values in a JSON schema to uppercase."""
	if isinstance(schema, dict):
		for key, value in schema.items():
			if key == "type" and isinstance(value, str):
				schema[key] = value.upper()
			else:
				_uppercase_schema_types(value)
	elif isinstance(schema, list):
		for item in schema:
			_uppercase_schema_types(item)
	return schema


def _linkify_erpnext_docs(text):
	"""Finds potential ERPNext document names in text and replaces them with links."""
	# This regex looks for patterns like 'PRJ-00001' or 'CUST-00002'.
	pattern = re.compile(r"(?<!['\"/>])([A-Z]{2,5}-\d{5,})(?!['\"/<])")

	def get_doctypes_from_cache():
		"""Fetches a list of non-single DocTypes, caching the result."""
		cache_key = "gemini_linkify_doctypes"
		doctypes = frappe.cache().get_value(cache_key)
		if not doctypes:
			doctypes = frappe.get_all("DocType", filters={"issingle": 0}, pluck="name")
			# Cache for an hour to balance freshness and performance.
			frappe.cache().set_value(cache_key, doctypes, expires_in_sec=3600)
		return doctypes

	doctypes_to_check = get_doctypes_from_cache()

	def replacer(match):
		doc_name = match.group(1)
		prefix = doc_name.split("-")[0]

		# This is a heuristic and might need adjustment based on naming series conventions.
		potential_doctype = next((dt for dt in doctypes_to_check if dt.upper().startswith(prefix)), None)

		if potential_doctype and frappe.db.exists(potential_doctype, doc_name):
			doc_url = get_url_to_form(potential_doctype, doc_name)
			return f'<a href="{doc_url}" target="_blank">{doc_name}</a>'

		return doc_name

	return pattern.sub(replacer, text)


# --- MAIN CHAT FUNCTIONALITY ---


@log_activity
@handle_errors
def generate_chat_response(
	prompt,
	model=None,
	conversation_id=None,
	use_google_search=False,
	stream=False,
	user=None,
	doctype=None,
	docname=None,
):
	"""Handles chat interactions by routing them to the correct MCP tools.

	Args:
	    prompt (str): The user's chat prompt.
	    model (str, optional): The model to use for the chat. Defaults to None.
	    conversation_id (str, optional): The ID of the existing conversation. Defaults to None.
	    use_google_search (bool, optional): Whether to enable Google Search for this query.
	        Defaults to False.
	    stream (bool, optional): Whether to stream the response. Defaults to False.
	    user (str, optional): The user initiating the request. This is crucial for background jobs.
	        Defaults to None.
	    doctype (str, optional): The DocType of the document the user is viewing. Defaults to None.
	    docname (str, optional): The name of the document the user is viewing. Defaults to None.

	Returns:
	    dict or generator: A dictionary containing the response, thoughts, and conversation ID,
	        or a generator that yields the response chunks.
	"""
	# Configure the Gemini client before proceeding
	settings = frappe.get_single("Gemini Settings")
	api_key = settings.get_password("api_key")
	if not api_key:
		frappe.throw("Gemini API Key not found. Please configure it in Gemini Settings.")

	try:
		genai.configure(api_key=api_key)
	except Exception as e:
		frappe.log_error(f"Failed to configure Gemini: {e!s}", "Gemini Integration")
		frappe.throw("An error occurred during Gemini configuration. Please check the logs.")

	# --- Image Generation Logic ---
	image_url = None
	image_keywords = [
		"generate a picture of", "create a picture of", "generate an image of",
		"create an image of", "show me a picture of", "draw a picture of",
		"generate a photo of", "create a photo of", "show me an image of"
	]
	is_image_request = any(keyword in prompt.lower() for keyword in image_keywords)

	if is_image_request:
		image_url = generate_image(prompt)
	# --- End Image Generation Logic ---

	from gemini_integration.mcp import mcp

	# Load the conversation history from the database if a conversation ID is provided.
	# The Gemini API expects a specific format, so we will transform it later.
	conversation_history = []
	if conversation_id:
		try:
			conversation_doc = frappe.get_doc("Gemini Conversation", conversation_id)
			if conversation_doc.conversation:
				# The conversation is stored as a JSON string.
				conversation_history = json.loads(conversation_doc.conversation)
		except frappe.DoesNotExistError:
			# If the conversation ID is invalid, we start a new conversation.
			conversation_id = None

	# 1. Determine which toolsets to use based on @-mentions and search settings.
	mentioned_services = re.findall(r"@(\w+)", prompt.lower())
	tool_declarations = []

	# If no specific services are mentioned, the model will act as a general chatbot.
	# If services are mentioned, we gather the appropriate tools.
	if mentioned_services:
		# Create a mapping from the service mention to the tool function names.
		# This is more robust than relying on direct name matching.
		service_to_tool_map = {
			"erpnext": ["search_erpnext_documents"],
			"google": [
				"search_drive",
				"search_gmail",
				"search_calendar",
				"search_google_contacts",
			],
			"drive": ["search_drive"],
			"gmail": [
				"send_email",
				"search_gmail",
				"get_gmail_message_context",
				"modify_gmail_label",
				"delete_gmail_message",
			],
			"calendar": ["search_calendar"],
			"contacts": ["search_google_contacts"],
		}

		# Get a list of all tool names to add based on the mentions.
		tools_to_add = set()
		for service in mentioned_services:
			tool_names = service_to_tool_map.get(service, [])
			for tool_name in tool_names:
				tools_to_add.add(tool_name)

		# Now, add the tool declarations for the selected tools.
		for tool_name in tools_to_add:
			if tool_name in mcp._tool_registry:
				tool = mcp._tool_registry[tool_name]
				# Sanitize the tool declaration for the Google API
				input_schema = tool.get("input_schema")
				if input_schema and "properties" in input_schema:
					parameters = {
						"type": "object",
						"properties": input_schema.get("properties", {}),
						"required": input_schema.get("required", []),
					}
				else:
					parameters = None # Should not happen if schema is well-formed

				declaration = {
					"name": tool.get("name"),
					"description": tool.get("description"),
					"parameters": parameters,
				}
				declaration = {k: v for k, v in declaration.items() if v is not None}
				if "parameters" in declaration:
					declaration["parameters"] = _uppercase_schema_types(declaration["parameters"])
				tool_declarations.append(declaration)

	# Add the Google Search tool if enabled.
	if settings.enable_google_search and use_google_search:
		tool_declarations.append({"google_search": {}})

	# If no tools are selected (no mentions, no search), the tool_declarations list will be empty,
	# and the model will behave like a standard chatbot, which is the desired behavior.

	# 2. Check for Google authentication if Google services are mentioned.
	# We don't need to pass credentials around, as the tools get them directly.
	google_services_mentioned = any(
		service in ["google", "gmail", "drive", "calendar", "contacts"] for service in mentioned_services
	)
	if google_services_mentioned:
		from gemini_integration.utils import is_google_integrated

		if not is_google_integrated():
			return {
				"response": "Please connect your Google account to use this feature.",
				"thoughts": "User is not authenticated with Google.",
				"conversation_id": conversation_id,
			}

	# 3. Set up the model with the dynamically selected tools and context.
	model_name = model or frappe.db.get_single_value("Gemini Settings", "default_model") or "gemini-2.5-pro"

	# --- Context Injection and Automatic Tool Call ---
	# A list of generic prompts that should trigger an automatic context fetch.
	generic_prompts = [
		"summarize this", "summarize", "explain this", "explain", "describe this", "what is this",
		"give me a summary", "can you summarize this?", "tell me about this"
	]

	document_context_for_model = ""
	# If context is provided, we might need to pre-emptively fetch the document.
	if doctype and docname:
		# Check if the prompt is generic enough to warrant an automatic fetch.
		if prompt.strip().lower() in generic_prompts:
			try:
				# Automatically call the tool to get the document's content.
				context_result = get_doc_context(doctype=doctype, docname=docname)
				if isinstance(context_result, dict) and context_result.get("string_representation"):
					document_context_for_model = context_result["string_representation"]
			except Exception as e:
				# If the tool call fails, we log it but don't block the chat.
				# The model can still proceed with the basic context.
				frappe.log_error(
					f"Automatic context fetch failed for {doctype} {docname}: {e!s}",
					"Gemini Integration",
				)

	# --- System Instruction Setup ---
	# Add a system instruction to ground the model and prevent hallucinations.
	system_instruction = """
You are an AI assistant integrated into ERPNext. When you use tools to access ERPNext data (like 'search_erpnext_documents'), you must strictly follow these rules:
1. Base your answers ONLY on the information returned by the tool.
2. If the tool returns a message like 'No documents found', you MUST state that you did not find any matching documents. Do NOT invent or suggest documents from your own knowledge.
3. If the tool returns a list of potential matches, you MUST present this list to the user for clarification. Do NOT treat it as a final answer.
4. Clearly separate information that comes from ERPNext tools from your general knowledge. For example, say 'I found the following in ERPNext...' when presenting tool results.
"""
	if doctype and docname:
		system_instruction += f"\n\n--- CURRENT PAGE CONTEXT ---\nThe user is currently viewing the '{doctype}' document titled '{docname}'. Prioritize this information to answer their questions."
		if document_context_for_model:
			system_instruction += "\n\nThe full content of this document has been pre-fetched for you. Use it to answer the user's prompt.\n"
			system_instruction += f"DOCUMENT CONTENT:\n{document_context_for_model}"
		system_instruction += "\n--- END CONTEXT ---"


	# Find the most recent tool context in the history and add it to the system prompt.
	latest_context = None
	for entry in reversed(conversation_history):
		if entry.get("role") == "tool_context":
			try:
				content = entry.get("content")
				context_data = json.loads(content) if isinstance(content, str) else content
				if isinstance(context_data, dict) and "doc" in context_data:
					latest_context = json.dumps(context_data["doc"], indent=2)
					break
			except (json.JSONDecodeError, TypeError):
				continue

	if latest_context:
		context_instruction = f"""---
HERE IS THE CONTEXT FOR THE CURRENT CONVERSATION.
A tool was previously run and returned the following data about a specific document.
You MUST use this data to answer the user's follow-up questions about this document.
If the user asks for information that is clearly not in this data, you may use your tools again to find more specific details related to this document.

CONTEXT:
{latest_context}
---
"""
		system_instruction += context_instruction

	# Now, initialize the model with the final, context-aware system instruction.
	if tool_declarations:
		tool_config = {"function_calling_config": {"mode": "AUTO"}}
		model_instance = genai.GenerativeModel(
			model_name,
			tools=tool_declarations,
			tool_config=tool_config,
			system_instruction=system_instruction,
		)
	else:
		model_instance = genai.GenerativeModel(model_name, system_instruction=system_instruction)


	# The Gemini API expects a specific format for conversation history.
	# We filter out our internal 'tool_context' messages before sending.
	gemini_history = []
	for entry in conversation_history:
		if entry.get("role") == "tool_context":
			continue # Do not send internal context to the model as chat history
		# The role must be 'user' or 'model'. Our doctype uses 'gemini'.
		role = "model" if entry.get("role") == "gemini" else "user"
		gemini_history.append({"role": role, "parts": [entry.get("text")]})

	chat = model_instance.start_chat(history=gemini_history)

	# 4. Send the prompt and handle the response, including any tool calls
	# Send the initial prompt and start the response processing.
	response_stream = chat.send_message(prompt, stream=stream)

	def process_response_stream(current_stream):
		"""
		Processes a response stream, handles tool calls, and returns the final text.
		This function is designed to be called recursively for tool calls.
		"""
		final_response_text = ""
		tool_calls_log = []

		for chunk in current_stream:
			try:
				# Robustly check for a function call in any part of the chunk
				function_call = None
				if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
					for part in chunk.candidates[0].content.parts:
						if part.function_call:
							function_call = part.function_call
							break

				if function_call:
					tool_name = function_call.name
					tool_args = {key: value for key, value in function_call.args.items()}

					# If the model wants to search ERPNext but didn't specify a DocType,
					# we'll try to infer one from the user's prompt to improve accuracy.
					if tool_name == "search_erpnext_documents":
						if not tool_args.get("doctype"):
							detected_doctype = _get_doctype_from_prompt(prompt)
							if detected_doctype:
								tool_args["doctype"] = detected_doctype
								frappe.log_info(
									f"Inferred DocType '{detected_doctype}' for search from prompt.",
									"Gemini Integration",
								)
						# If the model is asking for a broad summary without a specific query,
						# use the original prompt as the query for semantic search.
						if not tool_args.get("query"):
							tool_args["query"] = prompt
							frappe.log_info(
								"No query found for search. Using the original prompt as the query.",
								"Gemini Integration",
							)

					# Log the raw function call for debugging
					frappe.log_error(
						message=f"Gemini requested tool: {tool_name} with args: {tool_args}",
						title="Gemini Tool Call",
					)

					# Execute the tool function
					tool_function = mcp._tool_registry[tool_name]["fn"]
					tool_result_obj = tool_function(**tool_args)

					# Determine the representation of the result to send back to the model
					if isinstance(tool_result_obj, dict):
						tool_result_for_model = tool_result_obj.get(
							"string_representation", str(tool_result_obj)
						)
					else:
						tool_result_for_model = str(tool_result_obj)

					# If the tool was a successful document search, save the full context
					if (
						tool_name == "search_erpnext_documents"
						and isinstance(tool_result_obj, dict)
						and tool_result_obj.get("type") == "confident_match"
					):
						conversation_history.append(
							{"role": "tool_context", "content": json.dumps(tool_result_obj)}
						)

					# Log the result being sent back to the model
					tool_calls_log.append(
						{"tool": tool_name, "arguments": tool_args, "result": tool_result_for_model}
					)
					frappe.log_error(
						message=f"Sending tool response for {tool_name} to Gemini: {tool_result_for_model}",
						title="Gemini Tool Response",
					)

					# The stream must be fully consumed before sending the next message.
					# Calling resolve() finishes the iteration.
					current_stream.resolve()

					# Send the tool's result back to the model and get the new response stream
					function_response_payload = [
						{
							"function_response": {
								"name": tool_name,
								"response": {"contents": tool_result_for_model},
							}
						}
					]
					new_response_stream = chat.send_message(function_response_payload, stream=stream)

					# Process the new stream to get the final answer from the model
					# This recursive call handles subsequent tool calls or the final text response
					final_text, nested_logs = process_response_stream(new_response_stream)
					final_response_text += final_text
					tool_calls_log.extend(nested_logs)
					# Once we've handled a tool call and its subsequent response, we break the loop
					# as the rest of the original stream is now irrelevant.
					break

				else:
					# This is a regular text chunk, not a tool call
					text_chunk = ""
					try:
						text_chunk = chunk.text
					except ValueError:
						# This can happen if a chunk is empty or has non-text parts after a tool call.
						# We can safely ignore these.
						continue

					final_response_text += text_chunk
					if stream:
						frappe.publish_realtime(
							"gemini_chat_update", {"message": text_chunk}, user=user
						)

			except Exception as e:
				frappe.log_error(
					message=f"Error processing Gemini stream chunk: {e!s}\n{frappe.get_traceback()}",
					title="Gemini Stream Error",
				)
				if stream:
					# Notify the user of the error via the websocket
					frappe.publish_realtime(
						"gemini_chat_update",
						{"error": "An error occurred while processing the response."},
						user=user,
					)
				# Stop processing the stream on error
				break

		return final_response_text, tool_calls_log

	# --- Main Execution Logic ---

	# If streaming, the process runs entirely in the background, communicating via WebSockets.
	if stream:
		# Ensure a conversation exists before starting the stream
		if not conversation_id:
			conversation_id = save_conversation(None, prompt, [], user=user)
			frappe.publish_realtime(
				"gemini_chat_update",
				{"conversation_id": conversation_id},
				user=user,
			)

		# Process the stream from the initial prompt
		final_response_text, tool_calls_log = process_response_stream(response_stream)

		# Linkify any ERPNext document IDs found in the final response
		final_response_text = _linkify_erpnext_docs(final_response_text)

		# Log the full tool call trace if any tools were used
		if tool_calls_log:
			log_entry = {
				"source": "Gemini Tool Call Trace",
				"tool_calls": tool_calls_log,
				"final_response": final_response_text,
			}
			frappe.log_error(
				message=json.dumps(log_entry, indent=2, default=str),
				title="Gemini Tool Call Trace",
			)

		# Update and save the complete conversation history
		conversation_history.append({"role": "user", "text": prompt})
		conversation_history.append({"role": "gemini", "text": final_response_text})
		save_conversation(conversation_id, prompt, conversation_history)

		# Signal the end of the stream to the client
		frappe.publish_realtime("gemini_chat_update", {"end_of_stream": True}, user=user)
		# Since this is a background job, we don't need to return anything.
		return

	# Handle the non-streaming (blocking) case for other potential integrations
	final_response_text, tool_calls_log = process_response_stream(response_stream)
	final_response_text = _linkify_erpnext_docs(final_response_text)

	# If tools were called, log the complete trace for debugging.
	if tool_calls_log:
		log_entry = {
			"source": "Gemini Tool Call Trace",
			"tool_calls": tool_calls_log,
			"final_response": final_response_text,
		}
		frappe.log_error(
			message=json.dumps(log_entry, indent=2, default=str),
			title="Gemini Tool Call Trace",
		)

	# The concept of "thoughts" from the old MCP implementation doesn't directly map.
	# We will create a placeholder for now.
	thoughts = "The model generated a response, potentially after using tools."

	# 6. Save the conversation by appending the latest user prompt and model response
	# to the history before saving.
	conversation_history.append({"role": "user", "text": prompt})

	gemini_response_message = {"role": "gemini", "text": final_response_text}
	if image_url:
		gemini_response_message["image_url"] = image_url
	conversation_history.append(gemini_response_message)

	conversation_id = save_conversation(conversation_id, prompt, conversation_history)

	final_return_payload = {
		"response": final_response_text,
		"thoughts": thoughts,
		"conversation_id": conversation_id,
	}
	if image_url:
		final_return_payload["image_url"] = image_url

	return final_return_payload


def save_conversation(conversation_id, title, conversation, user=None):
	"""Saves or updates a conversation in the database.

	Args:
	    conversation_id (str): The ID of the conversation to update, or None to create a new one.
	    title (str): The title of the conversation.
	    conversation (list): The list of conversation entries.
	    user (str, optional): The user to assign the conversation to if creating a new one.
	        Defaults to the current session user.

	Returns:
	    str: The name of the saved conversation document.
	"""
	if not conversation_id:
		# Create a new conversation
		doc = frappe.new_doc("Gemini Conversation")
		doc.title = title[:140]
		doc.user = user or frappe.session.user
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

def _get_text_chunks(text, chunk_size=1000, overlap=100):
	"""Splits text into chunks of a specified size with overlap."""
	if not text:
		return []
	# Simple whitespace tokenizer
	tokens = text.split()
	chunks = []
	for i in range(0, len(tokens), chunk_size - overlap):
		chunks.append(" ".join(tokens[i : i + chunk_size]))
	return chunks


def update_embedding(doc, method):
	"""
	Creates or updates the embedding for a document. This will be called by the on_update hook.
	"""
	# This function will now just enqueue the background job
	try:
		# When a document is updated, we need to clear out all the old chunks
		# and regenerate them. The background job will handle the creation.
		# We'll just delete the existing ones here.
		existing_embeddings = frappe.get_all(
			"Gemini Embedding",
			filters={"ref_doctype": doc.doctype, "ref_docname": doc.name},
			pluck="name",
		)
		for embedding_name in existing_embeddings:
			frappe.delete_doc("Gemini Embedding", embedding_name, ignore_permissions=True)

		frappe.enqueue(
			"gemini_integration.gemini.generate_embedding_in_background",
			doctype=doc.doctype,
			docname=doc.name,
		)
	except Exception as e:
		frappe.log_error(
			message=f"Failed to enqueue embedding generation for {doc.doctype} {doc.name}: {e!s}\n{frappe.get_traceback()}",
			title="Gemini Embedding Enqueue Error",
		)


def delete_embeddings_for_doc(doc, method):
	"""
	Deletes all embedding chunks for a document when it is deleted.
	"""
	# This function will now just enqueue the background job
	frappe.enqueue(
		"gemini_integration.gemini.delete_embedding_in_background",
		doctype=doc.doctype,
		docname=doc.name,
	)


def generate_embedding_in_background(doctype, docname):
	"""
	Generates and saves an embedding for a specific document in the background.
	This now handles chunking the document and creating multiple embedding documents.

	Args:
		doctype (str): The DocType of the document.
		docname (str): The name/ID of the document.
	"""
	try:
		# 1. Get the content of the source document
		source_doc = frappe.get_doc(doctype, docname)
		content_to_embed = f"Document: {docname}\n"
		for field, value in source_doc.as_dict().items():
			if value and not isinstance(value, (list, dict, type(None))):
				content_to_embed += f"{frappe.unscrub(field)}: {value}\n"

		# 2. Split the content into chunks
		chunks = _get_text_chunks(content_to_embed)

		# 3. Generate an embedding for each chunk and save it as a new document
		for i, chunk in enumerate(chunks):
			embedding_vector = generate_embedding(chunk)
			if embedding_vector:
				embedding_doc = frappe.new_doc("Gemini Embedding")
				embedding_doc.ref_doctype = doctype
				embedding_doc.ref_docname = docname
				embedding_doc.chunk_number = i
				embedding_doc.content = chunk
				embedding_doc.embedding = json.dumps(embedding_vector)
				embedding_doc.status = "Completed"
				embedding_doc.insert(ignore_permissions=True)
			else:
				# Log an error for this specific chunk
				frappe.log_error(
					message=f"Failed to generate embedding for chunk {i} of {doctype} {docname}",
					title="Gemini Chunk Embedding Error",
				)

	except Exception as e:
		frappe.log_error(
			message=f"Failed to generate embedding for {doctype} {docname}: {e!s}\n{frappe.get_traceback()}",
			title="Gemini Embedding Generation Error",
		)


def delete_embedding_in_background(doctype, docname):
	"""
	Deletes the embedding for a document in the background.
	"""
	try:
		embedding_docs = frappe.get_all(
			"Gemini Embedding",
			filters={"ref_doctype": doctype, "ref_docname": docname},
			pluck="name",
		)
		for embedding_name in embedding_docs:
			frappe.delete_doc("Gemini Embedding", embedding_name, ignore_permissions=True)
	except Exception as e:
		frappe.log_error(
			message=f"Failed to delete embedding for {doctype} {docname}: {e!s}\n{frappe.get_traceback()}",
			title="Gemini Embedding Deletion Error",
		)

def backfill_embeddings():
	"""
	Iterates through specified DocTypes and generates embeddings for each document.
	This is triggered manually and bypasses the `save` method to avoid validation errors.
	"""
	try:
		settings = frappe.get_single("Gemini Settings")
		doctypes_to_embed = [link.doctype_name for link in settings.get("embedding_doctypes", [])]

		if not doctypes_to_embed:
			frappe.log_info("No DocTypes configured for embedding in Gemini Settings.", "Gemini Integration")
			return

		for doctype in doctypes_to_embed:
			if not frappe.db.exists("DocType", doctype):
				frappe.log_error(f"DocType '{doctype}' configured for embedding does not exist.", "Gemini Integration")
				continue

			documents = frappe.get_all(doctype, fields=["name"])
			for doc_info in documents:
				docname = doc_info.name
				try:
					# 1. Delete existing embeddings for the document
					existing_embeddings = frappe.get_all(
						"Gemini Embedding",
						filters={"ref_doctype": doctype, "ref_docname": docname},
						pluck="name",
					)
					for embedding_name in existing_embeddings:
						frappe.delete_doc("Gemini Embedding", embedding_name, ignore_permissions=True)

					# 2. Enqueue the generation of new embeddings
					frappe.enqueue(
						"gemini_integration.gemini.generate_embedding_in_background",
						doctype=doctype,
						docname=docname,
					)
					frappe.log_info(f"Successfully enqueued embedding generation for {doctype} - {docname}", "Gemini Embedding Backfill")

				except Exception as e:
					frappe.log_error(
						message=f"Failed to process document {docname} of doctype {doctype}: {e!s}\n{frappe.get_traceback()}",
						title="Gemini Embedding Backfill Error",
					)

		frappe.publish_realtime(
			"embedding_backfill_complete",
			{"message": "Successfully generated embeddings for all configured DocTypes."},
			user=frappe.session.user,
		)

	except Exception as e:
		error_message = f"An error occurred during the embedding backfill process: {e!s}"
		frappe.log_error(
			message=f"{error_message}\n{frappe.get_traceback()}",
			title="Gemini Embedding Backfill Failed",
		)
		frappe.publish_realtime(
			"embedding_backfill_failed",
			{"error": "An error occurred during the embedding backfill. Please check the Error Log for details."},
			user=frappe.session.user,
		)
