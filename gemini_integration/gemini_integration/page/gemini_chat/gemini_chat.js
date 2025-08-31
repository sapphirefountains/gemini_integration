frappe.pages['gemini-chat'].on_page_load = function(wrapper) {
	let page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Gemini Chat',
		single_column: true
	});

    let google_button_html = `<button id="google-connect-btn" class="btn btn-default btn-sm">
                                <i class="fa fa-google"></i> Connect Google Account
                              </button>`;

    let container = $(`
        <div class="gemini-chat-container" style="display: flex; flex-direction: column; height: calc(100vh - 160px);">
            <div class="gemini-chat-header" style="display: flex; justify-content: space-between; align-items: center; padding-bottom: 10px;">
                <div class="google-connect-wrapper">${google_button_html}</div>
                <div class="model-selector-wrapper" style="width: 250px;"></div>
            </div>
            <div class="gemini-chat-history" style="flex-grow: 1; overflow-y: auto; border: 1px solid #d1d8dd; border-radius: 6px; padding: 10px;"></div>
            <div class="gemini-chat-input-area" style="padding-top: 10px; display: flex; align-items: center;">
                <textarea class="form-control" placeholder="Type your message..."></textarea>
                <button class="btn btn-primary" style="margin-left: 10px;">Send</button>
                 <button class="btn btn-default btn-attach" style="margin-left: 5px;" title="Attach File">
                    <i class="fa fa-paperclip"></i>
                </button>
                <input type="file" style="display: none;" id="file-upload-input" />
            </div>
            <div class="gemini-chat-attachment-preview" style="padding-top: 5px; max-width: 200px;"></div>
        </div>
    `).appendTo(page.body);

    let chat_history = container.find(".gemini-chat-history");
    let input_area = container.find(".gemini-chat-input-area textarea");
    let send_button = container.find(".gemini-chat-input-area button.btn-primary");
    let attach_button = container.find(".btn-attach");
    let file_input = container.find("#file-upload-input");
    let attachment_preview = container.find(".gemini-chat-attachment-preview");

    let conversation_history = [];
    let attached_file_url = null;

    // --- GOOGLE AUTH LOGIC ---
    function update_google_button_state() {
        frappe.call({
            method: "gemini_integration.api.check_google_integration",
            callback: (r) => {
                let btn = container.find("#google-connect-btn");
                if (r.message) {
                    btn.removeClass("btn-default").addClass("btn-success").html(`<i class="fa fa-check"></i> Google Account Connected`);
                    btn.prop('disabled', true);
                }
            }
        });
    }

    container.on("click", "#google-connect-btn", () => {
        let btn = container.find("#google-connect-btn");
        if (btn.prop('disabled')) return;

        frappe.call({
            method: "gemini_integration.api.get_auth_url",
            callback: (r) => {
                if (r.message) {
                    // Open in a new tab for the user to authenticate
                    window.open(r.message, "_blank");
                }
            }
        });
    });

    update_google_button_state();
    // Check every 10 seconds if the user has completed authentication in the other tab
    setInterval(update_google_button_state, 10000);

    // --- The rest of your chat logic (send_message, add_message, etc.) remains here ---
    // Make sure to copy the rest of your working chat JS code below this point.
}

        .bot-message .message-bubble a { color: #007bff; }
        #gemini-chat-input { flex-grow: 1; margin-right: 10px; }
    `;
    let style_element = document.createElement('style');
    style_element.innerText = style;
    document.head.appendChild(style_element);


	let container = $(`
		<div class="gemini-chat-container">
			<div class="gemini-chat-header">
				<div class="model-selector-wrapper" style="width: 200px;"></div>
			</div>
			<div class="gemini-chat-history"></div>
			<div class="gemini-chat-footer">
				<input type="text" id="gemini-chat-input" class="form-control" placeholder="Type your message...">
				<button id="gemini-send-btn" class="btn btn-primary">Send</button>
			</div>
		</div>
	`).appendTo(page.body);

	page.model_selector = frappe.ui.form.make_control({
        parent: container.find('.model-selector-wrapper'),
        df: {
            fieldname: "gemini_model",
            label: "Model",
            fieldtype: "Select",
            options: "gemini-2.5-flash\ngemini-2.5-pro",
            default: "gemini-2.5-flash",
            // CORRECT WAY TO HANDLE CHANGE EVENT
            change: function() {
                // 'this' refers to the control object itself
                frappe.boot.user.last_gemini_model = this.get_value();
            }
        },
        render_input: true,
    });
    page.model_selector.set_value(frappe.boot.user.last_gemini_model || "gemini-2.5-flash");


	function add_message(sender, text) {
		let history = container.find('.gemini-chat-history');
		let message_class = sender === 'user' ? 'user-message' : 'bot-message';
		let message_el = $(`<div class="chat-message ${message_class}"><div class="message-bubble"></div></div>`);
        
        let bubble = message_el.find('.message-bubble');

        if (sender === 'bot') {
            if (page.converter) {
                let html = page.converter.makeHtml(text);
                bubble.html(html);
            } else {
                bubble.text(text).css('white-space', 'pre-wrap');
            }
        } else {
            bubble.text(text);
        }
		
		history.append(message_el);
		history.scrollTop(history[0].scrollHeight);
        return message_el;
	}

	function send_message() {
		let input = container.find('#gemini-chat-input');
		let prompt = input.val();
		if (!prompt) return;

		add_message('user', prompt);
		input.val('');
        
        let thinking_el = add_message('bot', '...');

		frappe.call({
			method: 'gemini_integration.api.chat',
			args: {
				prompt: prompt,
				model: page.model_selector.get_value()
			},
			callback: function(r) {
                let bubble = thinking_el.find('.message-bubble');
                if (page.converter) {
                    let html = page.converter.makeHtml(r.message);
                    bubble.html(html);
                } else {
				    bubble.text(r.message).css('white-space', 'pre-wrap');
                }
			},
            error: function(r) {
                let bubble = thinking_el.find('.message-bubble');
                let error_msg = "Sorry, an error occurred. Please check the Error Log for details.";
                if (r.message && r.message.message) {
                    error_msg = r.message.message;
                }
                bubble.text(error_msg).css('color', 'red');
            }
		});
	}

	container.find('#gemini-send-btn').on('click', send_message);
	container.find('#gemini-chat-input').on('keypress', function(e) {
		if (e.which === 13) {
			send_message();
		}
	});

    // The incorrect .on() handler has been removed from here
}

