
frappe.pages['gemini-chat'].on_page_load = function(wrapper) {
	let page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Gemini Chat',
		single_column: true
	});

	// Add custom styles
	const styles = `
		.gemini-chat-wrapper { max-width: 900px; margin: 0 auto; }
		.chat-history { height: 60vh; overflow-y: auto; border: 1px solid #d1d5db; border-radius: 8px; padding: 16px; margin-bottom: 16px; background-color: #f9fafb; }
		.chat-bubble { max-width: 80%; padding: 12px 16px; border-radius: 12px; margin-bottom: 12px; word-wrap: break-word; }
		.chat-bubble.user { background-color: #3b82f6; color: white; margin-left: auto; border-bottom-right-radius: 0; }
		.chat-bubble.gemini { background-color: #e5e7eb; color: #1f2937; margin-right: auto; border-bottom-left-radius: 0; }
		.chat-bubble.thought { background-color: #f3f4f6; color: #4b5563; border-left: 3px solid #6b7280; font-style: italic; font-size: 0.9em; margin-right: auto; border-bottom-left-radius: 0; white-space: pre-wrap; }
		.chat-input-area { display: flex; align-items: center; gap: 8px; }
		.chat-input-area textarea { flex-grow: 1; }
        .model-selector-area { margin-bottom: 15px; display: flex; justify-content: flex-end; align-items: center; gap: 10px; }
        .google-connect-btn { margin-left: auto; }
		.search-results { border: 1px solid #d1d5db; border-radius: 8px; padding: 16px; margin-bottom: 16px; background-color: #f9fafb; }
		.search-result-item { display: flex; align-items: center; gap: 12px; padding: 8px; border-bottom: 1px solid #e5e7eb; }
		.search-result-item:last-child { border-bottom: none; }
		.search-result-item img { width: 24px; height: 24px; }
		.search-result-item .result-details { display: flex; flex-direction: column; }
		.search-result-item .result-name { font-weight: 600; }
		.search-result-item .result-meta { font-size: 0.9em; color: #6b7280; }
		.search-filters { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
	`;
	$('<style>').text(styles).appendTo('head');

	let html = `
		<div class="gemini-chat-wrapper">
			<div class="model-selector-area">
				<button class="btn btn-default btn-sm help-btn" title="Help">
					<i class="fa fa-question-circle"></i>
				</button>
				<button class="btn btn-default btn-sm save-conversation-btn" title="Save Conversation">
					<i class="fa fa-save"></i>
				</button>
				<button class="btn btn-default btn-sm view-conversations-btn" title="View Conversations">
					<i class="fa fa-list"></i>
				</button>
                <button class="btn btn-secondary btn-sm google-connect-btn">Connect Google Account</button>
            </div>
			<div class="search-filters">
				<select class="form-control search-source">
					<option value="all">All</option>
					<option value="erpnext">ERPNext</option>
					<option value="drive">Google Drive</option>
					<option value="gmail">Gmail</option>
					<option value="tasks">Google Tasks</option>
				</select>
				<input type="date" class="form-control search-from-date">
				<input type="date" class="form-control search-to-date">
			</div>
			<div class="search-results" style="display: none;"></div>
			<div class="chat-history"></div>
			<div class="chat-input-area">
				<input type="text" class="form-control search-input" placeholder="Search for DocTypes, Google Drive files, and Gmail messages...">
			</div>
			<div class="chat-input-area">
				<textarea class="form-control" rows="2" placeholder="Type your message... (Shift + Enter to send)"></textarea>
				<button class="btn btn-primary send-btn">Send</button>
				<button class="btn btn-default upload-btn" title="Upload File"><i class="fa fa-upload"></i></button>
				<input type="file" class="file-input" style="display: none;">
			</div>
		</div>
	`;
	$(page.body).html(html);

    let chat_history = $(page.body).find('.chat-history');
    let chat_input = $(page.body).find('.chat-input-area textarea');
    let send_btn = $(page.body).find('.send-btn');
    let google_connect_btn = $(page.body).find('.google-connect-btn');
	let help_btn = $(page.body).find('.help-btn');
	let search_input = $(page.body).find('.search-input');
	let search_results = $(page.body).find('.search-results');
	let search_source = $(page.body).find('.search-source');
	let search_from_date = $(page.body).find('.search-from-date');
	let search_to_date = $(page.body).find('.search-to-date');
	let save_conversation_btn = $(page.body).find('.save-conversation-btn');
	let view_conversations_btn = $(page.body).find('.view-conversations-btn');
    let conversation = [];

    page.model_selector = frappe.ui.form.make_control({
        parent: $(page.body).find('.model-selector-area'),
        df: {
            fieldtype: 'Select',
            label: 'Model',
            options: [
                { label: "Gemini 2.5 Flash", value: "gemini-2.5-flash" },
                { label: "Gemini 2.5 Pro", value: "gemini-2.5-pro" }
            ],
            change: function() {
                if (frappe.storage) {
                    let selected_model = this.get_value();
                    frappe.storage.set('gemini_last_model', selected_model);
                }
            }
        },
        render_input: true,
    });
    
    if (frappe.storage) {
        let last_model = frappe.storage.get('gemini_last_model');
        if (last_model) {
            page.model_selector.set_value(last_model);
        } else {
            page.model_selector.set_value('gemini-2.5-flash');
        }
    } else {
        page.model_selector.set_value('gemini-2.5-flash');
    }
    
    frappe.call({
        method: "gemini_integration.api.check_google_integration",
        callback: function(r) {
            if (r.message) {
                google_connect_btn.text("Google Account Connected").removeClass("btn-secondary").addClass("btn-success");
            }
        }
    });

    google_connect_btn.on('click', function() {
        frappe.call({
            method: 'gemini_integration.api.get_auth_url',
            callback: function(r) {
                if (r.message) {
                    window.open(r.message, "_blank");
                }
            }
        });
    });

	help_btn.on('click', () => {
		const help_html = `
			<div>
				<h4>How to Use Gemini Chat</h4>

				<h5>1. Referencing Data</h5>
				<p>You can reference data from ERPNext and Google Workspace directly in your chat messages.</p>
				<ul>
					<li><b>ERPNext Documents:</b> Use <code>@DocType-ID</code> or <code>@"Doc Name"</code> to reference any document.</li>
					<li><b>Google Drive & Gmail:</b> Use <code>@gdrive/file_id</code> or <code>@gmail/message_id</code> to reference specific items.</li>
				</ul>

				<h5>2. Advanced Search</h5>
				<p>Use the search bar to find information across all your connected sources. You can filter by source (All, ERPNext, Google Drive, Gmail, Google Tasks) and by date range.</p>

				<h5>3. File Uploads</h5>
				<p>Click the upload button (<i class="fa fa-upload"></i>) to upload a file. The file will be sent to Gemini and used as context for your next message.</p>

				<h5>4. Actionable Responses</h5>
				<p>You can ask Gemini to perform actions for you, such as creating a new task.</p>
				<ul>
					<li><code>Create a new task to follow up with John Doe.</code></li>
				</ul>

				<h5>5. Conversation History</h5>
				<p>Click the save button (<i class="fa fa-save"></i>) to save your current conversation. You can view your saved conversations by clicking the view button (<i class="fa fa-list"></i>).</p>
			</div>
		`;

		frappe.msgprint({
			title: __('Help: Referencing Data'),
			indicator: 'blue',
			message: help_html
		});
	});

    const send_message = () => {
        let prompt = chat_input.val().trim();
        if (!prompt) return;

        add_to_history('user', prompt);
        chat_input.val('');
        
        let loading = frappe.msgprint({
            message: __("Getting response from Gemini..."),
            indicator: 'blue',
            title: __('Please Wait')
        });

        frappe.call({
            method: 'gemini_integration.api.chat',
            args: {
                prompt: prompt,
                model: page.model_selector.get_value(),
                conversation: JSON.stringify(conversation),
                file_uri: uploaded_file_uri
            },
            callback: function(r) {
                loading.hide();
                if (r.message) {
                    // Handle the structured response with thoughts and answer
                    const thoughts = r.message.thoughts;
                    const answer = r.message.answer;

                    if (thoughts) {
                        add_to_history('thought', thoughts);
                    }
                    add_to_history('gemini', answer);
                } else {
                    // Handle plain string response for backward compatibility or errors
                    add_to_history('gemini', r.message);
                }
            },
            error: function(r) {
                loading.hide();
                let error_msg = r.message ? r.message.replace(/</g, "&lt;").replace(/>/g, "&gt;") : "An unknown error occurred.";
                frappe.msgprint({
                    title: __('Error'),
                    indicator: 'red',
                    message: error_msg
                });
            }
        });

		uploaded_file_uri = null;
    };

    const add_to_history = (role, text) => {
        let bubble = $(`<div class="chat-bubble ${role}"></div>`);
        
        if (text) {
            if (role === 'gemini' && window.showdown) {
                let converter = new showdown.Converter();
                let html = converter.makeHtml(text);
                bubble.html(html);
            } else {
                // For user messages and thoughts, just display the text.
                bubble.text(text);
            }
        }
        
        chat_history.append(bubble);
        chat_history.scrollTop(chat_history[0].scrollHeight);
        
        // Only add user and gemini messages to the conversation history for the next prompt
        if (role === 'user' || role === 'gemini') {
            conversation.push({role: role, text: text});
        }
    };
    
    let script_url = "https://cdnjs.cloudflare.com/ajax/libs/showdown/2.1.0/showdown.min.js";
    let script = document.createElement('script');
    script.type = 'text/javascript';
    script.src = script_url;
    document.head.appendChild(script);

    send_btn.on('click', send_message);

    chat_input.on('keydown', function(e) {
        if (e.key === 'Enter' && e.shiftKey) {
            e.preventDefault();
            send_message();
        }
    });

	const trigger_search = () => {
		let query = search_input.val();
		let source = search_source.val();
		let from_date = search_from_date.val();
		let to_date = search_to_date.val();

		if (query.length > 2) {
			frappe.call({
				method: 'gemini_integration.api.search',
				args: {
					query: query,
					source: source,
					from_date: from_date,
					to_date: to_date
				},
				callback: function(r) {
					if (r.message) {
						let results_html = '';
						if (r.message.doctype_results.length > 0) {
							results_html += '<h5>DocTypes</h5>';
							r.message.doctype_results.forEach(function(result) {
								results_html += `<a href="#" class="search-result-item" data-type="doctype" data-name="${result.name}">
									<img src="/assets/frappe/images/icons/common/file.svg">
									<div class="result-details">
										<div class="result-name">${result.name}</div>
									</div>
								</a>`;
							});
						}
						if (r.message.drive_results.length > 0) {
							results_html += '<h5>Google Drive</h5>';
							r.message.drive_results.forEach(function(result) {
								results_html += `<a href="#" class="search-result-item" data-type="gdrive" data-id="${result.id}">
									<img src="${result.iconLink}">
									<div class="result-details">
										<div class="result-name">${result.name}</div>
										<div class="result-meta">Owner: ${result.owners[0].displayName}</div>
									</div>
								</a>`;
							});
						}
						if (r.message.gmail_results.length > 0) {
							results_html += '<h5>Gmail</h5>';
							r.message.gmail_results.forEach(function(result) {
								results_html += `<a href="#" class="search-result-item" data-type="gmail" data-id="${result.id}">
									<img src="/assets/frappe/images/icons/common/email.svg">
									<div class="result-details">
										<div class="result-name">${result.subject}</div>
										<div class="result-meta">From: ${result.from} | Date: ${result.date}</div>
									</div>
								</a>`;
							});
						}
						if (r.message.task_results.length > 0) {
							results_html += '<h5>Google Tasks</h5>';
							r.message.task_results.forEach(function(result) {
								results_html += `<a href="#" class="search-result-item" data-type="task" data-id="${result.id}">
									<img src="/assets/frappe/images/icons/common/check.svg">
									<div class="result-details">
										<div class="result-name">${result.title}</div>
										<div class="result-meta">Due: ${result.due ? result.due : 'N/A'}</div>
									</div>
								</a>`;
							});
						}
						search_results.html(results_html).show();
					}
				}
			});
		} else {
			search_results.hide();
		}
	};

	search_input.on('keyup', trigger_search);
	search_source.on('change', trigger_search);
	search_from_date.on('change', trigger_search);
	search_to_date.on('change', trigger_search);

	search_results.on('click', 'a', function(e) {
		e.preventDefault();
		let type = $(this).data('type');
		let id = $(this).data('id');
		let name = $(this).data('name');
		let current_val = chat_input.val();
		if (type === 'doctype') {
			chat_input.val(current_val + ` @"${name}"`);
		} else if (type === 'gdrive') {
			chat_input.val(current_val + ` @gdrive/${id}`);
		} else if (type === 'gmail') {
			chat_input.val(current_val + ` @gmail/${id}`);
		}
		search_results.hide();
		search_input.val('');
	});

	save_conversation_btn.on('click', () => {
		frappe.prompt([
			{fieldname: 'title', fieldtype: 'Data', label: 'Conversation Title', reqd: 1}
		], (values) => {
			frappe.call({
				method: 'gemini_integration.api.save_conversation',
				args: {
					title: values.title,
					conversation: JSON.stringify(conversation)
				},
				callback: function(r) {
					if (r.message) {
						frappe.show_alert({message: 'Conversation saved successfully', indicator: 'green'});
					}
				}
			});
		}, 'Save Conversation');
	});

	view_conversations_btn.on('click', () => {
		frappe.call({
			method: 'gemini_integration.api.get_conversations',
			callback: function(r) {
				if (r.message) {
					let conversations_html = r.message.map(conv => `<p><a href="#" class="saved-conversation" data-name="${conv.name}">${conv.title}</a></p>`).join('');
					frappe.msgprint({
						title: 'Saved Conversations',
						message: conversations_html
					});
				}
			}
		});
	});

	$(document).on('click', '.saved-conversation', function(e) {
		e.preventDefault();
		let name = $(this).data('name');
		frappe.call({
			method: 'gemini_integration.api.get_conversation',
			args: {
				name: name
			},
			callback: function(r) {
				if (r.message) {
					conversation = JSON.parse(r.message);
					chat_history.empty();
					conversation.forEach(msg => add_to_history(msg.role, msg.text));
					frappe.hide_msgprint();
				}
			}
		});
	});

	let uploaded_file_uri = null;

	$(page.body).on('click', '.upload-btn', function() {
		$(page.body).find('.file-input').click();
	});

	$(page.body).on('change', '.file-input', function() {
		let file = this.files[0];
		if (file) {
			let form_data = new FormData();
			form_data.append('file', file);

			frappe.call({
				method: 'gemini_integration.api.upload_file',
				args: {
					file: file
				},
				callback: function(r) {
					if (r.message) {
						uploaded_file_uri = r.message.uri;
						frappe.show_alert({message: `File "${file.name}" uploaded successfully.`, indicator: 'green'});
					}
				}
			});
		}
	});
}


frappe.provide("gemini_integration");
gemini_integration.ProjectDashboard = class {
    constructor(wrapper) {
        this.wrapper = wrapper;
        this.page = wrapper.page;
        this.project_id = this.page.frm.doc.name;
        this.make();
        this.refresh();
    }

    make() {
        const container = `
            <div class="project-dashboard-container">
                <h4>AI Tools</h4>
                <div class="row">
                    <div class="col-md-6">
                        <div class="form-group">
                            <label>Task Generation Template</label>
                            <select class="form-control" name="task-template">
                                <option value="standard">Standard</option>
                                <option value="agile">Agile Sprint</option>
                                <option value="waterfall">Waterfall Phases</option>
                            </select>
                        </div>
                        <button class="btn btn-sm btn-primary generate-tasks-btn">Generate Tasks</button>
                    </div>
                    <div class="col-md-6">
                        <button class="btn btn-sm btn-secondary analyze-risks-btn">Analyze Risks</button>
                    </div>
                </div>
                <div class="results-area mt-4"></div>
            </div>
        `;
        this.dashboard = $(container).appendTo(this.wrapper.find('.dashboard-section'));
        this.bind_events();
    }

    bind_events() {
        this.dashboard.on('click', '.generate-tasks-btn', () => this.generate_tasks());
        this.dashboard.on('click', '.analyze-risks-btn', () => this.analyze_risks());
    }

    generate_tasks() {
        const template = this.dashboard.find('[name="task-template"]').val();
        frappe.call({
            method: 'gemini_integration.api.get_project_tasks',
            args: { project_id: this.project_id, template: template },
            callback: (r) => {
                if (r.message && !r.message.error) {
                    this.render_tasks(r.message);
                } else {
                    frappe.msgprint(r.message.error || "An error occurred.");
                }
            }
        });
    }

    analyze_risks() {
        frappe.call({
            method: 'gemini_integration.api.get_project_risks',
            args: { project_id: this.project_id },
            callback: (r) => {
                if (r.message && !r.message.error) {
                    this.render_risks(r.message);
                } else {
                    frappe.msgprint(r.message.error || "An error occurred.");
                }
            }
        });
    }

    render_tasks(tasks) {
        let html = '<h5>Generated Tasks</h5><ul class="list-group">';
        tasks.forEach(task => {
            html += `<li class="list-group-item">
                <strong>${task.subject}</strong>
                <p>${task.description}</p>
                <button class="btn btn-xs btn-default" onclick="gemini_integration.create_task('${this.project_id}', '${task.subject}', '${task.description}')">Create Task</button>
            </li>`;
        });
        html += '</ul>';
        this.dashboard.find('.results-area').html(html);
    }

    render_risks(risks) {
        let html = '<h5>Potential Risks</h5><ul class="list-group">';
        risks.forEach(risk => {
            html += `<li class="list-group-item">
                <strong>${risk.risk_name}</strong>
                <p>${risk.risk_description}</p>
                <button class="btn btn-xs btn-default" onclick="gemini_integration.create_risk('${risk.risk_name}', '${risk.risk_description}')">Create Risk</button>
            </li>`;
        });
        html += '</ul>';
        this.dashboard.find('.results-area').html(html);
    }

    refresh() {
        // Can be used to refresh data if needed
    }
};

gemini_integration.create_task = function(project, subject, description) {
    frappe.new_doc('Task', {
        project: project,
        subject: subject,
        description: description
    });
};

gemini_integration.create_risk = function(risk_name, risk_description) {
    frappe.new_doc('Risk', {
        risk_name: risk_name,
        description: risk_description
    });
};

frappe.pages['gemini-integration'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Gemini Integration',
		single_column: true
	});

	let input_area = page.add_field({
		label: "Prompt",
		fieldtype: "Text",
		fieldname: "prompt"
	});

	let model_selector = page.add_field({
        label: "Model",
        fieldtype: "Select",
        fieldname: "model",
        options: [
            "gemini-2.5-flash",
            "gemini-2.5-pro"
        ]
    });

	let response_area = page.add_field({
		label: "Response",
		fieldtype: "Text",
		fieldname: "response",
		read_only: true
	});

	page.add_button("Generate", () => {
		let prompt = input_area.get_value();
		let model = model_selector.get_value();
		if (prompt) {
			frappe.call({
				method: "gemini_integration.api.generate",
				args: {
					prompt: prompt,
					model: model
				},
				callback: function(r) {
					response_area.set_value(r.message);
				}
			});
		}
	});

	frappe.db.get_single_value('Gemini Settings', 'model').then(model => {
        if (model) {
            model_selector.set_value(model);
        }
    });
}
