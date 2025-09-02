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
	`;
	$('<style>').text(styles).appendTo('head');

	let html = `
		<div class="gemini-chat-wrapper">
			<div class="model-selector-area">
				<button class="btn btn-default btn-sm help-btn" title="Help">
					<i class="fa fa-question-circle"></i>
				</button>
                <button class="btn btn-secondary btn-sm google-connect-btn">Connect Google Account</button>
            </div>
			<div class="search-results" style="display: none;"></div>
			<div class="chat-history"></div>
			<div class="chat-input-area">
				<input type="text" class="form-control search-input" placeholder="Search for DocTypes, Google Drive files, and Gmail messages...">
			</div>
			<div class="chat-input-area">
				<textarea class="form-control" rows="2" placeholder="Type your message... (Shift + Enter to send)"></textarea>
				<button class="btn btn-primary send-btn">Send</button>
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
				<h4>How to Reference Data</h4>
				<p>You can reference data from ERPNext and Google Workspace directly in your chat messages.</p>
				
				<h5>ERPNext Documents</h5>
				<p>Use <code>@DocType-ID</code> or <code>@"Doc Name"</code> to reference any document.</p>
				<ul>
					<li><code>What is the status of @PRJ-00183?</code></li>
					<li><code>Summarize customer @"Valley Fair"</code></li>
				</ul>

				<h5>Google Drive & Gmail</h5>
				<p>Use <code>@gdrive/file_id</code> or <code>@gmail/message_id</code> to reference specific items.</p>
				<ul>
					<li><code>Summarize the file @gdrive/1a2b3c...</code></li>
					<li><code>What was the outcome of email @gmail/a1b2c3...?</code></li>
				</ul>

				<h5>General Search</h5>
				<p>For general queries, the system will automatically search Google Drive and Gmail. You can also use keywords like <code>email</code>, <code>drive</code>, or <code>calendar</code> to focus the search.</p>
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
                conversation: JSON.stringify(conversation)
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

	search_input.on('keyup', function() {
		let query = $(this).val();
		if (query.length > 2) {
			frappe.call({
				method: 'gemini_integration.api.search',
				args: {
					query: query
				},
				callback: function(r) {
					if (r.message) {
						let results_html = '';
						if (r.message.doctype_results.length > 0) {
							results_html += '<h5>DocTypes</h5>';
							r.message.doctype_results.forEach(function(result) {
								results_html += `<a href="#" class="list-group-item list-group-item-action" data-type="doctype" data-name="${result.name}">${result.name}</a>`;
							});
						}
						if (r.message.drive_results.length > 0) {
							results_html += '<h5>Google Drive</h5>';
							r.message.drive_results.forEach(function(result) {
								results_html += `<a href="#" class="list-group-item list-group-item-action" data-type="gdrive" data-id="${result.id}">${result.name}</a>`;
							});
						}
						if (r.message.gmail_results.length > 0) {
							results_html += '<h5>Gmail</h5>';
							r.message.gmail_results.forEach(function(result) {
								results_html += `<a href="#" class="list-group-item list-group-item-action" data-type="gmail" data-id="${result.id}">${result.subject}</a>`;
							});
						}
						search_results.html(results_html).show();
					}
				}
			});
		} else {
			search_results.hide();
		}
	});

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

