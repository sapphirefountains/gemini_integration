// This script handles the Gemini File Management page.

frappe.pages["gemini-file-management"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Gemini File Management",
		single_column: true,
	});

	// Add a refresh button
	page.add_inner_button(__("Refresh"), function () {
		// Clear the existing list and redraw it
		page.main.find(".gemini-embedding-list").remove();
		draw_gemini_embedding_list(page);
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

	draw_gemini_embedding_list(page);
	draw_gemini_file_embedding_list(page);
};

function draw_gemini_file_embedding_list(page) {
	// Add a container for the list
	let list_container = $(`
		<div class="gemini-embedding-list frappe-card" style="margin-top: 15px;">
			<div class="frappe-card-head">File Embeddings</div>
			<div class="frappe-card-body">
				<div class="list-group"></div>
			</div>
		</div>
	`).appendTo(page.main);

	// Fetch the Gemini File Store documents
	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Gemini File Store",
			fields: ["name", "file_url", "status"],
			order_by: "modified desc",
			limit_page_length: 100,
		},
		callback: function (r) {
			if (r.message && r.message.length) {
				// Render the list
				r.message.forEach(function (item) {
					let list_item = $(`
						<div class="list-group-item">
							<div class="row">
								<div class="col-sm-6">
									<a href="/app/gemini-file-store/${item.name}">${item.name}</a>
								</div>
								<div class="col-sm-4">${item.file_url}</div>
								<div class="col-sm-2">
									<span class="indicator whitespace-nowrap ${
										item.status === "Completed"
											? "green"
											: item.status === "Pending"
											? "orange"
											: "red"
									}">${item.status}</span>
								</div>
							</div>
						</div>
					`).appendTo(list_container.find(".list-group"));
				});
			} else {
				// Show a message if there are no embeddings
				list_container
					.find(".list-group")
					.append(
						`<div class="list-group-item text-muted">No file embeddings found.</div>`
					);
			}
		},
	});
}

function draw_gemini_embedding_list(page) {
	// Add a container for the list
	let list_container = $(`
		<div class="gemini-embedding-list frappe-card" style="margin-top: 15px;">
			<div class="frappe-card-head">DocType Embeddings</div>
			<div class="frappe-card-body">
				<div class="list-group"></div>
			</div>
		</div>
	`).appendTo(page.main);

	// Fetch the Gemini Embedding documents
	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Gemini Embedding",
			fields: ["name", "ref_doctype", "ref_docname", "status"],
			order_by: "modified desc",
			limit_page_length: 100,
		},
		callback: function (r) {
			if (r.message && r.message.length) {
				// Render the list
				r.message.forEach(function (item) {
					let list_item = $(`
						<div class="list-group-item">
							<div class="row">
								<div class="col-sm-6">
									<a href="/app/gemini-embedding/${item.name}">${item.name}</a>
								</div>
								<div class="col-sm-4">${item.ref_docname}</div>
								<div class="col-sm-2">
									<span class="indicator whitespace-nowrap ${
										item.status === "Completed"
											? "green"
											: item.status === "Pending"
											? "orange"
											: "red"
									}">${item.status}</span>
								</div>
							</div>
						</div>
					`).appendTo(list_container.find(".list-group"));
				});
			} else {
				// Show a message if there are no embeddings
				list_container
					.find(".list-group")
					.append(
						`<div class="list-group-item text-muted">No DocType embeddings found.</div>`
					);
			}
		},
	});
}
