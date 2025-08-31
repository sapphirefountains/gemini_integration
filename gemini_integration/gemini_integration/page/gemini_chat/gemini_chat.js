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
        .chat-bubble.gemini img { max-width: 100%; border-radius: 8px; margin-top: 8px; }
		.chat-input-area { display: flex; align-items: center; gap: 8px; }
		.chat-input-area textarea { flex-grow: 1; }
        .attachment-preview { margin-top: 10px; }
        .attachment-preview img { max-width: 100px; max-height: 100px; border-radius: 5px; }
        .model-selector-area { margin-bottom: 15px; display: flex; justify-content: flex-end; align-items: center; gap: 10px; }
        .google-connect-btn { margin-left: auto; }
	`;
	$('<style>').text(styles).appendTo('head');

	let html = `
		<div class="gemini-chat-wrapper">
			<div class="model-selector-area">
                <button class="btn btn-secondary btn-sm google-connect-btn">Connect Google Account</button>
            </div>
			<div class="chat-history"></div>
			<div class="chat-input-area">
				<textarea class="form-control" rows="2" placeholder="Type your message..."></textarea>
                <label for="file-upload" class="btn btn-default" style="cursor: pointer;">
                    <i class="fa fa-paperclip"></i>
                </label>
                <input type="file" id="file-upload" style="display: none;" accept="image/*">
				<button class="btn btn-primary send-btn">Send</button>
			</div>
            <div class="attachment-preview"></div>
		</div>
	`;
	$(page.body).html(html);

    let chat_history = $(page.body).find('.chat-history');
    let chat_input = $(page.body).find('.chat-input-area textarea');
    let send_btn = $(page.body).find('.send-btn');
    let file_input = $(page.body).find('#file-upload');
    let attachment_preview = $(page.body).find('.attachment-preview');
    let google_connect_btn = $(page.body).find('.google-connect-btn');
    let conversation = [];
    let current_file_url = null;

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

    file_input.on('change', function() {
        let file = this.files[0];
        if (file) {
            frappe.file_uploader.upload_file(file, {
                callback: (attachment) => {
                    current_file_url = attachment.file_url;
                    attachment_preview.html(`<img src="${current_file_url}" alt="Attachment Preview">`);
                }
            });
        }
    });

    const send_message = () => {
        let prompt = chat_input.val().trim();
        if (!prompt && !current_file_url) return;

        add_to_history('user', prompt, current_file_url);
        chat_input.val('');
        attachment_preview.html('');
        
        frappe.show_alert({message: "Getting response from Gemini...", indicator: "blue"}, 5);

        frappe.call({
            method: 'gemini_integration.api.chat',
            args: {
                prompt: prompt,
                model: page.model_selector.get_value(),
                conversation: JSON.stringify(conversation),
                file_url: current_file_url
            },
            callback: function(r) {
                frappe.hide_global_message();
                let response_text = r.message;
                add_to_history('gemini', response_text);
            },
            error: function(r) {
                frappe.hide_global_message();
                let error_msg = r.message ? r.message.replace(/</g, "&lt;").replace(/>/g, "&gt;") : "An unknown error occurred.";
                frappe.msgprint({
                    title: __('Error'),
                    indicator: 'red',
                    message: error_msg
                });
            }
        });
        current_file_url = null;
    };

    const add_to_history = (role, text, file_url = null) => {
        let bubble = $(`<div class="chat-bubble ${role}"></div>`);
        
        if (text) {
            if (window.showdown) {
                let converter = new showdown.Converter();
                let html = converter.makeHtml(text);
                bubble.html(html);
            } else {
                bubble.text(text); // Fallback to plain text if showdown isn't loaded
            }
        }

        if (file_url) {
            let img = $(`<img src="${file_url}" alt="User attachment">`);
            bubble.append(img);
        }
        
        chat_history.append(bubble);
        chat_history.scrollTop(chat_history[0].scrollHeight);
        conversation.push({role: role, text: text});
    };
    
    // Use the standard, robust method for adding an external script
    let script_url = "https://cdnjs.cloudflare.com/ajax/libs/showdown/2.1.0/showdown.min.js";
    let script = document.createElement('script');
    script.type = 'text/javascript';
    script.src = script_url;
    document.head.appendChild(script);

    send_btn.on('click', send_message);
    chat_input.on('keypress', function(e) {
        if (e.which === 13 && !e.shiftKey) {
            e.preventDefault();
            send_message();
        }
    });
}
