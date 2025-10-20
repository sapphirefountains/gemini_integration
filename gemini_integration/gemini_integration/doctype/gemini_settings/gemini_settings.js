// Copyright (c) 2025 Sapphire Fountains and contributors
// For license information, please see license.txt

frappe.ui.form.on("Gemini Settings", {
	refresh: function (frm) {
		// Add a custom button to the page header
		frm.add_custom_button(__("Generate Embeddings"), function () {
			frappe.call({
				method: "gemini_integration.api.enqueue_backfill_embeddings",
				callback: function (r) {
					if (r.message && r.message.status === "success") {
						frappe.show_alert({
							message: __("Embedding generation has been started in the background."),
							indicator: "green",
						});
					}
				},
			});
		});

		// Listen for real-time events from the background job
		frappe.realtime.on("embedding_backfill_complete", function (data) {
			frappe.show_alert({
				message: __(data.message || "Embedding generation complete."),
				indicator: "green",
			});
		});

		frappe.realtime.on("embedding_backfill_failed", function (data) {
			frappe.show_alert({
				message: __(data.error || "An error occurred during embedding generation."),
				indicator: "red",
			});
		});
	},
});
