frappe.pages['gemini-chat'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Gemini Chat',
        single_column: true
    });

    // Add custom CSS for chat interface
    const style = `
        .gemini-chat-container {
            display: flex;
            flex-direction: column;
            height: calc(100vh - 200px);
            border: 1px solid #d1d8dd;
            border-radius: 6px;
            overflow: hidden;
        }
        .gemini-chat-header {
            padding: 10px;
            border-bottom: 1px solid #d1d8dd;
            display: flex;
            align-items: center;
            background-color: #f5f7fa;
        }
        .gemini-chat-header .model-selector {
            margin-left: auto;
        }
        .gemini-chat-messages {
            flex-grow: 1;
            padding: 20px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            background-color: #ffffff;
        }
        .chat-message {
            max-width: 70%;
            padding: 10px 15px;
            border-radius: 18px;
            margin-bottom: 10px;
            position: relative;
            word-wrap: break-word;
        }
        .chat-message.user {
            background-color: #007bff;
            color: white;
            align-self: flex-end;
            border-bottom-right-radius: 4px;
        }
        .chat-message.bot {
            background-color: #e9ecef;
            color: #333;
            align-self: flex-start;
            border-bottom-left-radius: 4px;
        }
        .chat-message.bot.typing {
            color: #6c757d;
        }
        .gemini-chat-input-area {
            display: flex;
            padding: 10px;
            border-top: 1px solid #d1d8dd;
            background-color: #f5f7fa;
        }
        .gemini-chat-input-area textarea {
            flex-grow: 1;
            border-radius: 6px;
            resize: none;
            border: 1px solid #d1d8dd;
            padding: 8px 12px;
            font-size: 14px;
        }
        .gemini-chat-input-area button {
            margin-left: 10px;
        }
    `;
    // Fix: Use jQuery to append style to the head, as frappe.dom.create_style is not a function in v15
    $('<style>').text(style).appendTo('head');


    // Main container
    let container = $(`<div class="gemini-chat-container"></div>`).appendTo(page.body);
    let header = $(`<div class="gemini-chat-header"><b>Model:</b></div>`).appendTo(container);
    let messages_container = $(`<div class="gemini-chat-messages"></div>`).appendTo(container);
    let input_area = $(`<div class="gemini-chat-input-area"></div>`).appendTo(container);

    // Model Selector
    let model_selector_wrapper = $(`<div class="model-selector"></div>`).appendTo(header);
    let model_selector = page.add_field({
        parent: model_selector_wrapper,
        fieldtype: "Select",
        fieldname: "model",
        options: [
            "gemini-2.5-flash",
            "gemini-2.5-pro"
        ],
        input_class: 'input-sm'
    });
    frappe.db.get_single_value('Gemini Settings', 'model').then(model => {
        if (model) {
            model_selector.set_value(model);
        }
    });

    // Input Textarea and Button
    let text_input = $(`<textarea class="form-control" rows="2" placeholder="Type your message... e.g., Summarize @PROJ-00413"></textarea>`).appendTo(input_area);
    let send_button = $(`<button class="btn btn-primary">Send</button>`).appendTo(input_area);

    function add_message(text, sender) {
        // Sanitize text before adding to DOM to prevent XSS, then convert newlines
        const sanitized_text = $('<div>').text(text).html().replace(/\n/g, '<br>');
        let message_el = $(`<div class="chat-message ${sender}">${sanitized_text}</div>`);
        messages_container.append(message_el);
        messages_container.scrollTop(messages_container[0].scrollHeight);
    }

    function show_typing_indicator() {
        let typing_el = $(`<div class="chat-message bot typing"><i>Typing...</i></div>`);
        typing_el.attr('id', 'typing-indicator');
        messages_container.append(typing_el);
        messages_container.scrollTop(messages_container[0].scrollHeight);
    }

    function remove_typing_indicator() {
        $('#typing-indicator').remove();
    }

    function send_message() {
        let prompt = text_input.val().trim();
        if (!prompt) return;

        add_message(prompt, 'user');
        text_input.val('');
        show_typing_indicator();

        frappe.call({
            method: "gemini_integration.api.chat",
            args: {
                prompt: prompt,
                model: model_selector.get_value(),
                conversation: null // For future stateful conversation
            },
            callback: function(r) {
                remove_typing_indicator();
                if (r.message) {
                    add_message(r.message, 'bot');
                }
            },
            error: function(r) {
                remove_typing_indicator();
                frappe.msgprint(__('An error occurred. Please check the console.'));
                console.error(r);
            }
        });
    }

    send_button.on('click', send_message);
    text_input.on('keypress', function(e) {
        if (e.which == 13 && !e.shiftKey) {
            e.preventDefault();
            send_message();
        }
    });

    add_message("Hello! How can I help you today? You can reference documents in ERPNext by using '@', for example: @PROJ-00413 or @\"Test Customer\".", 'bot');
};


