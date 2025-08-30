from __future__ import unicode_literals
import frappe
from gemini_integration.gemini_integration.gemini import generate_text, generate_chat_response

@frappe.whitelist()
def generate(prompt, model=None):
    return generate_text(prompt, model)

@frappe.whitelist()
def chat(prompt, model=None, conversation=None):
    """
    Endpoint for the chat interface.
    'conversation' is a placeholder for future stateful conversation implementation.
    """
    return generate_chat_response(prompt, model, conversation)

