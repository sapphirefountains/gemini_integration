frappe.pages['gemini-chat'].on_page_load = function(wrapper) {
    let page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Gemini Chat',
        single_column: true
    });

    // Add custom styles for the chat interface
    const style = `
        .gemini-chat-wrapper { display: flex; flex-direction: column; height: calc(100vh - 200px); }
        .gemini-chat-history { flex-grow: 1; overflow-y: auto; padding: 20px; border: 1px solid #d1d8dd; border-radius: 6px; }
        .chat-message { margin-bottom: 15px; display: flex; flex-direction: column; }
        .user-message { align-self: flex-end; background-color: #4796f7; color: white; border-radius: 12px 12px 0 12px; padding: 10px 15px; max-width: 70%; }
        .gemini-message { align-self: flex-start; background-color: #f1f1f1; color: #333; border-radius: 12px 12px 12px 0; padding: 10px 15px; max-width: 70%; }
        .gemini-message pre { background-color: #2d2d2d; color: #f8f8f2; padding: 10px; border-radius: 4px; white-space: pre-wrap; word-wrap: break-word; }
        .gemini-message code { font-family: 'Monaco', 'Menlo', 'Courier New', monospace; }
        .gemini-message a { color: #007bff; }
        .chat-input-area { display: flex; padding-top: 15px; }
        .chat-input { flex-grow: 1; margin-right: 10px; }
        .attachment-preview { margin-top: 10px; max-width: 200px; max-height: 200px; border-radius: 6px; }
        #gemini-chat-input { resize: none; }
    `;
    // Correctly add the style to the document head
    $('<style>').text(style).appendTo('head');


    // Main HTML structure for the chat page
    const chat_html = `
        <div class="gemini-chat-container">
            <div class="row">
                <div class="col-md-9">
                    <h3 id="connection-status">Connecting to your world...</h3>
                </div>
                <div class="col-md-3 text-right" id="google-controls"></div>
            </div>
            <div class="gemini-chat-wrapper mt-4">
                <div class="gemini-chat-history" id="gemini-chat-history">
                    <div class="gemini-message">
                        Hello! How can I help you today? You can ask me about documents in ERPNext by using '@' (e.g., @PRJ-00183) or connect your Google Account to ask about your emails, files, and calendar events.
                    </div>
                </div>
                <div class="chat-input-area">
                    <div class="frappe-control" data-fieldtype="Text" data-fieldname="chat-input" style="flex-grow: 1;">
                         <textarea class="form-control" id="gemini-chat-input" rows="2" placeholder="Type your message..."></textarea>
                    </div>
                    <div class="attachment-btn-wrapper ml-2">
                        <label for="file-upload" class="btn btn-default" style="margin-bottom: 0;">
                            <i class="fa fa-paperclip"></i>
                        </label>
                        <input id="file-upload" type="file" style="display: none;">
                    </div>
                    <button class="btn btn-primary ml-2" id="send-message-btn">Send</button>
                </div>
                <div id="attachment-preview-container"></div>
            </div>
        </div>
    `;

    // Correctly and safely append the HTML structure to the page body
    $(page.body).append(chat_html);


    let conversation_history = [];
    let attached_file_url = null;
    const chat_history_div = $("#gemini-chat-history");
    const send_button = $("#send-message-btn");
    const chat_input = $("#gemini-chat-input");
    const file_upload = $("#file-upload");
    const attachment_preview_container = $("#attachment-preview-container");
    const google_controls_div = $("#google-controls");
    const connection_status_h3 = $("#connection-status");


    function update_ui_for_google_status(is_connected) {
        if (is_connected) {
            connection_status_h3.text("Connected to Google");
            google_controls_div.html('<button class="btn btn-danger btn-sm" id="disconnect-google-btn">Disconnect Google Account</button>');
        } else {
            connection_status_h3.text("Connect your Google Account to ask about your emails, files, and calendar.");
            google_controls_div.html('<button class="btn btn-primary" id="connect-google-btn">Connect Google Account</button>');
        }
    }
    
    frappe.call({
        method: "gemini_integration.api.check_google_integration",
        callback: function(r) {
            update_ui_for_google_status(r.message);
        }
    });


    // Event listener for the connect button
    google_controls_div.on('click', '#connect-google-btn', function() {
        frappe.call({
            method: "gemini_integration.api.get_auth_url",
            callback: function(r) {
                if (r.message) {
                    window.open(r.message, "_blank");
                }
            }
        });
    });


    function add_message_to_history(sender, message, file_url=null) {
        let message_html = `<div class="${sender}-message">`;
        if (file_url) {
            message_html += `<img src="${file_url}" class="attachment-preview"><br>`;
        }

        if (sender === 'gemini') {
            const converter = new showdown.Converter();
            message_html += converter.makeHtml(message);
        } else {
            message_html += message.replace(/\n/g, '<br>');
        }
        message_html += `</div>`;
        
        const message_div = $(`<div class="chat-message">${message_html}</div>`);
        chat_history_div.append(message_div);
        chat_history_div.scrollTop(chat_history_div[0].scrollHeight);
    }

    function send_message() {
        const prompt = chat_input.val().trim();
        if (!prompt && !attached_file_url) return;

        add_message_to_history('user', prompt, attached_file_url);
        chat_input.val('');
        attachment_preview_container.empty();
        const temp_file_url = attached_file_url;
        attached_file_url = null;

        frappe.show_alert({ message: 'Getting response from Gemini...', indicator: 'blue' });

        frappe.call({
            method: "gemini_integration.api.chat",
            args: {
                prompt: prompt,
                model: "gemini-1.5-flash", // Update as needed
                conversation: conversation_history,
                file_url: temp_file_url
            },
            callback: function(r) {
                frappe.hide_alert();
                const response = r.message;
                conversation_history.push({ role: "user", parts: [prompt] });
                conversation_history.push({ role: "model", parts: [response] });
                add_message_to_history('gemini', response);
            },
            error: function(r) {
                frappe.hide_alert();
                frappe.msgprint({
                    title: __('Error'),
                    indicator: 'red',
                    message: r.message || __("An unknown error occurred.")
                });
            }
        });
    }

    send_button.on('click', send_message);
    chat_input.on('keypress', function(e) {
        if (e.which == 13 && !e.shiftKey) {
            e.preventDefault();
            send_message();
        }
    });

    file_upload.on('change', function(event) {
        const file = event.target.files[0];
        if (file) {
            const reader = new FileReader();
            reader.onload = function(e) {
                const preview = `<img src="${e.target.result}" alt="Attachment Preview" class="attachment-preview">`;
                attachment_preview_container.html(preview);
            };
            reader.readAsDataURL(file);

            frappe.upload.upload_file(file, {
                callback: (attachment) => {
                    attached_file_url = attachment.file_url;
                },
                onerror: () => {
                    frappe.msgprint(__("File upload failed."));
                }
            });
        }
    });

    // Load showdown library for Markdown rendering
    frappe.require("https://cdnjs.cloudflare.com/ajax/libs/showdown/1.9.1/showdown.min.js");
};
