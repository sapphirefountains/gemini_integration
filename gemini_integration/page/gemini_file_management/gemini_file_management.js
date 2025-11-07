frappe.pages["gemini-file-management"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Gemini File Management",
		single_column: true,
	});

	let body = `
		<div class="frappe-card">
			<div class="frappe-card-head">Bulk File Upload</div>
			<div class="frappe-card-body">
				<p>
					Click the button below to start a background job that will scan all files
					in your ERPNext instance and upload them to the Gemini File Search Store.
					This is useful for indexing existing files after the initial setup.
				</p>
				<button class="btn btn-primary" id="start-bulk-upload">Start Bulk Upload</button>
			</div>
		</div>
	`;

	$(body).appendTo(page.main);

	$("#start-bulk-upload").on("click", function () {
		frappe.call({
			method: "gemini_integration.api.start_bulk_file_upload",
			callback: function (r) {
				if (r.message) {
					frappe.show_alert({
						message: __("Bulk upload process has been started."),
						indicator: "green",
					});
				}
			},
		});
	});
};
