/* global createGeminiChatUI */

frappe.pages["gemini-chat"].on_page_load = function (wrapper) {
	let page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Gemini Chat",
		single_column: true,
	});

	// Add a custom class to the page wrapper for specific styling
	$(wrapper).addClass("gemini-chat-page");

    // The refactored UI creation function is called here
    createGeminiChatUI(page.body);
};
