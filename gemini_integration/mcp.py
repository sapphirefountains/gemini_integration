import frappe
import frappe_mcp

mcp = frappe_mcp.MCP(__name__)


@mcp.register()
def handle_mcp():
	"""The entry point for MCP requests.

	This function is registered with the MCP instance and is called when a
	request is made to the MCP. It imports the tools module to ensure that
	all the tools are registered with the MCP.
	"""
	import gemini_integration.tools  # noqa: F401