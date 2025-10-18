frappe.pages["gemini-integration"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Gemini Integration",
		single_column: true,
	});

	let input_area = page.add_field({
		label: "Prompt",
		fieldtype: "Text",
		fieldname: "prompt",
	});

	let model_selector = page.add_field({
		label: "Model",
		fieldtype: "Select",
		fieldname: "model",
		options: ["gemini-2.5-flash", "gemini-2.5-pro"],
	});

	let response_area = page.add_field({
		label: "Response",
		fieldtype: "Text",
		fieldname: "response",
		read_only: true,
	});

	page.add_button("Generate", () => {
		let prompt = input_area.get_value();
		let model = model_selector.get_value();
		if (prompt) {
			frappe.call({
				method: "gemini_integration.api.generate",
				args: {
					prompt: prompt,
					model: model,
				},
				callback: function (r) {
					response_area.set_value(r.message);
				},
			});
		}
	});

	frappe.db.get_single_value("Gemini Settings", "model").then((model) => {
		if (model) {
			model_selector.set_value(model);
		}
	});
};
