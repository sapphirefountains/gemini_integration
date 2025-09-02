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
		.chat-input-area { display: flex; align-items: center; gap: 8px; }
		.chat-input-area textarea { flex-grow: 1; }
        .model-selector-area { margin-bottom: 15px; display: flex; justify-content: flex-end; align-items: center; gap: 10px; }
        .google-connect-btn { margin-left: auto; }
		.gemini-thoughts-area {
			margin-bottom: 15px;
			padding: 15px;
			background-color: #f3f4f6;
			border: 1px solid #e5e7eb;
			border-radius: 8px;
		}
		.gemini-thoughts-area h6 {
			margin-top: 0;
			margin-bottom: 10px;
			color: #4b5563;
			font-weight: 600;
		}
		.gemini-thoughts-area .thoughts-content {
			white-space: pre-wrap;
			word-wrap: break-word;
			max-height: 200px;
			overflow-y: auto;
			background-color: #fff;
			padding: 10px;
			border-radius: 4px;
			font-family: monospace;
			font-size: 12px;
		}
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
			<div class="gemini-thoughts-area" style="display: none;">
				<h6>Gemini's Thoughts (Context Provided to AI)</h6>
				<pre class="thoughts-content"></pre>
			</div>
			<div class="chat-history"></div>
			<div class="chat-input-area">
				<button class="btn btn-default btn-sm search-drive-btn" title="Search Google Drive">
					<i class="fa fa-google"></i> Drive
				</button>
				<button class="btn btn-default btn-sm search-mail-btn" title="Search Google Mail">
					<i class="fa fa-envelope"></i> Mail
				</button>
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
    let thoughts_area = $(page.body).find('.gemini-thoughts-area');
    let thoughts_content = $(page.body).find('.thoughts-content');
    let search_drive_btn = $(page.body).find('.search-drive-btn');
    let search_mail_btn = $(page.body).find('.search-mail-btn');
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

        thoughts_area.hide();

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
                if (typeof r.message === 'object' && r.message.response) {
                    if (r.message.thoughts) {
                        thoughts_content.text(r.message.thoughts);
                        thoughts_area.show();
                    }
                    add_to_history('gemini', r.message.response);
                } else {
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

    const open_search_modal = (search_type) => {
        let dialog = new frappe.ui.Dialog({
            title: `Search ${search_type}`,
            fields: [
                {
                    label: 'Search Query',
                    fieldname: 'search_query',
                    fieldtype: 'Data'
                },
                {
                    label: 'Results',
                    fieldname: 'results',
                    fieldtype: 'HTML'
                }
            ],
            primary_action_label: 'Search',
            primary_action: (values) => {
                let method = search_type === 'Google Drive' ? 'search_drive' : 'search_mail';
                frappe.call({
                    method: `gemini_integration.api.${method}`,
                    args: {
                        query: values.search_query
                    },
                    callback: function(r) {
                        let results_html = '';
                        if (r.message && r.message.length > 0) {
                            results_html += '<ul class="list-group">';
                            r.message.forEach(item => {
                                let title = search_type === 'Google Drive' ? item.name : item.payload.headers.find(h => h.name === 'Subject').value;
                                let id = item.id;
                                results_html += `<li class="list-group-item d-flex justify-content-between align-items-center">
                                                    <a href="#" data-id="${id}" data-type="${search_type}">${title}</a>
                                                    <button class="btn btn-primary btn-sm analyze-btn" data-id="${id}">Analyze</button>
                                                </li>`;
                            });
                            results_html += '</ul>';
                        } else {
                            results_html = 'No results found.';
                        }
                        dialog.get_field('results').$wrapper.html(results_html);
                    }
                });
            }
        });

        dialog.show();

        dialog.get_field('results').$wrapper.on('click', 'a', function(e) {
            e.preventDefault();
            let id = $(this).data('id');
            let type = $(this).data('type');
            let ref = type === 'Google Drive' ? `@gdrive/${id}` : `@gmail/${id}`;
            chat_input.val(chat_input.val() + ' ' + ref);
            dialog.hide();
        });

        dialog.get_field('results').$wrapper.on('click', '.analyze-btn', function(e) {
            e.preventDefault();
            let id = $(this).data('id');
            frappe.call({
                method: 'gemini_integration.api.get_drive_file_for_analysis',
                args: {
                    file_id: id
                },
                callback: function(r) {
                    if (r.message) {
                        let ref = `@gdrive/${r.message.name}`;
                        chat_input.val(chat_input.val() + ' ' + ref);
                        dialog.hide();
                    }
                }
            });
        });
    };

    search_drive_btn.on('click', () => {
        open_search_modal('Google Drive');
    });

    search_mail_btn.on('click', () => {
        open_search_modal('Google Mail');
    });

    const add_to_history = (role, text) => {
        let bubble = $(`<div class="chat-bubble ${role}"></div>`);
        
        if (text) {
            if (window.showdown) {
                let converter = new showdown.Converter();
                let html = converter.makeHtml(text);
                bubble.html(html);
            } else {
                bubble.text(text);
            }
        }
        
        chat_history.append(bubble);
        chat_history.scrollTop(chat_history[0].scrollHeight);
        conversation.push({role: role, text: text});
    };
    
    let script_url = "https://cdnjs.cloudflare.com/ajax/libs/showdown/2.1.0/showdown.min.js";
    let script = document.createElement('script');
    script.type = 'text/javascript';
    script.src = script_url;
    document.head.appendChild(script);

    send_btn.on('click', send_message);

    // --- THIS IS THE FIX for the Enter key ---
    // Use 'keydown' to better handle modifier keys like Shift.
    chat_input.on('keydown', function(e) {
        // Only send the message if Shift and Enter are pressed together.
        if (e.key === 'Enter' && e.shiftKey) {
            e.preventDefault(); // Prevent default action (like adding a newline)
            send_message();
        }
    });
}
