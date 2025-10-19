import functools
import traceback

import frappe
from google.oauth2.credentials import Credentials


def get_log_level():
	"""Retrieves the log level from Gemini Settings.

	Returns:
	    str: The configured log level ("Debug", "Warning", "Error"),
	         or "Error" if settings are not found.
	"""
	try:
		return frappe.db.get_single_value("Gemini Settings", "log_level")
	except Exception:
		return "Error"


def log_activity(func):
	"""A decorator to log function calls and results for debugging purposes.

	This decorator will only log activity if the log level in Gemini Settings
	is set to "Debug".

	Args:
	    func (function): The function to be decorated.

	Returns:
	    function: The wrapped function.
	"""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		log_level = get_log_level()
		if log_level == "Debug":
			frappe.log(
				f"Calling function {func.__name__} with args: {args}, kwargs: {kwargs}",
				"Gemini Integration Debug",
			)

		result = func(*args, **kwargs)

		if log_level == "Debug":
			frappe.log(f"Function {func.__name__} returned: {result}", "Gemini Integration Debug")

		return result

	return wrapper


def handle_errors(func):
	"""A decorator to handle exceptions in a centralized way.

	This decorator catches any exception from the decorated function, logs it
	with a full traceback, and then throws a generic, user-friendly error
	message to the UI. Logging only occurs if the log level is set to
	"Error", "Warning", or "Debug".

	Args:
	    func (function): The function to be decorated.

	Returns:
	    function: The wrapped function.
	"""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		try:
			return func(*args, **kwargs)
		except Exception as e:
			log_level = get_log_level()
			if log_level in ["Error", "Warning", "Debug"]:
				# Log the error with traceback
				frappe.log_error(
					message=f"An error occurred in {func.__name__}: {e!s}\n{traceback.format_exc()}",
					title="Gemini Integration Error",
				)

			# Throw a user-friendly error message
			frappe.throw("An unexpected error occurred. Please contact the system administrator.")

	return wrapper


@log_activity
@handle_errors
def get_google_settings():
	"""Retrieves Google settings from Social Login Keys.

	Returns:
	    frappe.model.document.Document: The Google Social Login Key document.
	"""
	settings = frappe.get_doc("Social Login Key", "Google")
	if not settings or not settings.enable_social_login:
		frappe.throw("Google Login is not enabled in Social Login Keys.")
	return settings


@log_activity
@handle_errors
def is_google_integrated():
	"""Checks if a valid token exists for the current user.

	Returns:
	    bool: True if a token exists, False otherwise.
	"""
	return frappe.db.exists("Google User Token", {"user": frappe.session.user})


@log_activity
@handle_errors
def get_user_credentials():
	"""Retrieves stored credentials for the current user from the database.

	Returns:
	    google.oauth2.credentials.Credentials: The user's credentials, or None if not found.
	"""
	if not is_google_integrated():
		return None
	try:
		token_doc = frappe.get_doc("Google User Token", {"user": frappe.session.user})
		return Credentials(
			token=token_doc.access_token,
			refresh_token=token_doc.refresh_token,
			token_uri="https://oauth2.googleapis.com/token",
			client_id=get_google_settings().client_id,
			client_secret=get_google_settings().get_password("client_secret"),
			scopes=token_doc.scopes.split(" ") if token_doc.scopes else [],
		)
	except Exception as e:
		frappe.log_error(f"Could not get user credentials: {e}", "Gemini Integration")
		return None
