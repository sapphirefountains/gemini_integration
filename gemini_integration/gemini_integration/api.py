import frappe
from frappe import _
from .gemini import generate_text, generate_chat_response

@frappe.whitelist()
def generate(prompt=None, model=None):
    """
    Handles sales pitch generation.
    Accepts prompt as an optional argument and validates its existence.
    """
    if not prompt:
        frappe.throw(_("The 'prompt' argument is missing. Please provide a prompt for generation."))
    return generate_text(prompt, model)

@frappe.whitelist()
def chat(prompt=None, model=None, conversation=None):
    """
    Handles chat requests.
    Accepts prompt as an optional argument and validates its existence.
    """
    if not prompt:
        frappe.throw(_("The 'prompt' argument is missing. Please provide a chat message."))
    return generate_chat_response(prompt, model, conversation)
