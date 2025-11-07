app_name = "gemini_integration"
app_title = "Gemini Integration"
app_publisher = "Sapphire Fountains"
app_description = "Google Gemini integration with Frappe ERPNext 15."
app_email = "info@sapphirefountains.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "gemini_integration",
# 		"logo": "/assets/gemini_integration/logo.png",
# 		"title": "Gemini Integration",
# 		"route": "/gemini_integration",
# 		"has_permission": "gemini_integration.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/gemini_integration/css/gemini_integration.css"
app_include_js = [
	"https://cdnjs.cloudflare.com/ajax/libs/showdown/2.1.0/showdown.min.js",
	"https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.8/purify.min.js",
	"/assets/gemini_integration/js/gemini_chat_ui.js",
	"/assets/gemini_integration/js/global_chat.js",
]

# include js, css files in header of web template
# web_include_css = "/assets/gemini_integration/css/gemini_integration.css"
# web_include_js = "/assets/gemini_integration/js/gemini_integration.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "gemini_integration/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"gemini-chat" : "public/js/gemini_chat.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "gemini_integration/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "gemini_integration.utils.jinja_methods",
# 	"filters": "gemini_integration.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "gemini_integration.install.before_install"
# after_install = "gemini_integration.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "gemini_integration.uninstall.before_uninstall"
# after_uninstall = "gemini_integration.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "gemini_integration.utils.before_app_install"
# after_app_install = "gemini_integration.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "gemini_integration.utils.before_app_uninstall"
# after_app_uninstall = "gemini_integration.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "gemini_integration.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events
import frappe


def get_doctypes_for_embedding():
	"""
	Fetches the list of DocTypes configured for embedding from Gemini Settings.
	"""
	try:
		if frappe.db.exists("DocType", "Gemini Settings"):
			settings = frappe.get_single("Gemini Settings")
			return [link.doctype_name for link in settings.get("embedding_doctypes", [])]
	except Exception:
		# This can happen during installation or if the DocType is not yet synced
		pass
	return []


doc_events = {}
doctypes_to_embed = get_doctypes_for_embedding()
for doctype in doctypes_to_embed:
	doc_events[doctype] = {
		"on_update": "gemini_integration.gemini.update_embedding",
		"on_trash": "gemini_integration.gemini.delete_embeddings_for_doc",
	}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"gemini_integration.tasks.all"
# 	],
# 	"daily": [
# 		"gemini_integration.tasks.daily"
# 	],
# 	"hourly": [
# 		"gemini_integration.tasks.hourly"
# 	],
# 	"weekly": [
# 		"gemini_integration.tasks.weekly"
# 	],
# 	"monthly": [
# 		"gemini_integration.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "gemini_integration.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "gemini_integration.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "gemini_integration.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["gemini_integration.utils.before_request"]
# after_request = ["gemini_integration.utils.after_request"]

# Job Events
# ----------
# before_job = ["gemini_integration.utils.before_job"]
# after_job = ["gemini_integration.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"gemini_integration.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }
