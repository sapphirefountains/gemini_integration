import frappe
import google.generativeai as genai
from frappe.utils import get_url_to_form, get_site_url
import re
import json
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- EXISTING GEMINI FUNCTIONS ---
# (configure_gemini, generate_text, etc. remain here, but may be updated below)

# --- NEW OAUTH AND GOOGLE API FUNCTIONS ---

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

    return Flow.from_client_secrets_dictionary(
        client_secrets_dict={
            "web": {
                "client_id": settings.client_id,
                "client_secret": settings.get_password('client_secret'),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "openid",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/calendar.readonly",
        ],
        redirect_uri=redirect_uri
    )

def get_google_auth_url():
    """Generates the authorization URL for the user to click."""
    flow = get_google_flow()
    authorization_url, state = flow.authorization_url(access_type='offline', prompt='consent')
    frappe.cache().set(f"google_oauth_state_{frappe.session.user}", state, expires_in_sec=600)
    return authorization_url

def handle_google_callback(code, state, error):
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

        # Get user info to link the token correctly
        userinfo_service = build('oauth2', 'v2', credentials=creds)
        user_info = userinfo_service.userinfo().get().execute()
        google_email = user_info.get('email')

        token_doc = frappe.get_doc({
            "doctype": "Google User Token",
            "user": frappe.session.user,
            "google_email": google_email,
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "scopes": " ".join(creds.scopes)
        })
        token_doc.insert(ignore_permissions=True, overwrite=True)
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

# ... (keep existing functions like configure_gemini, get_series_doctype_map, etc.)
# ... (and all other existing functions. The generate_chat_response function will be updated below)

def generate_chat_response(prompt, model=None, conversation=None, file_url=None):
    # This is a placeholder for the full function which you already have.
    # The key is to add the new logic for Google services inside it.
    frappe.log_error("generate_chat_response needs to be fully implemented with Google search logic.", "Gemini Integration")
    # For now, we'll just return a message to show the flow is working.
    if is_google_integrated():
         if "search my emails for" in prompt.lower():
            return "I am connected to your Google Account and would search your emails."
    # ... The rest of your existing chat logic would go here ...
    return "This is a placeholder response."

# ... (keep all your other existing functions: generate_text, generate_tasks, analyze_risks, etc.)

