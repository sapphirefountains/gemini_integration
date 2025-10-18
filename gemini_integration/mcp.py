import frappe
import frappe_mcp

mcp = frappe_mcp.MCP(__name__)


@mcp.register()
def handle_mcp():
	"""
	The entry point for MCP requests.
	"""
	import gemini_integration.utils  # noqa: F401