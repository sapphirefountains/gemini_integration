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
from gemini_integration.utils import get_google_settings

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


# --- MAIN CHAT FUNCTIONALITY ---


@log_activity
@handle_errors
def generate_chat_response(prompt, model=None, conversation_id=None, use_google_search=False):
	"""Handles chat interactions by routing them to the correct MCP tools.

	Args:
	    prompt (str): The user's chat prompt.
	    model (str, optional): The model to use for the chat. Defaults to None.
	    conversation_id (str, optional): The ID of the existing conversation. Defaults to None.
	    use_google_search (bool, optional): Whether to enable Google Search for this query.
	        Defaults to False.

	Returns:
	    dict: A dictionary containing the response, thoughts, and conversation ID.
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
			"gmail": ["search_gmail"],
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

	# 2. Get user credentials if any Google services are mentioned
	kwargs = {}
	google_services = ["gmail", "drive", "calendar"]
	if any(service in mentioned_services for service in google_services):
		from gemini_integration.utils import get_user_credentials

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

	# 3. Set up the model with the dynamically selected tools.
	model_name = model or frappe.db.get_single_value("Gemini Settings", "default_model") or "gemini-2.5-pro"

	# Only add tool_config if there are tools to configure.
	if tool_declarations:
		tool_config = {"function_calling_config": {"mode": "AUTO"}}
		model_instance = genai.GenerativeModel(
			model_name, tools=tool_declarations, tool_config=tool_config
		)
	else:
		model_instance = genai.GenerativeModel(model_name)

	# The Gemini API expects a specific format for conversation history.
	# We need to transform our stored history to match this format.
	gemini_history = []
	for entry in conversation_history:
		# The role must be 'user' or 'model'. Our doctype uses 'gemini'.
		role = "model" if entry.get("role") == "gemini" else "user"
		gemini_history.append({"role": role, "parts": [entry.get("text")]})

	chat = model_instance.start_chat(history=gemini_history)

	# 4. Send the prompt and handle the response, including any tool calls
	response = chat.send_message(prompt)

	# Loop to handle multiple potential tool calls from the model
	while True:
		# Check if the model's response contains a function call.
		# This check is more robust and avoids potential IndexErrors.
		function_call = None
		if (
			response.candidates
			and response.candidates[0].content
			and response.candidates[0].content.parts
		):
			for part in response.candidates[0].content.parts:
				if part.function_call:
					function_call = part.function_call
					break  # Handle the first function call found

		if not function_call:
			# If no function call is found, this is the final response.
			break

		tool_name = function_call.name
		tool_args = {key: value for key, value in function_call.args.items()}

		# Add credentials to args if the tool requires them
		if "credentials" in kwargs:
			tool_args["credentials"] = kwargs["credentials"]

		# Execute the tool
		try:
			tool_function = mcp._tool_registry[tool_name]["fn"]
			tool_result = tool_function(**tool_args)
		except Exception:
			frappe.log_error(
				message=frappe.get_traceback(),
				title=f"Error executing tool: {tool_name}",
			)
			frappe.throw(
				f"An error occurred while executing the tool: {tool_name}. Please check the Error Log for details."
			)

		# Send the tool's result back to the model
		response = chat.send_message(
			[
				{
					"function_response": {
						"name": tool_name,
						"response": {"contents": tool_result},
					}
				}
			]
		)

	# 5. Extract the final text response and thoughts, handling potential errors
	try:
		final_response_text = response.text
	except ValueError:
		# This occurs if the response has no text part (e.g., due to safety filters
		# or a function call without a final text response).
		final_response_text = "No response from the model."
	# The concept of "thoughts" from the old MCP implementation doesn't directly map.
	# We will create a placeholder for now.
	thoughts = "The model generated a response, potentially after using tools."

	# 6. Save the conversation by appending the latest user prompt and model response
	# to the history before saving.
	conversation_history.append({"role": "user", "text": prompt})
	conversation_history.append({"role": "gemini", "text": final_response_text})
	conversation_id = save_conversation(conversation_id, prompt, conversation_history)

	return {
		"response": final_response_text,
		"thoughts": thoughts,
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
