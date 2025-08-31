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

# --- GEMINI API CONFIGURATION AND BASIC GENERATION ---

def configure_gemini():
    """Configures the Google Generative AI client with the API key from settings."""
    settings = frappe.get_single("Gemini Settings")
    api_key = settings.get_password('api_key')
    if not api_key:
        frappe.log_error("Gemini API Key not found in Gemini Settings.", "Gemini Integration")
        return None
    try:
        genai.configure(api_key=api_key)
        return True
    except Exception as e:
        frappe.log_error(f"Failed to configure Gemini: {str(e)}", "Gemini Integration")
        return None

def generate_text(prompt, model_name=None):
    """Generates text using a specified Gemini model."""
    if not configure_gemini():
        frappe.throw("Gemini integration is not configured. Please set the API Key in Gemini Settings.")

    if not model_name:
        model_name = frappe.db.get_single_value("Gemini Settings", "default_model") or "gemini-1.5-flash"
    
    try:
        model_instance = genai.GenerativeModel(model_name)
        response = model_instance.generate_content(prompt)
        return response.text
    except Exception as e:
        frappe.log_error(f"Gemini API Error: {str(e)}", "Gemini Integration")
        frappe.throw("An error occurred while communicating with the Gemini API. Please check the Error Log for details.")

# --- DYNAMIC DOCTYPE REFERENCING (@DOC-NAME) ---

def get_doctype_map_from_naming_series():
    """Dynamically builds a map of naming series prefixes to DocTypes."""
    dt_with_series = frappe.get_all("DocType", filters={"naming_rule": "By Naming Series"}, fields=["name"])
    doctype_map = {}
    for d in dt_with_series:
        naming_series = frappe.get_meta(d.name).get_field("naming_series").options
        if naming_series:
            prefixes = [s.strip().split('.')[0] for s in naming_series.split('\n') if s.strip()]
            for prefix in prefixes:
                doctype_map[prefix.upper()] = d.name
    return doctype_map

def get_cached_doctype_map():
    """Caches the DocType naming series map for 1 hour."""
    cache_key = "gemini_doctype_map"
    cached_map = frappe.cache().get_value(cache_key)
    if not cached_map:
        cached_map = get_doctype_map_from_naming_series()
        frappe.cache().set_value(cache_key, cached_map, expires_in_sec=3600)
    return cached_map

def get_doc_context(prompt):
    """Finds @-references in a prompt and fetches the document content."""
    doc_references = re.findall(r'@([\w\s.-]+)', prompt)
    if not doc_references:
        return "", prompt

    doctype_map = get_cached_doctype_map()
    context = ""
    
    for doc_name in doc_references:
        doc_name = doc_name.strip()
        found_doc = False
        # Iterate through the known prefixes to find a match
        for prefix, doctype in doctype_map.items():
            # Check if the doc_name starts with the prefix (e.g., "SO-")
            if doc_name.upper().startswith(prefix.upper() + '-'):
                if frappe.db.exists(doctype, doc_name):
                    doc = frappe.get_doc(doctype, doc_name)
                    doc_data = doc.as_dict()
                    context += f"\n\nContext for document '{doc_name}' (Type: {doctype}):\n"
                    context += json.dumps(doc_data, indent=2, default=str)
                    form_url = get_url_to_form(doctype, doc_name)
                    context += f"\nLink to document: {form_url}"
                    found_doc = True
                    break # Stop searching for prefixes once found
        
        if not found_doc:
            context += f"\n\n[System Note: Document '{doc_name}' could not be found or its prefix is not a recognized Naming Series prefix.]"
            
    clean_prompt = re.sub(r'@([\w\s.-]+)', '', prompt).strip()
    return context, clean_prompt

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
    return Flow.from_client_config(client_secrets, scopes=scopes, redirect_uri=redirect_uri)

def get_google_auth_url():
    """Generates the authorization URL for the user to click."""
    flow = get_google_flow()
    authorization_url, state = flow.authorization_url(access_type='offline', prompt='consent')
    frappe.cache().set_value(f"google_oauth_state_{frappe.session.user}", state, expires_in_sec=600)
    return authorization_url

def process_google_callback(code, state, error):
    """Exchanges the authorization code for tokens and stores them."""
    if error:
        frappe.log_error(f"Google OAuth Error: {error}", "Gemini Integration")
        frappe.respond_as_web_page("Google Authentication Failed", f"An error occurred: {error}", http_status_code=401)
        return

    cached_state = frappe.cache().get_value(f"google_oauth_state_{frappe.session.user}")
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

        if frappe.db.exists("Google User Token", {"user": frappe.session.user}):
            token_doc = frappe.get_doc("Google User Token", {"user": frappe.session.user})
        else:
            token_doc = frappe.new_doc("Google User Token")
            token_doc.user = frappe.session.user

        token_doc.google_email = google_email
        token_doc.access_token = creds.token
        if creds.refresh_token:
            token_doc.refresh_token = creds.refresh_token
        token_doc.scopes = " ".join(creds.scopes) if creds.scopes else ""
        token_doc.save(ignore_permissions=True)
        frappe.db.commit()

    except Exception as e:
        frappe.log_error(str(e), "Gemini Google Callback")
        frappe.respond_as_web_page("Error", "An unexpected error occurred while saving your credentials.", http_status_code=500)
        return

    frappe.respond_as_web_page(
        "Successfully Connected!",
        """<div style='text-align: center; padding: 40px;'>
              <h2>Your Google Account has been successfully connected.</h2>
              <p>You can now close this tab and return to the Gemini Chat page in ERPNext.</p>
           </div>""",
        indicator_color="green"
    )

def is_google_integrated():
    """Checks if a valid token exists for the current user."""
    return frappe.db.exists("Google User Token", {"user": frappe.session.user})

def get_user_credentials():
    """Retrieves stored credentials for the current user."""
    if not is_google_integrated():
        return None
    try:
        token_doc = frappe.get_doc("Google User Token", {"user": frappe.session.user})
        return Credentials(
            token=token_doc.access_token,
            refresh_token=token_doc.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=get_google_settings().client_id,
            client_secret=get_google_settings().get_password('client_secret'),
            scopes=token_doc.scopes.split(" ") if token_doc.scopes else []
        )
    except Exception as e:
        frappe.log_error(f"Could not get user credentials: {e}", "Gemini Integration")
        return None

# --- GOOGLE SERVICE SEARCH FUNCTIONS ---
def search_gmail(credentials, query):
    """Searches user's Gmail and returns a context string."""
    try:
        service = build('gmail', 'v1', credentials=credentials)
        results = service.users().messages().list(userId='me', q=query, maxResults=5).execute()
        messages = results.get('messages', [])
        
        email_context = "Recent emails matching the query:\n"
        if not messages:
            return "No recent emails found matching the query."
            
        for msg in messages:
            msg_data = service.users().messages().get(userId='me', id=msg['id'], format='metadata', metadataHeaders=['From', 'Subject', 'Date']).execute()
            headers = {h['name']: h['value'] for h in msg_data['payload']['headers']}
            email_context += f"- From: {headers.get('From')}, Subject: {headers.get('Subject')}, Date: {headers.get('Date')}\n"
        return email_context
    except HttpError as error:
        return f"An error occurred with Gmail: {error}"

def search_drive(credentials, query):
    """Searches user's Google Drive and returns a context string."""
    try:
        service = build('drive', 'v3', credentials=credentials)
        results = service.files().list(
            q=f"fullText contains '{query}'",
            pageSize=5,
            fields="nextPageToken, files(id, name, webViewLink)"
        ).execute()
        items = results.get('files', [])

        if not items:
            return "No files found in Google Drive matching the query."
        
        drive_context = "Recent files from Google Drive matching the query:\n"
        for item in items:
            drive_context += f"- Name: {item['name']}, Link: {item['webViewLink']}\n"
        return drive_context
    except HttpError as error:
        return f"An error occurred with Google Drive: {error}"

def search_calendar(credentials, query):
    """Searches user's Google Calendar for future events and returns a context string."""
    try:
        service = build('calendar', 'v3', credentials=credentials)
        now = datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(
            calendarId='primary',
            q=query,
            timeMin=now,
            maxResults=5,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        if not events:
            return "No upcoming calendar events found matching the query."
        
        calendar_context = "Upcoming calendar events matching the query:\n"
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            calendar_context += f"- Summary: {event['summary']}, Start: {start}\n"
        return calendar_context
    except HttpError as error:
        return f"An error occurred with Google Calendar: {error}"


# --- MAIN CHAT FUNCTIONALITY ---
def generate_chat_response(prompt, model=None, conversation=None, file_url=None):
    """Main function to handle chat, including document and Google context."""
    system_instruction = frappe.db.get_single_value("Gemini Settings", "system_instruction")
    erpnext_context, clean_prompt = get_doc_context(prompt)
    google_context = ""
    
    if is_google_integrated():
        creds = get_user_credentials()
        if creds:
            if re.search(r'\b(email|mail|gmail)\b', clean_prompt.lower()):
                search_term = clean_prompt
                google_context += search_gmail(creds, search_term)
            if re.search(r'\b(drive|file|doc|document|sheet|slide)\b', clean_prompt.lower()):
                search_term = clean_prompt
                google_context += search_drive(creds, search_term)
            if re.search(r'\b(calendar|event|meeting)\b', clean_prompt.lower()):
                search_term = clean_prompt
                google_context += search_calendar(creds, search_term)

    final_prompt = ""
    if system_instruction:
        final_prompt += f"System Instruction: {system_instruction}\n\n"

    final_prompt += f"User query: {clean_prompt}\n"

    if erpnext_context:
        final_prompt += f"\n--- ERPNext Data Context ---\n{erpnext_context}\n"
    if google_context:
        final_prompt += f"\n--- Google Workspace Data Context ---\n{google_context}\n"
    
    final_prompt += "\nBased on the user query and any provided context, please provide a helpful and comprehensive response."
    
    # Handle file attachments for vision model
    if file_url:
        try:
            file_doc = frappe.get_doc("File", {"file_url": file_url})
            file_path = file_doc.get_full_path()
            
            import mimetypes
            mime_type, _ = mimetypes.guess_type(file_path)
            
            with open(file_path, "rb") as f:
                image_part = {
                    "mime_type": mime_type,
                    "data": f.read()
                }
            
            model_instance = genai.GenerativeModel('gemini-1.5-flash')
            response = model_instance.generate_content([final_prompt, image_part])
            return response.text

        except Exception as e:
            frappe.log_error(f"Error processing file attachment: {e}", "Gemini Integration")
            return "Sorry, I encountered an error processing the attached file."

    return generate_text(final_prompt, model)


# --- PROJECT-SPECIFIC FUNCTIONS ---
def generate_tasks(project_id, template):
    """Generates a list of tasks for a project using Gemini."""
    if not frappe.db.exists("Project", project_id):
        return {"error": "Project not found."}
    
    project = frappe.get_doc("Project", project_id)
    project_details = project.as_dict()
    
    prompt = f"""
    Based on the following project details and the selected template '{template}', generate a list of tasks.
    Project Details: {json.dumps(project_details, indent=2, default=str)}
    
    Please return ONLY a valid JSON list of objects. Each object should have two keys: "subject" and "description".
    Example: [{"subject": "Initial client meeting", "description": "Discuss project scope and deliverables."}, ...]
    """
    
    response_text = generate_text(prompt)
    try:
        tasks = json.loads(response_text)
        return tasks
    except json.JSONDecodeError:
        return {"error": "Failed to parse a valid JSON response from the AI. Please try again."}

def analyze_risks(project_id):
    """Analyzes a project for potential risks using Gemini."""
    if not frappe.db.exists("Project", project_id):
        return {"error": "Project not found."}
    
    project = frappe.get_doc("Project", project_id)
    project_details = project.as_dict()
    
    prompt = f"""
    Analyze the following project for potential risks (e.g., timeline, budget, scope creep, resource constraints).
    Project Details: {json.dumps(project_details, indent=2, default=str)}
    
    Please return ONLY a valid JSON list of objects. Each object should have two keys: "risk_name" (a short title) and "risk_description".
    Example: [{"risk_name": "Scope Creep", "risk_description": "The project description is vague, which could lead to additional client requests not in the original scope."}, ...]
    """
    
    response_text = generate_text(prompt)
    try:
        risks = json.loads(response_text)
        return risks
    except json.JSONDecodeError:
        return {"error": "Failed to parse a valid JSON response from the AI. Please try again."}
