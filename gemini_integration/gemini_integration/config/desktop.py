from frappe import _


def get_data():
	"""Returns the configuration for the Gemini Integration module in the desk.

	Returns:
	    list: A list of dictionaries containing the module configuration.
	"""
	return [
		{
			"module_name": "Gemini Integration",
			"color": "grey",
			"icon": "octicon octicon-rocket",
			"type": "module",
			"label": _("Gemini Integration"),
		}
	]
