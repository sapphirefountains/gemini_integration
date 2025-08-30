frappe.pages['gemini-chat'].on_page_load = function(wrapper) {
	let page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Gemini Chat',
		single_column: true
	});

    // Add showdown.js for Markdown rendering
    let script = document.createElement('script');
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/showdown/2.1.0/showdown.min.js';
    script.onload = () => {
        // Initialize the converter once the script is loaded
        page.converter = new showdown.Converter({
            simplifiedAutoLink: true,
            strikethrough: true,
            tables: true,
            openLinksInNewWindow: true
        });
    };
    document.head.appendChild(script);

	// Add custom styles
    let style = `
        .gemini-chat-container { display: flex; flex-direction: column; height: calc(100vh - 200px); }
        .gemini-chat-header { display: flex; justify-content: flex-end; padding: 10px; border-bottom: 1px solid #d1d8dd; }
        .gemini-chat-history { flex-grow: 1; overflow-y: auto; padding: 20px; }
        .gemini-chat-footer { padding: 10px; border-top: 1px solid #d1d8dd; display: flex; }
        .chat-message { margin-bottom: 15px; display: flex; flex-direction: column; }
        .user-message { align-items: flex-end; }
        .bot-message { align-items: flex-start; }
        .message-bubble { max-width: 80%; padding: 10px 15px; border-radius: 15px; }
        .user-message .message-bubble { background-color: #007bff; color: white; border-top-right-radius: 0; }
        .bot-message .message-bubble { background-color: #f1f0f0; border-top-left-radius: 0; }
        .bot-message .message-bubble h1, .bot-message .message-bubble h2, .bot-message .message-bubble h3 { margin-top: 0; }
        .bot-message .message-bubble ul, .bot-message .message-bubble ol { padding-left: 20px; }
        .bot-message .message-bubble p { margin-bottom: 5px; }
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
            default: "gemini-2.5-flash"
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
                // If markdown converter is loaded, convert text to HTML
                let html = page.converter.makeHtml(text);
                bubble.html(html);
            } else {
                // Fallback to plain text if showdown hasn't loaded
                bubble.text(text).css('white-space', 'pre-wrap');
            }
        } else {
            // User message is always plain text
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
                // Update the "thinking" message with the real response
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

    page.model_selector.on('change', () => {
        frappe.boot.user.last_gemini_model = page.model_selector.get_value();
    });
}

