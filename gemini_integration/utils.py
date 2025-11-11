import functools
import traceback

import frappe
import google.genai as genai
from google.genai.errors import ServerError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from google.genai.types import EmbedContentConfig
from frappe.utils import get_site_url
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build


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
			frappe.log(f"Calling function {func.__name__} with args: {args}, kwargs: {kwargs}")

		result = func(*args, **kwargs)

		if log_level == "Debug":
			frappe.log(f"Function {func.__name__} returned: {result}")

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

			# Throw a more informative error message
			error_type = type(e).__name__
			frappe.throw(
				f"An unexpected error occurred: {error_type}. Please contact the system administrator."
			)

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


@log_activity
@handle_errors
def get_google_flow():
	"""Builds the Google OAuth 2.0 Flow object for authentication.

	Returns:
	    google_auth_oauthlib.flow.Flow: The configured Google OAuth 2.0 Flow object.
	"""
	settings = get_google_settings()
	redirect_uri = (
		get_site_url(frappe.local.site) + "/api/method/gemini_integration.api.handle_google_callback"
	)
	client_secrets = {
		"web": {
			"client_id": settings.client_id,
			"client_secret": settings.get_password("client_secret"),
			"auth_uri": "https://accounts.google.com/o/oauth2/auth",
			"token_uri": "https://oauth2.googleapis.com/token",
		}
	}
	# Scopes define the level of access to the user's Google data.
	scopes = [
		"https://www.googleapis.com/auth/userinfo.email",
		"openid",
		"https://www.googleapis.com/auth/gmail.modify",
		"https://www.googleapis.com/auth/gmail.send",
		"https://www.googleapis.com/auth/drive",
		"https://www.googleapis.com/auth/calendar",
		"https://www.googleapis.com/auth/contacts.readonly",
	]
	return Flow.from_client_config(client_secrets, scopes=scopes, redirect_uri=redirect_uri)


@log_activity
@handle_errors
def get_google_auth_url():
	"""Generates the authorization URL for the user to grant consent.

	Returns:
	    str: The Google authorization URL.
	"""
	flow = get_google_flow()
	authorization_url, state = flow.authorization_url(access_type="offline", prompt="consent")
	# Store the state in cache to prevent CSRF attacks.
	frappe.cache().set_value(f"google_oauth_state_{frappe.session.user}", state, expires_in_sec=600)
	return authorization_url


@log_activity
@handle_errors
def process_google_callback(code, state, error):
	"""Handles the OAuth callback from Google, exchanges the code for tokens, and stores them.

	Args:
	    code (str): The authorization code received from Google.
	    state (str): The state parameter for CSRF protection.
	    error (str): Any error returned by Google.
	"""
	if error:
		frappe.log_error(f"Google OAuth Error: {error}", "Gemini Integration")
		frappe.respond_as_web_page(
			"Google Authentication Failed", f"An error occurred: {error}", http_status_code=401
		)
		return

	cached_state = frappe.cache().get_value(f"google_oauth_state_{frappe.session.user}")
	if not cached_state or cached_state != state:
		frappe.log_error("Google OAuth State Mismatch", "Gemini Integration")
		frappe.respond_as_web_page(
			"Authentication Failed", "State mismatch. Please try again.", http_status_code=400
		)
		return

	try:
		flow = get_google_flow()
		flow.fetch_token(code=code)
		creds = flow.credentials

		# Get user's email to store alongside the token for reference.
		userinfo_service = build("oauth2", "v2", credentials=creds)
		user_info = userinfo_service.userinfo().get().execute()
		google_email = user_info.get("email")

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
		frappe.respond_as_web_page(
			"Error", "An unexpected error occurred while saving your credentials.", http_status_code=500
		)
		return

	# Show a success page to the user.
	frappe.respond_as_web_page(
		"Successfully Connected!",
		"""<div style='text-align: center; padding: 40px;'>
              <h2>Your Google Account has been successfully connected.</h2>
              <p>You can now close this tab and return to the Gemini Chat page in ERPNext.</p>
           </div>""",
		indicator_color="green",
	)


def get_gemini_client():
	"""Creates and returns an authenticated Gemini client.

	Returns:
	    google.genai.Client: An initialized Gemini client, or None on failure.
	"""
	settings = frappe.get_single("Gemini Settings")
	api_key = settings.get_password("api_key")
	if not api_key:
		frappe.log_error("Gemini API Key not found in Gemini Settings.", "Gemini Integration")
		return None
	try:
		return genai.Client(api_key=api_key)
	except Exception as e:
		frappe.log_error(f"Failed to create Gemini client: {e!s}", "Gemini Integration")
		return None


@retry(
	wait=wait_exponential(multiplier=1, min=2, max=60),
	stop=stop_after_attempt(3),
	retry=retry_if_exception_type(ServerError),
)
def generate_embedding(text):
	"""
	Generates an embedding for a given text using the Gemini API.
	"""
	client = get_gemini_client()
	if not client:
		return None
	try:
		result = client.models.embed_content(
			model="models/embedding-001",
			contents=text,
			config=EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
		)
		if result.embeddings:
			return result.embeddings[0].values
		return None
	except Exception as e:
		frappe.log_error(
			message=f"Failed to generate embedding: {e!s}\n{frappe.get_traceback()}",
			title="Gemini Embedding Generation Error",
		)
		return None


def generate_text(prompt, model_name=None, uploaded_files=None):
	"""Generates text using a specified Gemini model.

	Args:
	    prompt (str): The text prompt for the model.
	    model_name (str, optional): The name of the model to use.
	        If not provided, the default model from settings will be used.
	        Defaults to None.
	    uploaded_files (list, optional): A list of uploaded files to include
	        in the context. Defaults to None.

	Returns:
	    str: The generated text from the model.
	"""
	client = get_gemini_client()
	if not client:
		frappe.throw("Gemini integration is not configured. Please set the API Key in Gemini Settings.")

	if not model_name:
		model_name = frappe.db.get_single_value("Gemini Settings", "default_model") or "gemini-2.5-pro"

	try:
		model = genai.GenerativeModel(model_name)
		contents = [prompt]
		if uploaded_files:
			contents.extend(uploaded_files)

		response = model.generate_content(contents)
		try:
			return response.text
		except ValueError:
			# This can happen if the model returns a function call or other non-text part.
			# For a simple text generation, we can just return an empty string.
			return ""
	except Exception as e:
		frappe.log_error(f"Gemini API Error: {e!s}", "Gemini Integration")
		frappe.throw(
			"An error occurred while communicating with the Gemini API. Please check the Error Log for details."
		)
