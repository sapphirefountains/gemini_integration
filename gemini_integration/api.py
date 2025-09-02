import frappe
from gemini_integration.utils import handle_errors, log_activity
from gemini_integration.gemini import (
    generate_text,
    generate_chat_response,
    generate_tasks,
    analyze_risks,
    get_google_auth_url,
    process_google_callback,
    is_google_integrated,
    search_google_drive,
    search_google_mail,
    get_user_credentials,
    get_drive_file_for_analysis
)

@frappe.whitelist()
@log_activity
@handle_errors
def generate(prompt, model=None):
    """Endpoint for simple text generation."""
    return generate_text(prompt, model)

@frappe.whitelist()
@log_activity
@handle_errors
def chat(prompt=None, model=None, conversation=None):
    """Endpoint for the main chat functionality."""
    if not prompt:
        frappe.throw("A prompt is required.")
    return generate_chat_response(prompt, model, conversation)

@frappe.whitelist()
@log_activity
@handle_errors
def get_project_tasks(project_id, template):
    """Endpoint for generating tasks for a project."""
    return generate_tasks(project_id, template)

@frappe.whitelist()
@log_activity
@handle_errors
def get_project_risks(project_id):
    """Endpoint for analyzing risks for a project."""
    return analyze_risks(project_id)

@frappe.whitelist()
@log_activity
@handle_errors
def get_auth_url():
    """Gets the Google OAuth 2.0 authorization URL."""
    return get_google_auth_url()

@frappe.whitelist(allow_guest=True)
@log_activity
@handle_errors
def handle_google_callback(code=None, state=None, error=None):
    """Handles the callback from Google after user consent."""
    process_google_callback(code, state, error)

@frappe.whitelist()
@log_activity
@handle_errors
def check_google_integration():
    """Checks if the current user has integrated their Google account."""
    return is_google_integrated()

@frappe.whitelist()
@log_activity
@handle_errors
def search_drive(query):
    """Endpoint for searching Google Drive."""
    creds = get_user_credentials()
    if not creds:
        frappe.throw("Google account not integrated.")
    return search_google_drive(creds, query)

@frappe.whitelist()
@log_activity
@handle_errors
def search_mail(query):
    """Endpoint for searching Google Mail."""
    creds = get_user_credentials()
    if not creds:
        frappe.throw("Google account not integrated.")
    return search_google_mail(creds, query)

@frappe.whitelist()
@log_activity
@handle_errors
def get_drive_file_for_analysis(file_id):
    """Endpoint for getting a Google Drive file for analysis."""
    creds = get_user_credentials()
    if not creds:
        frappe.throw("Google account not integrated.")
    return get_drive_file_for_analysis(creds, file_id)
