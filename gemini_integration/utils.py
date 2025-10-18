import functools
import logging
import traceback

import frappe


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
