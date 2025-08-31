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

        frappe.log_error(f"Gemini API Error: {str(e)}", "Gemini Integration Error")
        frappe.throw("An error occurred while communicating with the Gemini API. Please check the Error Log for details.")

def get_doc_context(doctype, docname):
    """Fetches and formats a document's data for context."""
    try:
        doc = frappe.get_doc(doctype, docname)
        doc_dict = doc.as_dict()
        context = f"Context for {doctype} '{docname}':\n"
        for field, value in doc_dict.items():
            if value and not isinstance(value, list): # Exclude child tables for brevity
                context += f"- {field}: {value}\n"
        
        doc_url = get_url_to_form(doctype, docname)
        context += f"\nLink: {doc_url}"
        return context
    except frappe.DoesNotExistError:
        return f"(System: Document '{docname}' of type '{doctype}' not found.)\n"
    except Exception as e:
        frappe.log_error(f"Error fetching doc context: {str(e)}")
        return f"(System: Could not retrieve context for {doctype} {docname}.)\n"

def get_dynamic_doctype_map():
    """
    Builds a map of naming series prefixes to DocTypes by querying the database
    and caches the result for one hour.
    e.g., {"PROJ": "Project", "SO": "Sales Order"}
    """
    cache_key = "gemini_doctype_prefix_map"
    doctype_map = frappe.cache().get_value(cache_key)
    if doctype_map:
        return doctype_map

    doctype_map = {}
    # Find DocTypes that use a naming series format by parsing their 'autoname' property.
    all_doctypes = frappe.get_all("DocType", fields=["name", "autoname"])

    for doc in all_doctypes:
        autoname = doc.get("autoname")
        if not autoname or not isinstance(autoname, str):
            continue

        # Simple parsing: extract the prefix before the first separator.
        # This covers formats like 'PREFIX-.#####', 'PREFIX./.YYYY./.MM.-.#####', etc.
        match = re.match(r'^([A-Z_]+)[\-./]', autoname, re.IGNORECASE)
        if match:
            prefix = match.group(1).upper()
            doctype_map[prefix] = doc.name

    # Add common hardcoded fallbacks and merge them with the dynamic map.
    # The dynamic map will overwrite these if prefixes are the same, which is desired.
    hardcoded_map = {
        "PROJ": "Project", "PRJ": "Project",
        "SO": "Sales Order", "PO": "Purchase Order",
        "QUO": "Quotation", "SI": "Sales Invoice", "PI": "Purchase Invoice",
        "CUST": "Customer", "SUPP": "Supplier", "ITEM": "Item"
    }
    hardcoded_map.update(doctype_map)
    doctype_map = hardcoded_map

    frappe.cache().set_value(cache_key, doctype_map, expires_in_sec=3600) # Cache for 1 hour
    return doctype_map

@frappe.whitelist()
def generate_chat_response(prompt, model=None, conversation=None):
    """Handles chat interactions, including document references."""
    
    references = re.findall(r'@([a-zA-Z0-9\s-]+)|@"([^"]+)"', prompt)
    full_context = ""
    doc_names = [item for tpl in references for item in tpl if item]

    # Get the dynamically generated and cached map of prefixes to DocTypes
    doctype_map = get_dynamic_doctype_map()

    for docname in doc_names:
        found_doctype = None
        
        # 1. Try prefix-based matching using our dynamic map
        try:
            # Check for a hyphen, which is typical for series-based names
            if '-' in docname:
                prefix = docname.split('-')[0].upper()
                mapped_doctype = doctype_map.get(prefix)
                if mapped_doctype and frappe.db.exists(mapped_doctype, docname):
                    found_doctype = mapped_doctype
        except Exception:
            pass # Ignore errors if splitting fails, etc.

        # 2. If no prefix match, check a list of common doctypes by full name
        if not found_doctype:
            common_doctypes_to_check = ["Customer", "Supplier", "Item", "Project", "Lead", "Opportunity"]
            for dt in common_doctypes_to_check:
                if frappe.db.exists(dt, docname):
                    found_doctype = dt
                    break
        
        # 3. Add context or a failure message
        if found_doctype:
            full_context += get_doc_context(found_doctype, docname) + "\n\n"
        else:
            system_message = f"(System: Could not find any document with the name '{docname}'.)\n"
            full_context += system_message
            frappe.log_error(f"Could not find a document for reference: {docname}", "Gemini Chat Debug")

    final_prompt = f"{full_context}User query: {prompt}"
    
    return generate_text(final_prompt, model)
