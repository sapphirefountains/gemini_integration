import frappe
import functools
import traceback
import logging

def get_log_level():
    try:
        return frappe.db.get_single_value("Gemini Settings", "log_level")
    except Exception:
        return "Error"

def log_activity(func):
    """A decorator to log activity."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        log_level = get_log_level()
        if log_level == "Debug":
            frappe.log(f"Calling function {func.__name__} with args: {args}, kwargs: {kwargs}", "Gemini Integration Debug")
        
        result = func(*args, **kwargs)
        
        if log_level == "Debug":
            frappe.log(f"Function {func.__name__} returned: {result}", "Gemini Integration Debug")
        
        return result
    return wrapper


def handle_errors(func):
    """A decorator to handle errors in a centralized way."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            log_level = get_log_level()
            if log_level in ["Error", "Warning", "Debug"]:
                # Log the error with traceback
                frappe.log_error(
                    message=f"An error occurred in {func.__name__}: {str(e)}\n{traceback.format_exc()}",
                    title="Gemini Integration Error"
                )
            
            # Throw a user-friendly error message
            frappe.throw("An unexpected error occurred. Please contact the system administrator.")
    return wrapper
