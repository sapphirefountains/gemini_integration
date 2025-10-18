import frappe
import frappe_mcp

mcp = frappe_mcp.MCP(
	"gemini",
	__name__,
	"Gemini Integration",
	"An MCP server for Gemini Integration.",
)


@mcp.register()
def handle_mcp():
	"""
	The entry point for MCP requests.
	"""
	import gemini_integration.utils  # noqa: F401