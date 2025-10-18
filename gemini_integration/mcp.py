#
#  Copyright © 2024-2025th Sapphire Fountains.
#  See LICENSE for licensing details.

import json

import frappe

from gemini_integration.gemini import generate_chat_response


@frappe.whitelist(allow_guest=True)
def handle_request():
	"""
	Handles MCP requests according to the Streamable HTTP transport specification.
	This single endpoint manages all MCP communication.
	"""
	# Log the request details for debugging
	request_method = frappe.request.method
	# full_path = frappe.request.full_path
	# headers = frappe.request.headers
	# frappe.log_error(f"MCP Request: {request_method} {full_path}", f"MCP Endpoint\nHeaders:\n{headers}")

	if request_method == "POST":
		# Client is sending a message to the server.
		return handle_post_request()
	elif request_method == "GET":
		# Client is listening for messages from the server.
		return handle_get_request()
	else:
		# Method not allowed
		frappe.throw(f"Method {request_method} not allowed.", frappe.PermissionError)


def handle_post_request():
	"""Handles incoming POST requests from the client."""
	try:
		mcp_message = json.loads(frappe.request.get_data())
	except json.JSONDecodeError:
		frappe.throw("Invalid JSON in request body.", frappe.ValidationError)

	# Use a dispatch table to handle different MCP methods
	mcp_method_handler = {
		"initialize": handle_initialize_request,
		"chat": handle_chat_request,
	}

	handler = mcp_method_handler.get(mcp_message.get("method"))

	if handler:
		return handler(mcp_message)
	else:
		# If the method is unknown, return a JSON-RPC error
		return {
			"jsonrpc": "2.0",
			"id": mcp_message.get("id"),
			"error": {"code": -32601, "message": f"Method not found: {mcp_message.get('method')}"},
		}


def handle_initialize_request(message):
	"""
	Handles the 'initialize' request from the MCP client.
	Creates a new conversation session and returns the session ID.
	"""
	# Create a new "Gemini Conversation" to represent the MCP session
	conversation_doc = frappe.new_doc("Gemini Conversation")
	conversation_doc.title = "MCP Session"
	conversation_doc.user = frappe.session.user or "Guest"  # Handle guest users
	conversation_doc.save(ignore_permissions=True)
	frappe.db.commit()

	session_id = conversation_doc.name

	# Set the Mcp-Session-Id header in the response
	frappe.local.response.headers["Mcp-Session-Id"] = session_id

	# According to MCP spec, the result of 'initialize' is an object
	# that includes the protocol version and information about the server.
	initialize_result = {
		"protocol_version": "2025-06-18",  # The version of MCP we support
		"server_info": {
			"name": "Frappe Gemini Integration",
			# You can add more server details here if needed
		},
	}

	# Return a JSON-RPC response
	return {"jsonrpc": "2.0", "id": message.get("id"), "result": initialize_result}


def handle_chat_request(message):
	"""
	Handles the 'chat' request from the MCP client.
	"""
	params = message.get("params", {})
	prompt = params.get("prompt")
	selected_options = params.get("selected_options")
	conversation_id = frappe.request.headers.get("Mcp-Session-Id")

	if not prompt and not selected_options:
		return {
			"jsonrpc": "2.0",
			"id": message.get("id"),
			"error": {
				"code": -32602,
				"message": "Invalid params: 'prompt' or 'selected_options' is required.",
			},
		}

	# Call the existing chat logic
	response_data = generate_chat_response(
		prompt=prompt,
		conversation_id=conversation_id,
		selected_options=json.dumps(selected_options) if selected_options else None,
	)

	if response_data.get("clarification_needed"):
		# The server needs to ask the user for more information.
		# This is done by sending a request to the client.
		# We will need to implement a way to send messages to the client.
		# For now, we will return a special response that the client can handle.
		return {
			"jsonrpc": "2.0",
			"id": message.get("id"),
			"result": {
				"clarification_needed": True,
				"options": response_data.get("options"),
				"response": response_data.get("response"),
			},
		}
	else:
		# The server has a final response.
		return {
			"jsonrpc": "2.0",
			"id": message.get("id"),
			"result": {"response": response_data.get("response")},
		}


def handle_get_request():
	"""Handles incoming GET requests, primarily for establishing SSE streams."""
	# This is where the server would initiate a Server-Sent Events (SSE) stream.
	# For now, we'll return a placeholder response.
	# In a real implementation, this would return a streaming response.
	return {"status": "ready_for_sse", "message": "SSE stream not yet implemented."}
