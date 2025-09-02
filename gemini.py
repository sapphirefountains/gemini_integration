import frappe
import google.generativeai as genai
from frappe.utils import get_url_to_form, get_site_url
import re
import json
import base64
from datetime import datetime, timedelta
from thefuzz import process

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

def get_doc_context(doctype, docname):
    """Fetches and formats a document's data for context."""
    try:
        doc = frappe.get_doc(doctype, docname)
        doc_dict = doc.as_dict()
        context = f"Context for {doctype} '{docname}':\n"
        # Loop through the document dictionary and format the data for readability.
        # Child tables (lists) are excluded for brevity.
        for field, value in doc_dict.items():
            if value and not isinstance(value, list):
                context += f"- {field}: {value}\n"
        
        doc_url = get_url_to_form(doctype, docname)
        context += f"\nLink: {doc_url}"
        return context
    except frappe.DoesNotExistError:
        # If the document is not found, try to find the best match using fuzzy search
        all_docs = frappe.get_all(doctype, fields=['name'])
        all_doc_names = [d['name'] for d in all_docs]
        
        best_match = process.extractOne(docname, all_doc_names)
        if best_match and best_match[1] > 80: # 80 is a good threshold for confidence
            return f"(System: Document '{docname}' of type '{doctype}' not found. Did you mean '{best_match[0]}'?)\n"
        else:
            return f"(System: Document '{docname}' of type '{doctype}' not found.)\n"
    except Exception as e:
        frappe.log_error(f"Error fetching doc context: {str(e)}")
        return f"(System: Could not retrieve context for {doctype} {docname}.)\n"

def get_dynamic_doctype_map():
    """Builds and caches a map of naming series prefixes to DocTypes (e.g., {"PRJ": "Project"}).
    
    This is used to quickly identify the DocType of a referenced document ID.
    It combines dynamically found prefixes with a hardcoded list for common cases.
    """
    cache_key = "gemini_doctype_prefix_map"
    doctype_map = frappe.cache().get_value(cache_key)
    if doctype_map:
        return doctype_map

    doctype_map = {}
    all_doctypes = frappe.get_all("DocType", fields=["name", "autoname"])

    # Dynamically build the map from DocType autoname properties
    for doc in all_doctypes:
        autoname = doc.get("autoname")
        if not autoname or not isinstance(autoname, str):
            continue
        
        match = re.match(r'^([A-Z_]+)[\-./]', autoname, re.IGNORECASE)
        if match:
            prefix = match.group(1).upper()
            doctype_map[prefix] = doc.name

    # Add a hardcoded map as a fallback for common or non-standard naming series.
    # The dynamic map takes precedence.
    hardcoded_map = {
        "PRJ": "Project", "PROJ": "Project", "TASK": "Task",
        "SO": "Sales Order", "PO": "Purchase Order", "QUO": "Quotation",
        "SI": "Sales Invoice", "PI": "Purchase Invoice", "CUST": "Customer",
        "SUPP": "Supplier", "ITEM": "Item", "LEAD": "Lead", "OPP": "Opportunity"
    }
    hardcoded_map.update(doctype_map)
    doctype_map = hardcoded_map

    frappe.cache().set_value(cache_key, doctype_map, expires_in_sec=3600) # Cache for 1 hour
    return doctype_map

# --- OAUTH AND GOOGLE API FUNCTIONS ---

def get_google_settings():
    """Retrieves Google settings from Social Login Keys."""
    settings = frappe.get_doc("Social Login Key", "Google")
    if not settings or not settings.enable_social_login:
        frappe.throw("Google Login is not enabled in Social Login Keys.")
    return settings

def get_google_flow():
    """Builds the Google OAuth 2.0 Flow object for authentication."""
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
    # Scopes define the level of access to the user's Google data.
    scopes = [
        "https://www.googleapis.com/auth/userinfo.email", "openid",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/calendar.readonly",
    ]
    return Flow.from_client_config(client_secrets, scopes=scopes, redirect_uri=redirect_uri)

def get_google_auth_url():
    """Generates the authorization URL for the user to grant consent."""
    flow = get_google_flow()
    authorization_url, state = flow.authorization_url(access_type='offline', prompt='consent')
    # Store the state in cache to prevent CSRF attacks.
    frappe.cache().set_value(f"google_oauth_state_{frappe.session.user}", state, expires_in_sec=600)
    return authorization_url

def process_google_callback(code, state, error):
    """Handles the OAuth callback from Google, exchanges the code for tokens, and stores them."""
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

        # Get user's email to store alongside the token for reference.
        userinfo_service = build('oauth2', 'v2', credentials=creds)
        user_info = userinfo_service.userinfo().get().execute()
        google_email = user_info.get('email')

        # Create or update the Google User Token document for the current user.
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

    # Show a success page to the user.
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
    """Retrieves stored credentials for the current user from the database."""
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

# --- GOOGLE SERVICE-SPECIFIC FUNCTIONS ---

def search_gmail(credentials, query):
    """Searches Gmail for a query and returns message subjects and snippets."""
    try:
        service = build('gmail', 'v1', credentials=credentials)
        
        if query.strip():
            search_query = f'"{query}" in:anywhere'
        else:
            search_query = 'in:inbox'
        
        results = service.users().messages().list(userId='me', q=search_query, maxResults=5).execute()
        messages = results.get('messages', [])
        
        email_context = "Recent emails matching your query:\n"
        if not messages:
            return "No recent emails found matching your query."

        batch = service.new_batch_http_request()
        email_data = {}

        def create_callback(msg_id):
            def callback(request_id, response, exception):
                if exception:
                    frappe.log_error(f"Gmail batch callback error for msg {msg_id}: {exception}", "Gemini Gmail Error")
                else:
                    email_data[msg_id] = response
            return callback

        for msg in messages:
            msg_id = msg['id']
            batch.add(
                service.users().messages().get(userId='me', id=msg_id, format='metadata', metadataHeaders=['Subject']),
                callback=create_callback(msg_id)
            )
        
        batch.execute()

        for msg in messages:
            msg_id = msg['id']
            msg_data = email_data.get(msg_id)
            if msg_data:
                subject = next((h['value'] for h in msg_data['payload']['headers'] if h['name'] == 'Subject'), 'No Subject')
                snippet = msg_data.get('snippet', '')
                email_context += f"- Subject: {subject}\n  Snippet: {snippet}\n"
        
        return email_context
    except HttpError as error:
        frappe.log_error(
            message=f"Google Gmail API Error for query '{query}': {error.content}",
            title="Gemini Gmail Error"
        )
        return "An API error occurred during Gmail search. Please check the Error Log for details.\n"

def search_drive(credentials, query):
    """Searches Google Drive for a query or lists recent files."""
    try:
        service = build('drive', 'v3', credentials=credentials)
        
        if query.strip():
            search_params = {'q': f"fullText contains '{query}'"}
        else:
            search_params = {'orderBy': 'modifiedTime desc'}

        results = service.files().list(
            pageSize=5,
            fields="nextPageToken, files(id, name, webViewLink)",
            corpora='allDrives',
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            **search_params
        ).execute()
        items = results.get('files', [])

        if not items:
            return "No files found in Google Drive matching your query."
        
        drive_context = "Recent files from Google Drive matching your query:\n"
        for item in items:
            drive_context += f"- Name: {item['name']}, Link: {item['webViewLink']}\n"
        return drive_context
    except HttpError as error:
        return f"An error occurred with Google Drive: {error}"

def search_calendar(credentials, query):
    """Lists upcoming calendar events for the next 7 days."""
    try:
        service = build('calendar', 'v3', credentials=credentials)
        now = datetime.utcnow()
        time_min = now.isoformat() + 'Z'
        time_max = (now + timedelta(days=7)).isoformat() + 'Z'
        
        calendar_list = service.calendarList().list().execute()
        all_events = []

        for calendar_list_entry in calendar_list.get('items', []):
            calendar_id = calendar_list_entry['id']
            events_result = service.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=10,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            for event in events_result.get('items', []):
                event['calendar_name'] = calendar_list_entry.get('summary', calendar_id)
                all_events.append(event)

        if not all_events:
            return "No upcoming calendar events found in the next 7 days."
        
        sorted_events = sorted(all_events, key=lambda x: x['start'].get('dateTime', x['start'].get('date')))
        
        calendar_context = "Upcoming calendar events in the next 7 days:\n"
        for event in sorted_events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'Untitled Event')
            calendar_name = event['calendar_name']
            calendar_context += f"- {summary} at {start} (from Calendar: {calendar_name})\n"
        return calendar_context
    except HttpError as error:
        return f"An error occurred with Google Calendar: {error}"

def get_drive_file_context(credentials, file_id):
    """Fetches a Drive file's metadata and content, supporting Shared Drives."""
    try:
        service = build('drive', 'v3', credentials=credentials)
        file_meta = service.files().get(
            fileId=file_id,
            fields="id, name, webViewLink, modifiedTime, owners, mimeType",
            supportsAllDrives=True
        ).execute()

        owner = file_meta.get('owners', [{}])[0].get('displayName', 'Unknown Owner')
        context = f"Context for Google Drive File: {file_meta.get('name', 'Untitled')}\n"
        context += f"- Link: {file_meta.get('webViewLink', 'Link not available')}\n"

        mime_type = file_meta.get('mimeType', '')
        content = ""

        if 'google-apps.document' in mime_type:
            content_bytes = service.files().export_media(fileId=file_id, mimeType='text/plain').execute()
            content = content_bytes.decode('utf-8')
        elif mime_type == 'text/plain':
            content_bytes = service.files().get_media(fileId=file_id, supportsAllDrives=True).execute()
            content = content_bytes.decode('utf-8')
        else:
            content = "(Content preview is not available for this file type.)"

        # Truncate content to avoid excessive length
        context += f"Content Snippet:\n{content[:3000]}"
        return context
    except HttpError as error:
        frappe.log_error(
            message=f"Google Drive API Error for fileId {file_id}: {error.content}",
            title="Gemini Google Drive Error"
        )
        if error.resp.status == 404:
            return f"(System: A 404 Not Found error occurred for Google Drive file {file_id}. This means the file does not exist or you do not have permission to access it. Please double-check the file ID and your permissions in Google Drive. More details may be in the Error Log.)\n"
        return f"An API error occurred while fetching Google Drive file {file_id}. Please check the Error Log for details.\n"
    except Exception as e:
        frappe.log_error(f"Error fetching drive file context for {file_id}: {str(e)}")
        return f"(System: Could not retrieve context for Google Drive file {file_id}.)\n"

def get_gmail_message_context(credentials, message_id):
    """Fetches a specific Gmail message's headers and body."""
    try:
        service = build('gmail', 'v1', credentials=credentials)
        msg_data = service.users().messages().get(userId='me', id=message_id, format='full').execute()

        headers = {h['name']: h['value'] for h in msg_data['payload']['headers']}
        link = f"https://mail.google.com/mail/#all/{msg_data['threadId']}"
        
        content = "(Could not extract email body.)"
        payload = msg_data.get('payload', {})
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    data = part['body'].get('data')
                    if data:
                        content = base64.urlsafe_b64decode(data).decode('utf-8')
                    break
        else:
            data = payload.get('body', {}).get('data')
            if data:
                content = base64.urlsafe_b64decode(data).decode('utf-8')

        context = "Context for Gmail Message:\n"
        context += f"- Subject: {headers.get('Subject', 'No Subject')}\n"
        context += f"- From: {headers.get('From', 'N/A')}\n"
        context += f"- Link: {link}\n"
        context += f"Body Snippet:\n{content[:3000]}"
        return context
    except HttpError as error:
        return f"An error occurred while fetching Gmail message {message_id}: {error}\n"
    except Exception as e:
        frappe.log_error(f"Error fetching gmail context for {message_id}: {str(e)}")
        return f"(System: Could not retrieve context for Gmail message {message_id}.)\n"

# --- MAIN CHAT FUNCTIONALITY ---
def generate_chat_response(prompt, model=None, conversation=None):
    """Handles chat interactions by assembling context from ERPNext and Google Workspace.
    
    The process is as follows:
    1. Look for explicit ERPNext doc references (e.g., @CUST-0001).
    2. If none, check for things that look like doc IDs but are missing the '@' and guide the user.
    3. Look for explicit Google Workspace references (e.g., @gdrive/file_id).
    4. Perform keyword-based or general searches in Google Workspace.
    5. Assemble all gathered context into a final prompt for the AI.
    6. Clean all reference syntax from the prompt before sending.
    """
    
    # 1. Find all ERPNext document references starting with '@'
    references = re.findall(r'@([a-zA-Z0-9\s-]+)|@"([^"]+)"', prompt)
    doc_names = [item for tpl in references for item in tpl if item]

    # 2. If no '@' references are found, check for potential IDs the user forgot to mark.
    # This prevents hallucinations by catching mistakes and guiding the user.
    if not doc_names:
        doctype_map = get_dynamic_doctype_map()
        prefixes = list(doctype_map.keys())
        if prefixes:
            # Regex to find patterns like 'PRJ-00123' based on known prefixes.
            pattern = r'\b(' + '|'.join(re.escape(p) for p in prefixes) + r')-[\w\d-]+'
            potential_ids = re.findall(pattern, prompt, re.IGNORECASE)
            if potential_ids:
                suggestions = [f"@{pid}" for pid in potential_ids]
                suggestion_str = ", ".join(suggestions)
                return (
                    f"To ensure I pull the correct data from ERPNext, please use the '@' symbol before any document ID. "
                    f"For example, try asking: 'What is the current status of {suggestion_str}?'"
                )

    # 3. Gather context from all found ERPNext references.
    full_context = ""
    if doc_names:
        doctype_map = get_dynamic_doctype_map()
        all_doctype_names = [d.name for d in frappe.get_all("DocType")]

        for doc_name in doc_names:
            doc_name = doc_name.strip()
            found_doctype = None
            
            if '-' in doc_name:
                prefix = doc_name.split('-')[0].upper()
                mapped_doctype = doctype_map.get(prefix)
                if mapped_doctype and frappe.db.exists(mapped_doctype, doc_name):
                    found_doctype = mapped_doctype
            
            if not found_doctype:
                for dt in all_doctype_names:
                    if frappe.db.exists(dt, doc_name):
                        found_doctype = dt
                        break
            
            if found_doctype:
                full_context += get_doc_context(found_doctype, doc_name) + "\n\n"
            else:
                full_context += f"(System: Document '{doc_name}' could not be found.)\n\n"

    # 4. Gather context from Google Workspace.
    google_context = ""
    creds = None
    if is_google_integrated():
        creds = get_user_credentials()

    if creds:
        # 4a. Look for direct references like @gdrive/file_id or @gmail/message_id
        gdrive_refs = re.findall(r'@gdrive/([\w-]+)', prompt)
        gmail_refs = re.findall(r'@gmail/([\w-]+)', prompt)

        for file_id in gdrive_refs:
            google_context += get_drive_file_context(creds, file_id) + "\n\n"

        for msg_id in gmail_refs:
            google_context += get_gmail_message_context(creds, msg_id) + "\n\n"

        # 4b. Perform keyword-based or general searches for any text not part of a direct reference.
        # This avoids searching for "@gdrive/123" if it was already handled.
        search_prompt = re.sub(r'@gdrive/[\w-]+', '', prompt).strip()
        search_prompt = re.sub(r'@gmail/[\w-]+', '', search_prompt).strip()

        gmail_triggered = re.search(r'\b(email|mail|gmail)\b', search_prompt.lower())
        drive_triggered = re.search(r'\b(drive|file|doc|document|sheet|slide)\b', search_prompt.lower())
        calendar_triggered = re.search(r'\b(calendar|event|meeting)\b', search_prompt.lower())

        if gmail_triggered:
            google_context += search_gmail(creds, search_prompt)
        
        if drive_triggered:
            google_context += search_drive(creds, search_prompt)

        if calendar_triggered:
            google_context += search_calendar(creds, search_prompt)

        # 4c. If no specific keywords or direct links were used, perform a general search.
        if not any([gmail_triggered, drive_triggered, calendar_triggered, gdrive_refs, gmail_refs]):
            google_context += search_gmail(creds, search_prompt)
            google_context += "\n"
            google_context += search_drive(creds, search_prompt)

    # Assemble thoughts for the UI
    thoughts = ""
    if full_context:
        thoughts += f"--- ERPNext Data Context ---\n{full_context}\n"
    
    if google_context:
        thoughts += f"--- Google Workspace Data Context ---\n{google_context}\n"

    # 5. Clean the prompt of all reference syntax before sending it to the AI.
    clean_prompt = re.sub(r'@([a-zA-Z0-9\s-]+)|@"([^"]+)"', '', prompt)
    clean_prompt = re.sub(r'@gdrive/[\w-]+', '', clean_prompt).strip()
    clean_prompt = re.sub(r'@gmail/[\w-]+', '', clean_prompt).strip()

    # 6. Assemble the final prompt with all context.
    system_instruction = frappe.db.get_single_value("Gemini Settings", "system_instruction")
    final_prompt = ""
    if system_instruction:
        final_prompt += f"System Instruction: {system_instruction}\n\n"
    
    if thoughts:
        final_prompt += thoughts

    final_prompt += f"User query: {clean_prompt}\n"
    final_prompt += "\nBased on the user query and any provided context, please provide a helpful and comprehensive response."

    response_text = generate_text(final_prompt, model)
    return {
        "response": response_text,
        "thoughts": thoughts.strip() if thoughts else ""
    }


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
    Example: [{{"subject": "Initial client meeting", "description": "Discuss project scope and deliverables."}}, ...]    """
    
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
    Example: [{{"risk_name": "Scope Creep", "risk_description": "The project description is vague, which could lead to additional client requests not in the original scope."}}, ...]    """
    
    response_text = generate_text(prompt)
    try:
        risks = json.loads(response_text)
        return risks
    except json.JSONDecodeError:
        return {"error": "Failed to parse a JSON response from the AI. Please try again."}
