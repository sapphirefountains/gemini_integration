import frappe
import google.generativeai as genai
from frappe.utils import get_url_to_form
import re

def configure_gemini():
    """Configures the Google Generative AI client with the API key from settings."""
    api_key = frappe.get_single_value('Gemini Settings', 'api_key')

    # --- DEBUGGING STEP ---
    # Log the first 8 and last 4 characters of the key being used to the error log.
    if api_key:
        frappe.log_error(
            f"Using Gemini API Key starting with '{api_key[:8]}' and ending with '{api_key[-4:]}'",
            "Gemini Integration Debug"
        )
    else:
        frappe.log_error("No Gemini API Key found in settings.", "Gemini Integration Debug")
    # --- END DEBUGGING STEP ---

    if not api_key:
        frappe.throw("Gemini API Key not found in Gemini Settings.")

    genai.configure(api_key=api_key)

@frappe.whitelist()
def generate_text(prompt, model=None):
    """Generates text using the Gemini API."""
    configure_gemini()
    if not model:
        model = frappe.get_single_value('Gemini Settings', 'model') or 'gemini-2.5-flash'

    system_instruction = frappe.get_single_value('Gemini Settings', 'system_instruction')

    try:
        model_instance = genai.GenerativeModel(model, system_instruction=system_instruction)
        response = model_instance.generate_content(prompt)
        return response.text
    except Exception as e:
        frappe.log_error(f"Gemini API Error: {str(e)}", "Gemini Integration Error")
        frappe.throw("An error occurred while communicating with the Gemini API.")

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
        return f"Document '{docname}' of type '{doctype}' not found."
    except Exception as e:
        frappe.log_error(f"Error fetching doc context: {str(e)}")
        return f"Could not retrieve context for {doctype} {docname}."

@frappe.whitelist()
def generate_chat_response(prompt, model=None, conversation=None):
    """Handles chat interactions, including document references."""
    # Find all @-references, e.g., @PROJ-001 or @"Some Customer"
    references = re.findall(r'@\[?([a-zA-Z0-9\s-]+)\]?|@"([^"]+)"', prompt)
    
    full_context = ""
    for ref_tuple in references:
        # ref_tuple will be like ('PROJ-001', '') or ('', 'Some Customer')
        docname = next((item for item in ref_tuple if item), None)
        if docname:
            # Simple heuristic to guess doctype for now. Can be improved.
            # This is a basic example and might need to be made more robust.
            parts = docname.split('-')
            doctype_map = {
                "PROJ": "Project",
                "SO": "Sales Order",
                "CUST": "Customer",
            }
            doctype = doctype_map.get(parts[0], frappe.db.get_value("DocType", {"name": docname}, "name") or docname)

            if frappe.db.exists(doctype, docname):
                 full_context += get_doc_context(doctype, docname) + "\n\n"
            else:
                 # Try searching by another field if it's not a name
                 possible_doctype = frappe.db.sql(f"""SELECT parent FROM `tabDocField` WHERE fieldname LIKE '%{docname.lower().replace(" ", "_")}%' and fieldtype='Data'""")
                 if possible_doctype:
                     dt = possible_doctype[0][0]
                     real_docname = frappe.db.get_value(dt, {docname.lower().replace(" ", "_"): docname})
                     if real_docname:
                         full_context += get_doc_context(dt, real_docname) + "\n\n"


    final_prompt = f"{full_context}User query: {prompt}"

    # For now, we'll just use the simple text generation.
    # A real chat implementation would handle conversation history.
    return generate_text(final_prompt, model)


