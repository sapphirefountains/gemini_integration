import frappe
import google.generativeai as genai
from google.generativeai import files
from frappe.utils import get_url_to_form, get_site_url
import re
import json
import base64
from datetime import datetime, timedelta
from thefuzz import process, fuzz
import requests
from bs4 import BeautifulSoup
from PyPDF2 import PdfReader
import io

from gemini_integration.utils import handle_errors, log_activity

# Google API Imports
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- GEMINI API CONFIGURATION AND BASIC GENERATION ---

@log_activity
@handle_errors
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


@log_activity
@handle_errors
def generate_text(prompt, model_name=None, uploaded_files=None, generation_config=None):
    """Generates text using a specified Gemini model."""
    if not configure_gemini():
        frappe.throw("Gemini integration is not configured. Please set the API Key in Gemini Settings.")

    if not model_name:
        model_name = frappe.db.get_single_value("Gemini Settings", "default_model") or "gemini-2.5-pro"

    if generation_config is None:
        generation_config = {}
    if "max_output_tokens" not in generation_config:
        if model_name in ["gemini-2.5-pro", "gemini-2.5-flash"]:
            generation_config["max_output_tokens"] = 8192

    try:
        model_instance = genai.GenerativeModel(model_name)
        content = [prompt] + uploaded_files if uploaded_files else [prompt]
        response = model_instance.generate_content(content, generation_config=generation_config)
        return response.text
    except Exception as e:
        frappe.log_error(f"Gemini API Error: {str(e)}", "Gemini Integration")
        frappe.throw("An error occurred while communicating with the Gemini API. Please check the Error Log for details.")


# --- URL CONTEXT FETCHING ---

@log_activity
def extract_urls(text):
    """Extracts all URLs from a given text."""
    url_pattern = r'https?://[^\s/$.?#].[^\s]*'
    return re.findall(url_pattern, text)


@handle_errors
def get_html_content(url):
    """Fetches and extracts text content from a HTML URL."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        return soup.get_text(separator=' ', strip=True)
    except requests.RequestException as e:
        frappe.log_error(f"Error fetching URL {url}: {e}", "Gemini URL Fetcher")
        return None


@handle_errors
def get_pdf_content(url):
    """Fetches and extracts text content from a PDF URL."""
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        with io.BytesIO(response.content) as f:
            reader = PdfReader(f)
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
        return text
    except requests.RequestException as e:
        frappe.log_error(f"Error fetching PDF from {url}: {e}", "Gemini URL Fetcher")
        return None
    except Exception as e:
        frappe.log_error(f"Error parsing PDF from {url}: {e}", "Gemini URL Fetcher")
        return None


@log_activity
def get_url_context(urls):
    """Fetches content from a list of URLs, respecting a blacklist, and returns a formatted context string."""
    full_context = ""
    settings = frappe.get_single("Gemini Settings")
    blacklist_str = settings.get("url_blacklist", "")
    blacklist = [item.strip() for item in blacklist_str.split('\n') if item.strip()]

    for url in urls:
        is_blacklisted = any(bl_item in url for bl_item in blacklist)

        if is_blacklisted:
            full_context += f"(System: The URL '{url}' was skipped because it is on the blacklist.)\n\n"
            continue

        try:
            headers = requests.head(url, timeout=5, allow_redirects=True)
            headers.raise_for_status()
            content_type = headers.headers.get('Content-Type', '')

            content = None
            if 'application/pdf' in content_type:
                content = get_pdf_content(url)
            elif 'text/html' in content_type:
                content = get_html_content(url)
            else:
                # Fallback for other text-based content types
                content = get_html_content(url)

            if content is not None:
                full_context += f"Content from URL '{url}':\n{content[:5000]}\n\n" # Limit content length
            else:
                # This happens if get_pdf_content or get_html_content return None.
                # Their internal errors are already logged. We throw a clear error here.
                frappe.throw(f"Failed to retrieve or parse content from URL: {url}")
        except requests.RequestException as e:
            frappe.throw(f"Could not access URL: {url}. Error: {e}")

    return full_context


# --- DYNAMIC DOCTYPE REFERENCING (@DOC-NAME) ---

@log_activity
@handle_errors
def get_doc_context(doctype, docname):
    """Fetches and formats a document's data for context."""
    try:
        doc = frappe.get_doc(doctype, docname)
        doc_dict = doc.as_dict()
        context = f"Context for {doctype} '{docname}':\n"
        for field, value in doc_dict.items():
            if value and not isinstance(value, list):
                context += f"- {field}: {value}\n"
        doc_url = get_url_to_form(doctype, docname)
        context += f"\nLink: {doc_url}"
        return context
    except frappe.DoesNotExistError:
        return f"(System: Document '{docname}' of type '{doctype}' not found.)\n"
    except Exception as e:
        frappe.log_error(f"Error fetching doc context for {doctype} {docname}: {str(e)}")
        return f"(System: Could not retrieve context for {doctype} {docname}.)\n"


@log_activity
@handle_errors
def search_erpnext_documents(doctype, query, limit=1000):
    """Searches for documents in ERPNext with a query and returns a list of documents."""
    try:
        # Include 'name' field for searching, as it's often the primary identifier.
        fields = ["name"] + [df.fieldname for df in frappe.get_meta(doctype).fields if df.fieldtype in ["Data", "Text", "Small Text", "Long Text", "Text Editor", "Select"]]
        all_docs = frappe.get_all(doctype, fields=list(set(fields))) # Use set to avoid duplicate fields

        matching_docs = []
        for doc in all_docs:
            # Include the doctype name in the searchable text to improve context-aware search.
            doc_text = f"{doctype} " + " ".join([str(doc.get(field, '')) for field in fields])

            # token_set_ratio is good for matching phrases and ignoring word order.
            score = fuzz.token_set_ratio(query.lower(), doc_text.lower())

            if score > 75: # Adjusted threshold for token_set_ratio
                matching_docs.append({"name": doc.name, "score": score})

        # Sort by score in descending order and take the top results
        sorted_matches = sorted(matching_docs, key=lambda x: x['score'], reverse=True)
        documents = sorted_matches[:limit]

        disclaimer = f"(System: Searched {len(all_docs)} documents of type '{doctype}' and found {len(documents)} potential matches.)\n"
        return documents, disclaimer
    except Exception as e:
        frappe.log_error(f"Error searching ERPNext documents for doctype {doctype}: {str(e)}")
        return [], f"(System: Could not search documents of type '{doctype}'.)\n"


@log_activity
@handle_errors
def get_dynamic_doctype_map():
    """Builds and caches a map of naming series prefixes to DocTypes."""
    cache_key = "gemini_doctype_prefix_map"
    doctype_map = frappe.cache().get_value(cache_key)
    if doctype_map:
        return doctype_map

    doctype_map = {}
    all_doctypes = frappe.get_all("DocType", fields=["name", "autoname"])
    for doc in all_doctypes:
        autoname = doc.get("autoname")
        if isinstance(autoname, str):
            match = re.match(r'^([A-Z_]+)[\-./]', autoname, re.IGNORECASE)
            if match:
                doctype_map[match.group(1).upper()] = doc.name

    hardcoded_map = {
        "PRJ": "Project", "TASK": "Task", "SO": "Sales Order", "PO": "Purchase Order",
        "QUO": "Quotation", "SI": "Sales Invoice", "PI": "Purchase Invoice",
        "CUST": "Customer", "SUPP": "Supplier", "ITEM": "Item", "LEAD": "Lead",
        "OPP": "Opportunity"
    }
    hardcoded_map.update(doctype_map)
    doctype_map = hardcoded_map

    frappe.cache().set_value(cache_key, doctype_map, expires_in_sec=3600)
    return doctype_map


# --- OAUTH AND GOOGLE API FUNCTIONS ---

@log_activity
@handle_errors
def get_google_settings():
    """Retrieves Google settings from Social Login Keys."""
    settings = frappe.get_doc("Social Login Key", "Google")
    if not settings or not settings.enable_social_login:
        frappe.throw("Google Login is not enabled in Social Login Keys.")
    return settings


@log_activity
@handle_errors
def get_google_flow():
    """Builds the Google OAuth 2.0 Flow object for authentication."""
    settings = get_google_settings()
    redirect_uri = get_site_url(frappe.local.site) + "/api/method/gemini_integration.api.handle_google_callback"
    client_secrets = {
        "web": {
            "client_id": settings.client_id, "client_secret": settings.get_password('client_secret'),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    scopes = [
        "https://www.googleapis.com/auth/userinfo.email", "openid",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/contacts.readonly",
    ]
    return Flow.from_client_config(client_secrets, scopes=scopes, redirect_uri=redirect_uri)


@log_activity
@handle_errors
def get_google_auth_url():
    """Generates the authorization URL for the user to grant consent."""
    flow = get_google_flow()
    authorization_url, state = flow.authorization_url(access_type='offline', prompt='consent')
    frappe.cache().set_value(f"google_oauth_state_{frappe.session.user}", state, expires_in_sec=600)
    return authorization_url


@log_activity
@handle_errors
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
        userinfo_service = build('oauth2', 'v2', credentials=creds)
        user_info = userinfo_service.userinfo().get().execute()
        google_email = user_info.get('email')

        doc_name = frappe.db.get_value("Google User Token", {"user": frappe.session.user}, "name")
        if doc_name:
            token_doc = frappe.get_doc("Google User Token", doc_name)
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

    frappe.respond_as_web_page("Successfully Connected!", "<div style='text-align: center; padding: 40px;'><h2>Your Google Account has been successfully connected.</h2><p>You can now close this tab.</p></div>", indicator_color="green")


@log_activity
@handle_errors
def is_google_integrated():
    """Checks if a valid token exists for the current user."""
    return frappe.db.exists("Google User Token", {"user": frappe.session.user})


@log_activity
@handle_errors
def get_user_credentials():
    """Retrieves stored credentials for the current user."""
    if not is_google_integrated():
        return None
    try:
        doc_name = frappe.db.get_value("Google User Token", {"user": frappe.session.user}, "name")
        if not doc_name:
            return None
        token_doc = frappe.get_doc("Google User Token", doc_name)
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

@log_activity
@handle_errors
def search_drive_files(credentials, query, limit=5):
    """Searches Google Drive for files and returns a list."""
    try:
        service = build('drive', 'v3', credentials=credentials)
        q = f"fullText contains '{query}'" if query.strip() else None
        results = service.files().list(q=q, pageSize=limit, fields="files(id, name, webViewLink)", corpora='allDrives', includeItemsFromAllDrives=True, supportsAllDrives=True, orderBy='modifiedTime desc' if not q else None).execute()
        return results.get('files', [])
    except HttpError as e:
        frappe.log_error(f"Google Drive API Error: {e}", "Gemini Integration")
        return []


@log_activity
@handle_errors
def search_gmail_messages(credentials, query, limit=5):
    """Searches Gmail for messages and returns a list."""
    try:
        service = build('gmail', 'v1', credentials=credentials)
        # The query should not be wrapped in double quotes for a keyword search.
        q = f'{query} in:anywhere' if query.strip() else 'in:inbox'
        results = service.users().messages().list(userId='me', q=q, maxResults=limit).execute()
        messages = results.get('messages', [])
        if not messages: return []

        email_data = []
        batch = service.new_batch_http_request()
        def create_callback(msg_id):
            def callback(request_id, response, exception):
                if not exception:
                    subject = next((h['value'] for h in response['payload']['headers'] if h['name'] == 'Subject'), 'No Subject')
                    email_data.append({"id": msg_id, "subject": subject, "snippet": response.get('snippet', '')})
            return callback

        for msg in messages:
            batch.add(service.users().messages().get(userId='me', id=msg['id'], format='metadata', metadataHeaders=['Subject']), callback=create_callback(msg['id']))
        batch.execute()
        return email_data
    except HttpError as e:
        frappe.log_error(f"Gmail API Error: {e}", "Gemini Integration")
        return []


@log_activity
@handle_errors
def search_google_contacts(credentials, name_query, limit=5):
    """Searches Google Contacts for a person by name."""
    try:
        service = build('people', 'v1', credentials=credentials)
        results = service.people().searchContacts(
            query=name_query,
            pageSize=limit,
            readMask="names,emailAddresses"
        ).execute()
        return results.get('results', [])
    except HttpError as e:
        frappe.log_error(f"Google People API Error: {e}", "Gemini Integration")
        return []


@log_activity
@handle_errors
def get_calendar_events(credentials, days=7):
    """Gets upcoming calendar events and returns a list."""
    try:
        service = build('calendar', 'v3', credentials=credentials)
        now = datetime.utcnow()
        time_min = now.isoformat() + 'Z'
        time_max = (now + timedelta(days=days)).isoformat() + 'Z'
        events_result = service.events().list(calendarId='primary', timeMin=time_min, timeMax=time_max, maxResults=15, singleEvents=True, orderBy='startTime').execute()
        return [{"summary": event.get('summary', 'No Title'), "start": event['start'].get('dateTime', event['start'].get('date')), "end": event['end'].get('dateTime', event['end'].get('date')), "id": event['id']} for event in events_result.get('items', [])]
    except HttpError as e:
        frappe.log_error(f"Google Calendar API Error: {e}", "Gemini Integration")
        return []


@log_activity
@handle_errors
def get_drive_file_context(credentials, file_id):
    """Fetches a Drive file's metadata and content."""
    try:
        service = build('drive', 'v3', credentials=credentials)
        file_meta = service.files().get(fileId=file_id, fields="id, name, webViewLink, mimeType", supportsAllDrives=True).execute()
        context = f"Context for Google Drive File: {file_meta.get('name', 'Untitled')}\n- Link: {file_meta.get('webViewLink', 'N/A')}\n"
        mime_type = file_meta.get('mimeType', '')
        if 'google-apps.document' in mime_type or 'text/plain' in mime_type:
            export_mime = 'text/plain'
            content_bytes = service.files().export_media(fileId=file_id, mimeType=export_mime).execute() if 'google-apps.document' in mime_type else service.files().get_media(fileId=file_id, supportsAllDrives=True).execute()
            content = content_bytes.decode('utf-8')
            context += f"Content Snippet:\n{content[:3000]}"
        else:
            context += "(Content preview not available for this file type.)"
        return context
    except HttpError as error:
        frappe.log_error(f"Google Drive API Error for fileId {file_id}: {error.content}", "Gemini Google Drive Error")
        return f"(System: Error fetching Google Drive file {file_id}. It may not exist or you lack permission.)\n"


@log_activity
@handle_errors
def get_gmail_message_context(credentials, message_id):
    """Fetches a specific Gmail message's headers and body."""
    try:
        service = build('gmail', 'v1', credentials=credentials)
        msg_data = service.users().messages().get(userId='me', id=message_id, format='full').execute()
        headers = {h['name']: h['value'] for h in msg_data['payload']['headers']}
        content = "(Could not extract email body.)"
        if 'parts' in msg_data['payload']:
            for part in msg_data['payload']['parts']:
                if part['mimeType'] == 'text/plain' and 'data' in part['body']:
                    content = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                    break
        elif 'data' in msg_data['payload']['body']:
            content = base64.urlsafe_b64decode(msg_data['payload']['body']['data']).decode('utf-8')

        context = f"Context for Gmail Message:\n- Subject: {headers.get('Subject', 'No Subject')}\n- From: {headers.get('From', 'N/A')}\n"
        context += f"Body Snippet:\n{content[:3000]}"
        return context
    except HttpError as error:
        return f"An error occurred while fetching Gmail message {message_id}: {error}\n"

# --- MAIN CHAT FUNCTIONALITY ---

@log_activity
@handle_errors
def search_documents(query):
    """
    Searches for documents across all searchable doctypes based on a natural language query.
    """
    doctype_map = get_dynamic_doctype_map()
    searchable_doctypes = list(set(doctype_map.values()))

    all_matches = []
    thoughts = ""

    for doctype in searchable_doctypes:
        matches, disclaimer = search_erpnext_documents(doctype, query, limit=100) # Limit per doctype to avoid overload
        if matches:
            for match in matches:
                all_matches.append({"doctype": doctype, "name": match["name"]})
        thoughts += disclaimer

    if len(all_matches) > 20: # Threshold for asking for clarification
        clarification_options = []
        for match in all_matches[:20]: # Show first 20 options
            clarification_options.append({
                "type": "erpnext",
                "label": f"ERPNext: {match['doctype']} '{match['name']}'",
                "data": {"doctype": match['doctype'], "docname": match['name']}
            })
        return {
            "clarification_needed": True,
            "options": clarification_options,
            "response": "I found a lot of documents that could match your query. Please select the most relevant one(s), or refine your search.",
            "thoughts": thoughts
        }

    full_context = ""
    for match in all_matches:
        full_context += get_doc_context(match['doctype'], match['name']) + "\n\n"

    if not full_context:
        full_context = "(System: No relevant documents found across all ERPNext DocTypes.)\n"

    return {"clarification_needed": False, "context": full_context, "thoughts": thoughts}


def _generate_final_response(prompt, context, model, conversation_id, conversation_history, uploaded_files, generation_config=None):
    """Cleans prompt, assembles final context, generates text, and saves conversation."""
    clean_prompt = re.sub(r'@([a-zA-Z0-9\s.-]+)|@"([^"]+)"', '', prompt).strip()

    system_instruction = frappe.db.get_single_value("Gemini Settings", "system_instruction") or ""

    final_prompt_parts = []
    if system_instruction: final_prompt_parts.append(f"System Instruction: {system_instruction}")
    if context: final_prompt_parts.append(f"Context from ERPNext/Google:\n{context}")

    # Add conversation history, avoiding duplication of the current prompt
    if conversation_history:
        for entry in conversation_history:
            if entry.get('text') != prompt:
                final_prompt_parts.append(f"{entry['role']}: {entry['text']}")

    final_prompt_parts.append(f"User query: {clean_prompt}")
    final_prompt_parts.append("\nBased on the user query and provided context, provide a helpful response.")

    final_prompt = "\n".join(final_prompt_parts)
    response_text = generate_text(final_prompt, model, uploaded_files, generation_config=generation_config)

    conversation_history.append({"role": "user", "text": prompt})
    conversation_history.append({"role": "gemini", "text": response_text})
    new_conversation_id = save_conversation(conversation_id, prompt, conversation_history)

    return {"response": response_text, "thoughts": context.strip(), "conversation_id": new_conversation_id, "clarification_needed": False}


@log_activity
@handle_errors
def generate_chat_response(prompt, model=None, conversation_id=None, selected_options=None, generation_config=None):
    """Orchestrates chat interactions, including context fetching and clarification."""
    conversation_history = []
    if conversation_id:
        try:
            conv_doc = frappe.get_doc("Gemini Conversation", conversation_id)
            if conv_doc.conversation:
                conversation_history = json.loads(conv_doc.conversation)
        except frappe.DoesNotExistError:
            pass

    full_context = ""
    thoughts = ""
    uploaded_files = []

    # Extract and process URLs from the prompt
    if prompt:
        urls = extract_urls(prompt)
        if urls:
            url_context = get_url_context(urls)
            full_context += url_context
            thoughts += f"Extracted and processed {len(urls)} URLs.\n"

    if selected_options:
        options = json.loads(selected_options)
        creds = get_user_credentials() if is_google_integrated() else None
        for option in options:
            data = option.get("data", {})
            if option.get("type") == "erpnext":
                full_context += get_doc_context(data.get("doctype"), data.get("docname")) + "\n\n"
            elif option.get("type") == "gdrive" and creds:
                full_context += get_drive_file_context(creds, data.get("file_id")) + "\n\n"
            elif option.get("type") == "gmail" and creds:
                full_context += get_gmail_message_context(creds, data.get("message_id")) + "\n\n"

        original_prompt = next((entry['text'] for entry in reversed(conversation_history) if entry['role'] == 'user'), prompt)
        return _generate_final_response(original_prompt, full_context, model, conversation_id, conversation_history, uploaded_files, generation_config=generation_config)

    # Always use the natural language search logic.
    # Clean the prompt to handle '@' references as simple text.
    search_query = re.sub(r'@([a-zA-Z0-9\s.-]+)|@"([^"]+)"', r'\1\2', prompt).strip()
    search_result = search_documents(search_query)

    if search_result.get("clarification_needed"):
        # Pass the clarification options to the user.
        conversation_history.append({"role": "user", "text": prompt})
        new_conversation_id = save_conversation(conversation_id, prompt, conversation_history)
        search_result["conversation_id"] = new_conversation_id
        # Also search Google Workspace if clarification is needed for ERPNext docs
        creds = get_user_credentials() if is_google_integrated() else None
        if creds:
            # Re-use the clarification options from the search_result
            clarification_options = search_result.get("options", [])
            gdrive_keywords = ['drive', 'file', 'doc', 'document', 'sheet', 'slide']
            gmail_keywords = ['email', 'mail', 'gmail']

            if any(kw in prompt.lower() for kw in gdrive_keywords):
                files = search_drive_files(creds, search_query)
                for f in files:
                    clarification_options.append({"type": "gdrive", "label": f"Google Drive: '{f['name']}'", "data": {"file_id": f['id']}})

            if any(kw in prompt.lower() for kw in gmail_keywords):
                messages = search_gmail_messages(creds, search_query)
                for m in messages:
                    clarification_options.append({"type": "gmail", "label": f"Gmail: '{m['subject']}'", "data": {"message_id": m['id']}})

            search_result["options"] = clarification_options

        return search_result

    full_context += search_result.get("context", "")
    thoughts += search_result.get("thoughts", "")

    creds = get_user_credentials() if is_google_integrated() else None
    if creds:
        gdrive_keywords = ['drive', 'file', 'doc', 'document', 'sheet', 'slide']
        gmail_keywords = ['email', 'mail', 'gmail']
        if any(kw in prompt.lower() for kw in gdrive_keywords):
            files = search_drive_files(creds, prompt)
            if len(files) == 1:
                full_context += get_drive_file_context(creds, files[0]['id']) + "\n\n"
            elif files:
                for f in files:
                    clarification_options.append({"type": "gdrive", "label": f"Google Drive: '{f['name']}'", "data": {"file_id": f['id']}})

        if any(kw in prompt.lower() for kw in gmail_keywords):
            search_query = prompt
            # Try to find a contact name to refine the search. Case-insensitive search.
            contact_name_match = re.search(r'(?:from|by|to)\s+([a-zA-Z\s]+)', prompt, re.IGNORECASE)
            contact_name = contact_name_match.group(1).strip() if contact_name_match else None

            if contact_name:
                contacts = search_google_contacts(creds, contact_name)
                if len(contacts) == 1:
                    person = contacts[0].get('person', {})
                    email_addresses = person.get('emailAddresses', [])
                    if email_addresses:
                        # If a single contact with an email is found, use it for the search.
                        search_query = email_addresses[0].get('value')
                        thoughts += f"Found a unique Google Contact for '{contact_name}'. Searching emails from '{search_query}'.\n"
                    else:
                        thoughts += f"Found contact '{contact_name}' but they have no email address. Using full prompt for search.\n"
                elif len(contacts) > 1:
                    thoughts += f"Found multiple contacts for '{contact_name}'. Using full prompt for a broader search.\n"
                else:
                    thoughts += f"No Google Contact found for '{contact_name}'. Using full prompt for search.\n"

            messages = search_gmail_messages(creds, search_query)
            if len(messages) == 1:
                full_context += get_gmail_message_context(creds, messages[0]['id']) + "\n\n"
            elif messages:
                for m in messages:
                    clarification_options.append({"type": "gmail", "label": f"Gmail: '{m['subject']}'", "data": {"message_id": m['id']}})

    if 'clarification_options' in locals() and clarification_options:
        conversation_history.append({"role": "user", "text": prompt})
        save_conversation(conversation_id, prompt, conversation_history)
        return {"clarification_needed": True, "options": clarification_options, "response": "I found a few items that could match. Please select the correct one(s):", "thoughts": thoughts, "conversation_id": conversation_id}

    thoughts += full_context
    return _generate_final_response(prompt, full_context, model, conversation_id, conversation_history, uploaded_files, generation_config=generation_config)


def save_conversation(conversation_id, title, conversation):
    """Saves or updates a conversation in the database."""
    if not conversation_id:
        doc = frappe.new_doc("Gemini Conversation")
        doc.title = title[:140]
        doc.user = frappe.session.user
    else:
        doc = frappe.get_doc("Gemini Conversation", conversation_id)

    doc.conversation = json.dumps(conversation)
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return doc.name


# --- PROJECT-SPECIFIC FUNCTIONS ---
@log_activity
@handle_errors
def generate_tasks(project_id, template):
    """Generates a list of tasks for a project using Gemini."""
    if not frappe.db.exists("Project", project_id):
        return {"error": "Project not found."}
    project = frappe.get_doc("Project", project_id)
    prompt = f"Based on the project details and the template '{template}', generate a list of tasks.\nProject: {json.dumps(project.as_dict(), default=str)}\n\nReturn ONLY a valid JSON list of objects with keys \"subject\" and \"description\"."
    response_text = generate_text(prompt)
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        return {"error": "Failed to parse a valid JSON response from the AI."}


@log_activity
@handle_errors
def analyze_risks(project_id):
    """Analyzes a project for potential risks using Gemini."""
    if not frappe.db.exists("Project", project_id):
        return {"error": "Project not found."}
    project = frappe.get_doc("Project", project_id)
    prompt = f"Analyze the project for potential risks (e.g., timeline, budget, scope creep).\nProject: {json.dumps(project.as_dict(), default=str)}\n\nReturn ONLY a valid JSON list of objects with keys \"risk_name\" and \"risk_description\"."
    response_text = generate_text(prompt)
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        return {"error": "Failed to parse a JSON response from the AI."}
