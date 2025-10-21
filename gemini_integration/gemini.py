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
	fetch_erpnext_data,
	get_doc_context,
	handle_errors,
	log_activity,
	search_calendar,
	search_drive,
	search_erpnext_documents,
	search_gmail,
	search_google_contacts,
	create_comment,
	create_task,
	update_document_status,
)
from gemini_integration.utils import configure_gemini, generate_embedding, generate_text

# --- GEMINI API CONFIGURATION AND BASIC GENERATION ---


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
		pass
# --- SERVICE TO TOOL MAPPING ---

# This dictionary maps the user-facing @-mention service to a list of tool function names.
# This makes it easy to manage which tools are exposed for each service and allows for reuse.
SERVICE_TO_TOOL_MAP = {
    "erpnext": {
        "label": "@ERPNext",
        "tools": [
            "search_erpnext_documents",
            "fetch_erpnext_data",
            "create_comment",
            "create_task",
            "update_document_status",
        ],
    },
    "google": {
        "label": "@Google",
        "tools": [
            "search_drive",
            "search_gmail",
            "search_calendar",
            "search_google_contacts",
        ],
    },
    "drive": {"label": "@Drive", "tools": ["search_drive"]},
    "gmail": {
        "label": "@Gmail",
        "tools": [
            "send_email",
            "search_gmail",
            "get_gmail_message_context",
            "modify_gmail_label",
            "delete_gmail_message",
        ],
    },
    "calendar": {"label": "@Calendar", "tools": ["search_calendar"]},
    "contacts": {"label": "@Contacts", "tools": ["search_google_contacts"]},
}


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
	"""Handles chat interactions using a Plan-Execute-Synthesize model.

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
		dict or None: A dictionary containing the response for non-streaming calls,
			or None for streaming calls (which use WebSockets).
	"""
	# --- 0. Setup and Configuration ---
	settings = frappe.get_single("Gemini Settings")
	api_key = settings.get_password("api_key")
	if not api_key:
		frappe.throw("Gemini API Key not found. Please configure it in Gemini Settings.")
	try:
		genai.configure(api_key=api_key)
	except Exception as e:
		frappe.log_error(f"Failed to configure Gemini: {e!s}", "Gemini Integration")
		frappe.throw("An error occurred during Gemini configuration. Please check the logs.")

	from gemini_integration.mcp import mcp
	from gemini_integration.utils import is_google_integrated

	model_name = model or settings.default_model or "gemini-1.5-pro"

	# Load conversation history
	conversation_history = []
	if conversation_id:
		try:
			conversation_doc = frappe.get_doc("Gemini Conversation", conversation_id)
			if conversation_doc.conversation:
				conversation_history = json.loads(conversation_doc.conversation)
		except frappe.DoesNotExistError:
			conversation_id = None

	# For streaming, ensure a conversation ID exists to send back to the client
	if stream and not conversation_id:
		conversation_id = save_conversation(None, prompt, [], user=user)
		frappe.publish_realtime("gemini_chat_update", {"conversation_id": conversation_id}, user=user)

	# --- 1. Planning Phase ---
	# Provide the model with a "menu" of all available tools.
	tool_declarations = []
	for tool_name, tool_data in mcp._tool_registry.items():
		# Sanitize the tool declaration for the Google API
		input_schema = tool_data.get("input_schema")
		if input_schema and "properties" in input_schema:
			parameters = {
				"type": "object",
				"properties": input_schema.get("properties", {}),
				"required": input_schema.get("required", []),
			}
		else:
			parameters = None

		declaration = {
			"name": tool_data.get("name"),
			"description": tool_data.get("description"),
			"parameters": parameters,
		}
		declaration = {k: v for k, v in declaration.items() if v is not None}
		if "parameters" in declaration:
			declaration["parameters"] = _uppercase_schema_types(declaration["parameters"])
		tool_declarations.append(declaration)

	if settings.enable_google_search and use_google_search:
		tool_declarations.append({"google_search": {}})

	# Craft the "Planner" instruction
	planning_instruction = """
You are a planner for an AI assistant integrated into ERPNext. Your job is to analyze the user's prompt and the list of available tools.
Break the user's request into a series of steps.
Output this plan as a valid JSON list of tool calls to be executed.
Each object in the list must have 'tool_name' and 'args' keys.
If no tools are needed for the prompt, respond with a friendly, conversational answer directly, NOT as JSON.
"""
	if doctype and docname:
		planning_instruction += f"\n\nThe user is currently viewing the document '{docname}' of type '{doctype}'. Prioritize this information when creating the plan."

	planner_model = genai.GenerativeModel(
		model_name,
		tools=tool_declarations,
		tool_config={"function_calling_config": {"mode": "ANY"}}, # Use ANY to allow for direct response or tool plan
		system_instruction=planning_instruction,
	)

	planner_chat = planner_model.start_chat()
	planner_response = planner_chat.send_message(prompt)

	# --- 2. Parse Planner Response ---
	execution_plan = None
	direct_response = False

	# Check for a direct function call first. This is the most likely alternative to a JSON plan.
	try:
		tool_call = planner_response.candidates[0].content.parts[0].function_call
		# Adapt the single tool call to the list format expected by the execution phase.
		execution_plan = [
			{
				"tool_name": tool_call.name,
				"args": {k: v for k, v in tool_call.args.items()},
			}
		]
		frappe.log(f"Planner returned a direct function call: {tool_call.name}")
	except (ValueError, IndexError, AttributeError):
		# If there's no function call, proceed to check for a JSON plan or a direct text response.
		try:
			# A valid plan is a parsable JSON string that is a non-empty list.
			execution_plan = json.loads(planner_response.text)
			if not isinstance(execution_plan, list) or not execution_plan:
				# If it's an empty list `[]` or not a list, treat it as a direct response.
				direct_response = True
				execution_plan = None
		except (json.JSONDecodeError, ValueError):
			# The response is not a valid JSON plan, so it's the final answer.
			direct_response = True
			execution_plan = None

	# If it was determined to be a direct response, handle it and exit.
	if direct_response:
		final_response_text = _linkify_erpnext_docs(planner_response.text)

		# Save the conversation history
		conversation_history.append({"role": "user", "text": prompt})
		conversation_history.append({"role": "gemini", "text": final_response_text})
		save_conversation(conversation_id, prompt, conversation_history, user=user)

		# If streaming, publish the final answer and signal the end.
		if stream:
			frappe.publish_realtime("gemini_chat_update", {"message": final_response_text}, user=user)
			frappe.publish_realtime("gemini_chat_update", {"end_of_stream": True}, user=user)
			return

		# For non-streaming, return the final payload.
		return {
			"response": final_response_text,
			"thoughts": "The model provided a direct answer without using tools.",
			"conversation_id": conversation_id,
		}

	# --- 3. Execution Phase ---
	compiled_context = []
	for step in execution_plan:
		tool_name = step.get("tool_name")
		tool_args = step.get("args", {})

		if not tool_name or not isinstance(tool_args, dict):
			# Skip malformed steps in the plan
			continue

		# Check for Google authentication if a Google tool is planned
		if tool_name in ["search_drive", "search_gmail", "search_calendar", "search_google_contacts", "send_email"]:
			if not is_google_integrated():
				compiled_context.append({
					"tool_name": tool_name,
					"status": "error",
					"result": "User has not connected their Google account.",
				})
				continue # Skip to the next tool in the plan

		try:
			# Execute the tool function
			tool_function = mcp._tool_registry[tool_name]["fn"]
			tool_result = tool_function(**tool_args)
			compiled_context.append({
				"tool_name": tool_name,
				"status": "success",
				"result": tool_result,
			})
		except Exception as e:
			frappe.log_error(
				message=f"Error executing tool '{tool_name}' from plan: {e!s}\n{frappe.get_traceback()}",
				title="Gemini Execution Phase Error",
			)
			compiled_context.append({
				"tool_name": tool_name,
				"status": "error",
				"result": f"An error occurred while running the tool: {e!s}",
			})

	# --- 4. Synthesis Phase ---
	synthesis_instruction = """
You are a helpful AI assistant integrated into ERPNext. Your goal is to provide a single, comprehensive, and user-friendly answer to the user's original question.
You will be given the user's prompt and a JSON object containing the results of a series of tool calls that were executed to gather information.
Synthesize the information from the tool results to answer the user's question.
If any tools returned an error, acknowledge the failure and inform the user what information you were unable to retrieve.
Base your answer STRICTLY on the provided tool results. Do not invent or hallucinate information.
Format your response in clear, readable Markdown.
"""

	# The Gemini API cannot handle the `decimal` type from MariaDB, so we need a custom JSON encoder.
	class CustomJSONEncoder(json.JSONEncoder):
		def default(self, obj):
			if isinstance(obj, frappe.model.document.Document):
				return obj.as_dict()
			if hasattr(obj, 'isoformat'): # Handles dates, datetimes
				return obj.isoformat()
			from decimal import Decimal
			if isinstance(obj, Decimal):
				return float(obj)
			return super().default(self, obj)

	final_prompt_content = f"""**User's Original Question:**
"{prompt}"

**Compiled Context from Tool Execution:**
```json
{json.dumps(compiled_context, indent=2, cls=CustomJSONEncoder)}
```

**Your Answer:**
"""

	synthesis_model = genai.GenerativeModel(model_name, system_instruction=synthesis_instruction)
	final_response = synthesis_model.generate_content(final_prompt_content, stream=stream)

	# --- 5. Stream or Return Final Response ---
	if stream:
		final_response_text = ""
		for chunk in final_response:
			text_chunk = chunk.text
			final_response_text += text_chunk
			frappe.publish_realtime("gemini_chat_update", {"message": text_chunk}, user=user)

		final_response_text = _linkify_erpnext_docs(final_response_text)
		conversation_history.append({"role": "user", "text": prompt})
		conversation_history.append({"role": "gemini", "text": final_response_text})
		save_conversation(conversation_id, prompt, conversation_history, user=user)
		frappe.publish_realtime("gemini_chat_update", {"end_of_stream": True}, user=user)
		return

	# Handle non-streaming case
	final_response_text = _linkify_erpnext_docs(final_response.text)
	conversation_history.append({"role": "user", "text": prompt})
	conversation_history.append({"role": "gemini", "text": final_response_text})
	save_conversation(conversation_id, prompt, conversation_history, user=user)

	return {
		"response": final_response_text,
		"thoughts": "The model generated a synthesized response based on tool results.",
		"conversation_id": conversation_id,
	}


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

def create_deal_brief_for_opportunity(doc, method):
    """
    When a new high-value Opportunity is created, trigger a hook that creates a "Deal Brief".
    """
    if doc.opportunity_amount > 5000:
        customer_details = fetch_erpnext_data(
            doctype="Customer",
            filters={"name": doc.party_name},
            fields=["name", "customer_name", "email", "phone", "mobile_no"],
        )

        customer_projects = fetch_erpnext_data(
            doctype="Project",
            filters={"customer": doc.party_name},
            fields=["name", "project_name", "status", "priority", "start_date", "end_date"],
        )

        customer_opportunities = fetch_erpnext_data(
            doctype="Opportunity",
            filters={"party_name": doc.party_name},
            fields=["name", "opportunity_from", "status", "opportunity_amount"],
        )

        gmail_history = search_gmail(query=doc.party_name)

        prompt = f"""
        Create a "Deal Brief" summarizing the following opportunity, customer history, and recent interactions.
        Opportunity: {doc.as_dict()}
        Customer Details: {customer_details}
        Customer Projects: {customer_projects}
        Customer Opportunities: {customer_opportunities}
        Recent Emails: {gmail_history}
        """

        deal_brief = generate_text(prompt)

        create_comment(
            reference_doctype="Opportunity",
            reference_name=doc.name,
            comment=deal_brief,
            confirmed=True,
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
			frappe.log("No DocTypes configured for embedding in Gemini Settings.")
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
					frappe.log(f"Successfully enqueued embedding generation for {doctype} - {docname}")

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
