import frappe
import google.generativeai as genai
from frappe.utils import get_url_to_form, get_site_url
import re
import json
from datetime import datetime, timedelta

# Google API Imports
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- OAUTH AND GOOGLE API FUNCTIONS ---

def get_google_settings():
    """Retrieves Google settings from Social Login Keys."""
    settings = frappe.get_doc("Social Login Key", "Google")
    if not settings or not settings.enable_social_login:
        frappe.throw("Google Login is not enabled in Social Login Keys.")
    return settings

def get_google_flow():
    """Builds the Google OAuth 2.0 Flow object."""
    settings = get_google_settings()
    redirect_uri = get_site_url(frappe.local.site) + "/api/method/gemini_integration.api.handle_google_callback"
    client_secrets = {
        "web": {
            "client_id": settings.client_id,
            "client_secret": settings.get_password('client_secret'),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    scopes = [
        "https://www.googleapis.com/auth/userinfo.email", "openid",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/calendar.readonly",
    ]
    return Flow.from_client_secrets_dictionary(client_secrets, scopes=scopes, redirect_uri=redirect_uri)

def get_google_auth_url():
    """Generates the authorization URL for the user to click."""
    flow = get_google_flow()
    authorization_url, state = flow.authorization_url(access_type='offline', prompt='consent')
    frappe.cache().set(f"google_oauth_state_{frappe.session.user}", state, expires_in_sec=600)
    return authorization_url

def process_google_callback(code, state, error):
    """Exchanges the authorization code for tokens and stores them."""
    if error:
        frappe.log_error(f"Google OAuth Error: {error}", "Gemini Integration")
        frappe.respond_as_web_page("Google Authentication Failed", f"An error occurred: {error}", http_status_code=401)
        return

    cached_state = frappe.cache().get(f"google_oauth_state_{frappe.session.user}")
    if not cached_state or cached_state != state:
        frappe.log_error("Google OAuth State Mismatch", "Gemini Integration")
        frappe.respond_as_web_page("Authentication Failed", "State mismatch. Please try again.", http_status_code=400)
        return

    try:
        flow = get_google_flow()
        flow.fetch_token(code=code)
        creds = flow.credentials

        userinfo_service = build('oauth2', 'v2', credentials=creds)
        user_info = userinfo_service.userinfo().get().execute()
        google_email = user_info.get('email')

        # Use frappe.db.exists to check before creating/updating
        if frappe.db.exists("Google User Token", {"user": frappe.session.user}):
            token_doc = frappe.get_doc("Google User Token", {"user": frappe.session.user})
        else:
            token_doc = frappe.new_doc("Google User Token")
            token_doc.user = frappe.session.user

        token_doc.google_email = google_email
        token_doc.access_token = creds.token
        token_doc.refresh_token = creds.refresh_token
        token_doc.scopes = " ".join(creds.scopes)
        token_doc.save(ignore_permissions=True)
        frappe.db.commit()

    except Exception as e:
        frappe.log_error(str(e), "Gemini Google Callback")
        frappe.respond_as_web_page("Error", "An unexpected error occurred while saving your credentials.", http_status_code=500)
        return

    frappe.utils.redirect_to_message(
        "Successfully Connected!",
        "Your Google Account has been successfully connected. You can now close this tab and return to the Gemini Chat.",
        indicator_color="green"
    )

def is_google_integrated():
    """Checks if a valid token exists for the current user."""
    return frappe.db.exists("Google User Token", {"user": frappe.session.user})

def get_user_credentials():
    """Retrieves stored credentials for the current user."""
    if not is_google_integrated():
        return None
    token_doc = frappe.get_doc("Google User Token", {"user": frappe.session.user})
    return Credentials(
        token=token_doc.access_token,
        refresh_token=token_doc.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=get_google_settings().client_id,
        client_secret=get_google_settings().get_password('client_secret'),
        scopes=token_doc.scopes.split(" ") if token_doc.scopes else None
    )

# --- GOOGLE SERVICE SEARCH FUNCTIONS ---
# (Implementations from previous response)
# ...

# --- MAIN CHAT FUNCTION ---
@frappe.whitelist()
def generate_chat_response(prompt, model=None, conversation=None, file_url=None):
    """Handles chat, detects keywords to search Google, and sends context to Gemini."""
    # ... (Implementation from previous response)
    pass # Keep the full implementation here

# --- Other functions ---
# ... (Keep all your other existing functions: generate_text, analyze_risks, etc.)


