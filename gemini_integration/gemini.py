import frappe
import google.generativeai as genai
import re
import json

# A list of common doctypes to search for mentions. You can customize this list.
SEARCHABLE_DOCTYPES = [
    'Project', 'Task', 'Sales Order', 'Customer', 'Item', 'Quotation',
    'Sales Invoice', 'Purchase Order', 'Supplier', 'Lead', 'Opportunity'
]

@frappe.whitelist()
def generate_text(prompt, model=None):
    settings = frappe.get_single("Gemini Settings")
    api_key = settings.api_key
    if not api_key:
        frappe.throw("Please set the Gemini API Key in Gemini Settings.")

    genai.configure(api_key=api_key)

    model_name = model or settings.model
    system_instructions = settings.system_instructions

    model = genai.GenerativeModel(
        model_name,
        system_instruction=system_instructions if system_instructions else None
    )
    response = model.generate_content(prompt)
    return response.text

def _get_document_context(doc_name):
    """Finds a document by name across searchable doctypes and returns its data."""
    for doctype in SEARCHABLE_DOCTYPES:
        if frappe.db.exists(doctype, doc_name):
            try:
                doc = frappe.get_doc(doctype, doc_name)
                # Return a serializable dictionary
                return {
                    "doctype": doctype,
                    "name": doc_name,
                    "data": doc.as_dict()
                }
            except Exception as e:
                frappe.log_error(f"Error fetching doc: {doctype}/{doc_name}", str(e))
                return None
    return None

@frappe.whitelist()
def generate_chat_response(prompt, model=None, conversation=None):
    """
    Generates a response from Gemini, including context from mentioned documents.
    """
    # Regex to find mentions like @SO-0001 or @"Test Customer"
    mentions = re.findall(r'@(?:([a-zA-Z0-9\-\._]+)|"([^"]+)")', prompt)

    context_str = ""
    if mentions:
        # The regex returns tuples of matching groups, e.g. ('SO-0001', '') or ('', 'Test Customer').
        # We need to get the non-empty part of each tuple.
        doc_names = [m[0] if m[0] else m[1] for m in mentions]
        
        contexts = []
        for name in doc_names:
            context = _get_document_context(name)
            if context:
                contexts.append(context)

        if contexts:
            context_str = "CONTEXT FROM ERPNEXT:\n"
            for ctx in contexts:
                # Pretty print JSON for better readability by the model
                context_str += f"--- Document: {ctx['doctype']} ({ctx['name']}) ---\n"
                context_str += json.dumps(ctx['data'], indent=2, default=str) + "\n"
            context_str += "--- End of Context ---\n\n"

    final_prompt = context_str + "USER'S PROMPT:\n" + prompt

    return generate_text(final_prompt, model)

