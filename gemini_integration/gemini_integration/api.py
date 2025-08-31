import frappe
from gemini_integration.gemini import (
    generate_text,
    generate_chat_response,
    generate_tasks,
    analyze_risks,
    get_google_auth_url,
    process_google_callback,
    is_google_integrated
)

@frappe.whitelist()
def generate(prompt, model=None):
    """Endpoint for simple text generation."""
    return generate_text(prompt, model)

@frappe.whitelist()
def chat(prompt=None, model=None, conversation=None):
    """Endpoint for the main chat functionality."""
    if not prompt:
        frappe.throw("A prompt is required.")
    return generate_chat_response(prompt, model, conversation)

@frappe.whitelist()
def get_project_tasks(project_id, template):
    """Endpoint for generating tasks for a project."""
    return generate_tasks(project_id, template)

@frappe.whitelist()
def get_project_risks(project_id):
    """Endpoint for analyzing risks for a project."""
    return analyze_risks(project_id)

@frappe.whitelist()
def get_auth_url():
    """Gets the Google OAuth 2.0 authorization URL."""
    return get_google_auth_url()

@frappe.whitelist(allow_guest=True)
def handle_google_callback(code=None, state=None, error=None):
    """Handles the callback from Google after user consent."""
    process_google_callback(code, state, error)

@frappe.whitelist()
def check_google_integration():
    """Checks if the current user has integrated their Google account."""
    return is_google_integrated()
