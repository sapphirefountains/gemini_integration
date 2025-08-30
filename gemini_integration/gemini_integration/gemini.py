import frappe
import google.generativeai as genai
from frappe.utils import get_url_to_form
import re

def configure_gemini():
    """Configures the Google Generative AI client with the API key from settings."""
    api_key = frappe.get_single_value('Gemini Settings', 'api_key')

    if api_key:
        frappe.log_error(
            f"Attempting to use Gemini API Key starting with '{api_key[:8]}' and ending with '{api_key[-4:]}'",
            "Gemini API Key Check"
        )
    else:
        frappe.log_error("No Gemini API Key found in settings.", "Gemini API Key Check")

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
