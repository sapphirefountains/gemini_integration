/* global showdown */
frappe.pages["gemini-chat"].on_page_load = function (wrapper) {
	let page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Gemini Chat",
		single_column: true,
	});

	let currentConversation = null;

	const styles = `
        .gemini-chat-container { display: flex; height: 75vh; position: relative; overflow: hidden; }
        .conversations-sidebar { width: 250px; border-right: 1px solid #d1d5db; padding: 15px; display: flex; flex-direction: column; transition: transform 0.3s ease; }
        .sidebar-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        #new-chat-button { margin-left: 10px; }
        #conversations-list { list-style: none; padding: 0; margin: 0; overflow-y: auto; }
        #conversations-list .list-group-item { cursor: pointer; padding: 10px; border-radius: 5px; margin-bottom: 5px; }
        #conversations-list .list-group-item:hover { background-color: #f0f0f0; }
        #conversations-list .list-group-item.active { background-color: #e0e0e0; font-weight: bold; }

        .gemini-chat-wrapper { flex-grow: 1; display: flex; flex-direction: column; max-width: 900px; margin: 0 auto; width: 100%; }
        .chat-header { padding: 10px 0; display: flex; justify-content: space-between; align-items: center; }
        .chat-history { flex-grow: 1; overflow-y: auto; border: 1px solid #d1d5db; border-radius: 8px; padding: 16px; margin-bottom: 16px; background-color: #f9fafb; }
        .chat-bubble { max-width: 80%; padding: 12px 16px; border-radius: 12px; margin-bottom: 12px; word-wrap: break-word; }
        .chat-bubble.user { background-color: #3b82f6; color: white; margin-left: auto; border-bottom-right-radius: 0; }
        .chat-bubble.gemini { background-color: #e5e7eb; color: #1f2937; margin-right: auto; border-bottom-left-radius: 0; }
        .chat-bubble.thoughts { background-color: #f3f4f6; border: 1px solid #e5e7eb; color: #4b5563; width: 100%; max-width: 100%; margin-bottom: 12px; }
        .chat-bubble.thoughts h6 { margin-top: 0; margin-bottom: 10px; font-weight: 600; }
        .chat-bubble.thoughts pre { white-space: pre-wrap; word-wrap: break-word; max-height: 200px; overflow-y: auto; background-color: #fff; padding: 10px; border-radius: 4px; font-family: monospace; font-size: 12px; }

        .clarification-container { padding: 10px; }
        .clarification-container .list-group-item { display: flex; align-items: center; }
        .clarification-container .list-group-item input { margin-right: 10px; }
        .clarification-submit-btn { margin-top: 10px; }

        .chat-input-area { display: flex; align-items: center; gap: 8px; }
        .chat-input-area textarea { flex-grow: 1; }
        .model-selector-area { margin-bottom: 15px; display: flex; justify-content: flex-end; align-items: center; gap: 10px; }
        .google-connect-btn { margin-left: auto; }
        .sidebar-toggle-btn { display: none; }

        @media (max-width: 768px) {
            .sidebar-toggle-btn { display: inline-block; }
            .conversations-sidebar { position: absolute; top: 0; left: 0; height: 100%; z-index: 10; background: #fff; transform: translateX(-100%); }
            .gemini-chat-container.sidebar-open .conversations-sidebar { transform: translateX(0); }
            .gemini-chat-wrapper { max-width: 100%; }
        }
    `;
	$("<style>").text(styles).appendTo("head");

	let html = `
        <div class="gemini-chat-container">
            <div class="conversations-sidebar">
                <div class="sidebar-header">
                    <h4>Conversations</h4>
                    <button id="new-chat-button" class="btn btn-primary btn-sm">New</button>
                </div>
                <ul id="conversations-list" class="list-group"></ul>
            </div>
            <div class="gemini-chat-wrapper">
                <div class="chat-header">
                     <button class="btn btn-default btn-sm sidebar-toggle-btn">
                        <i class="fa fa-bars"></i>
                    </button>
                    <div class="model-selector-area flex-grow-1">
                         <button class="btn btn-default btn-sm help-btn" title="Help">
                            <i class="fa fa-question-circle"></i>
                        </button>
                        <button class="btn btn-secondary btn-sm google-connect-btn">Connect Google Account</button>
                    </div>
                </div>
                <div class="chat-history"></div>
                <div class="chat-input-area">
                    <textarea class="form-control" rows="2" placeholder="Type your message... (Shift + Enter to send)"></textarea>
                    <button class="btn btn-primary send-btn">Send</button>
                </div>
            </div>
        </div>
    `;
	$(page.body).html(html);

	let chat_history = $(page.body).find(".chat-history");
	let chat_input = $(page.body).find(".chat-input-area textarea");
	let send_btn = $(page.body).find(".send-btn");
	let google_connect_btn = $(page.body).find(".google-connect-btn");
	let help_btn = $(page.body).find(".help-btn");
	let new_chat_btn = $(page.body).find("#new-chat-button");
	let conversations_list = $(page.body).find("#conversations-list");
	let sidebar_toggle_btn = $(page.body).find(".sidebar-toggle-btn");
	let gemini_chat_container = $(page.body).find(".gemini-chat-container");
	let conversation = [];

	page.model_selector = frappe.ui.form.make_control({
		parent: $(page.body).find(".model-selector-area"),
		df: {
			fieldtype: "Select",
			label: "Model",
			options: [
				{ label: "Gemini 2.5 Flash", value: "gemini-2.5-flash" },
				{ label: "Gemini 2.5 Pro", value: "gemini-2.5-pro" },
			],
			change: function () {
				try {
					localStorage.setItem("gemini_last_model", this.get_value());
				} catch (e) {
					console.error("localStorage is not available.", e);
				}
			},
		},
		render_input: true,
	});

	try {
		page.model_selector.set_value(
			localStorage.getItem("gemini_last_model") || "gemini-1.5-flash"
		);
	} catch (e) {
		console.error("localStorage is not available. Using default model.", e);
		page.model_selector.set_value("gemini-1.5-flash");
	}

	frappe.call({
		method: "gemini_integration.api.check_google_integration",
		callback: (r) => {
			if (r.message)
				google_connect_btn
					.text("Google Account Connected")
					.removeClass("btn-secondary")
					.addClass("btn-success");
		},
	});

	google_connect_btn.on("click", () => {
		frappe.call({
			method: "gemini_integration.api.get_auth_url",
			callback: (r) => {
				if (r.message) window.open(r.message, "_blank");
			},
		});
	});

	sidebar_toggle_btn.on("click", () => gemini_chat_container.toggleClass("sidebar-open"));

	help_btn.on("click", () => {
		const help_html = `
            <div>
                <h4>How to Reference Data</h4>
                <p>Use the <code>@</code> symbol to reference data from ERPNext or search Google Workspace.</p>
                <h5>ERPNext Documents</h5>
                <p>Use <code>@DocType-ID</code> or <code>@"Doc Name"</code> to find specific documents.</p>
                <ul><li><code>What is the status of @PRJ-00183?</code></li><li><code>Summarize customer @"Valley Fair"</code></li></ul>
                <h5>Google Workspace</h5>
                <p>Include keywords like <code>email</code>, <code>drive</code>, <code>file</code>, or <code>calendar</code> in your prompt. If multiple items are found, I'll ask you to clarify.</p>
                <ul><li><code>Find emails about the "Q3 marketing budget"</code></li><li><code>Search my drive for "2024 Roadmap"</code></li></ul>
            </div>`;
		frappe.msgprint({
			title: __("Help: Referencing Data"),
			indicator: "blue",
			message: help_html,
		});
	});

	const send_message = (prompt) => {
		if (!prompt) {
			prompt = chat_input.val().trim();
			if (!prompt) return;
		}

		add_to_history("user", prompt);
		chat_input.val("");

		let loading = frappe.msgprint({
			message: __("Getting response from Gemini..."),
			indicator: "blue",
			title: __("Please Wait"),
		});

		frappe.call({
			method: "gemini_integration.api.chat",
			args: {
				prompt: prompt,
				model: page.model_selector.get_value(),
				conversation_id: currentConversation,
			},
			callback: function (r) {
				loading.hide();
				if (r.message) {
					// The response can be a string (for info messages) or an object
					if (typeof r.message === "string") {
						add_to_history("gemini", r.message);
						return;
					}

					if (r.message.thoughts) add_to_history("thoughts", r.message.thoughts);

					// Check for suggestions, which indicates clarification is needed
					if (r.message.suggestions && r.message.suggestions.length > 0) {
						render_clarification_options(r.message.response, r.message.suggestions);
					} else {
						add_to_history("gemini", r.message.response);
					}

					if (r.message.conversation_id && !currentConversation) {
						currentConversation = r.message.conversation_id;
						load_conversations();
					}
				} else {
					add_to_history(
						"gemini",
						"Sorry, I received an empty response. Please try again."
					);
				}
			},
			error: function (r) {
				loading.hide();
				let error_msg =
					"An unknown server error occurred. Please check the console or server logs for more details.";
				if (r && r.message) {
					// Sanitize message to prevent potential XSS if rendered as HTML
					error_msg = r.message.replace(/</g, "&lt;").replace(/>/g, "&gt;");
				} else if (r && r.statusText) {
					error_msg = `Request failed: ${r.statusText}`;
				}
				add_to_history("gemini", `Error: ${error_msg}`);
			},
		});
	};

	const render_clarification_options = (intro_text, suggestions) => {
		let options_html = `<div class="clarification-container">
                                <p>${intro_text}</p>
                                <ol>`; // Using a simple <ol> for reliable numbering
		suggestions.forEach((opt) => {
			// Use the new descriptive label from the backend, with a fallback.
			const label = opt.label || `${opt.doctype}: ${opt.name}`;
			options_html += `<li>
                                <a href="${opt.url}" target="_blank" rel="noopener noreferrer">${label}</a>
                             </li>`;
		});
		options_html += `   </ol>
                           </div>`;

		let bubble = $(`<div class="chat-bubble gemini"></div>`);
		bubble.html(options_html);
		chat_history.append(bubble);
		chat_history.scrollTop(chat_history[0].scrollHeight);
	};

	const add_to_history = (role, text) => {
		let bubble;
		if (role === "thoughts") {
			bubble = $(
				`<div class="chat-bubble thoughts"><h6>Gemini's Thoughts</h6><pre></pre></div>`
			);
			bubble.find("pre").text(text);
		} else {
			bubble = $(`<div class="chat-bubble ${role}"></div>`);
			if (text) {
				if (window.showdown) {
					let converter = new showdown.Converter();
					bubble.html(converter.makeHtml(text));
				} else {
					bubble.text(text);
				}
			}
		}

		chat_history.append(bubble);
		chat_history.scrollTop(chat_history[0].scrollHeight);
		if (role !== "thoughts") {
			conversation.push({ role: role, text: text });
		}
	};

	let script = document.createElement("script");
	script.type = "text/javascript";
	script.src = "https://cdnjs.cloudflare.com/ajax/libs/showdown/2.1.0/showdown.min.js";
	document.head.appendChild(script);

	send_btn.on("click", () => send_message());

	chat_input.on("keydown", function (e) {
		if (e.key === "Enter" && e.shiftKey) {
			e.preventDefault();
			send_message();
		}
	});

	const load_conversations = () => {
		frappe.call({
			method: "gemini_integration.api.get_conversations",
			callback: function (r) {
				conversations_list.empty();
				if (r.message) {
					r.message.forEach((conv) => {
						let active_class = conv.name === currentConversation ? "active" : "";
						conversations_list.append(
							`<li class="list-group-item ${active_class}" data-id="${conv.name}">${conv.title}</li>`
						);
					});
				}
			},
		});
	};

	const load_conversation = (conversation_id) => {
		frappe.call({
			method: "gemini_integration.api.get_conversation",
			args: { conversation_id: conversation_id },
			callback: function (r) {
				if (r.message) {
					currentConversation = r.message.name;
					chat_history.empty();
					conversation = JSON.parse(r.message.conversation || "[]");
					conversation.forEach((msg) => add_to_history(msg.role, msg.text));
					load_conversations();
				}
			},
		});
	};

	new_chat_btn.on("click", () => {
		currentConversation = null;
		conversation = [];
		chat_history.empty();
		add_to_history("gemini", "Hello! How can I help you today?");
		load_conversations();
	});

	conversations_list.on("click", ".list-group-item", function () {
		load_conversation($(this).data("id"));
	});

	load_conversations();
	add_to_history("gemini", "Hello! How can I help you today?");
};
