/* global showdown */
frappe.pages["gemini-chat"].on_page_load = function (wrapper) {
	let page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Gemini Chat",
		single_column: true,
	});

	let currentConversation = null;

	const styles = `
		:root {
			--gemini-font-family: "Google Sans", sans-serif;
			--gemini-bg-color: #f0f4f9;
			--gemini-header-bg: #fff;
			--gemini-sidebar-bg: #fff;
			--gemini-chat-bg: #fff;
			--gemini-input-bg: #fff;
			--gemini-user-bubble: #1a73e8;
			--gemini-model-bubble: #f1f3f4;
			--gemini-text-color: #202124;
			--gemini-light-text: #5f6368;
			--gemini-border-color: #e0e2e6;
		}
        body { font-family: var(--gemini-font-family); }
        .gemini-chat-container { display: flex; height: 85vh; position: relative; overflow: hidden; background-color: var(--gemini-bg-color); }
        .conversations-sidebar { width: 260px; border-right: 1px solid var(--gemini-border-color); padding: 15px; display: flex; flex-direction: column; transition: transform 0.3s ease; background-color: var(--gemini-sidebar-bg); }
        .sidebar-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        #new-chat-button { border-radius: 20px; }
        #conversations-list { list-style: none; padding: 0; margin: 0; overflow-y: auto; }
        #conversations-list .list-group-item { cursor: pointer; padding: 10px 15px; border-radius: 20px; margin-bottom: 8px; border: none; }
        #conversations-list .list-group-item:hover { background-color: #e8f0fe; }
        #conversations-list .list-group-item.active { background-color: #d2e3fc; font-weight: 500; }

        .gemini-chat-wrapper { flex-grow: 1; display: flex; flex-direction: column; max-width: 900px; margin: 0 auto; width: 100%; }
		.page-header { padding: 15px 20px 0; }
        .chat-history { flex-grow: 1; overflow-y: auto; padding: 20px; }

		.chat-bubble-wrapper {
			display: flex;
			margin-bottom: 20px;
		}
		.chat-bubble-wrapper.user {
			justify-content: flex-end;
		}
		.chat-bubble-wrapper.gemini {
			justify-content: flex-start;
		}

		.avatar {
			width: 32px;
			height: 32px;
			border-radius: 50%;
			margin-right: 15px;
			background-color: #ccc; /* Placeholder */
			display: flex;
			align-items: center;
			justify-content: center;
			font-weight: bold;
			overflow: hidden;
		}

		.avatar img {
			width: 100%;
			height: 100%;
			object-fit: cover;
		}

		.chat-bubble-wrapper.user .avatar {
			margin-left: 15px;
			margin-right: 0;
		}


        .chat-bubble { max-width: 80%; padding: 15px 20px; border-radius: 18px; word-wrap: break-word; line-height: 1.6; }
        .chat-bubble.user { background-color: var(--gemini-user-bubble); color: white; border-bottom-right-radius: 4px; }
        .chat-bubble.gemini { background-color: var(--gemini-model-bubble); color: var(--gemini-text-color); border-bottom-left-radius: 4px; }
        .chat-bubble.thoughts { background-color: #f3f4f6; border: 1px solid var(--gemini-border-color); color: #4b5563; width: 100%; max-width: 100%; margin: 15px 0; padding: 15px; }
        .chat-bubble.thoughts h6 { margin-top: 0; margin-bottom: 10px; font-weight: 600; }
        .chat-bubble.thoughts pre { white-space: pre-wrap; word-wrap: break-word; max-height: 200px; overflow-y: auto; background-color: #fff; padding: 10px; border-radius: 4px; font-family: monospace; font-size: 12px; }
		.chat-bubble .generated-image { max-width: 100%; border-radius: 10px; margin-top: 10px; }

		.greeting-card {
			padding: 24px;
			border-radius: 12px;
			margin-bottom: 30px;
			text-align: center;
		}
		.greeting-title {
			font-size: 32px;
			font-weight: 500;
			margin-bottom: 10px;
		}
		.greeting-subtitle {
			font-size: 16px;
			color: var(--gemini-light-text);
		}

        .chat-input-area { display: flex; align-items: center; gap: 15px; position: relative; background-color: var(--gemini-input-bg); padding: 10px 20px; border-radius: 28px; border: 1px solid var(--gemini-border-color); margin-bottom: 20px; }
        .chat-input-area textarea { flex-grow: 1; border: none; outline: none; resize: none; background-color: transparent; font-size: 16px; }
		.chat-input-area textarea:focus { box-shadow: none; }
		.send-btn { border-radius: 50%; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }

		.sidebar-controls { display: flex; flex-direction: column; gap: 10px; padding-top: 15px; border-top: 1px solid var(--gemini-border-color); }
		.sidebar-controls .btn { width: 100%; text-align: left; justify-content: flex-start; }
		.sidebar-controls .model-selector-container .form-group { margin-bottom: 0; }
		.sidebar-controls .google-connect-btn { border-radius: 20px; }
        .sidebar-toggle-btn { display: none; }

		/* Toggle Switch styles */
		.google-search-toggle { display: flex; align-items: center; justify-content: space-between; padding: 8px 15px; cursor: pointer; border-radius: 20px; }
		.google-search-toggle:hover { background-color: #e8f0fe; }
		.google-search-toggle label { margin-bottom: 0; font-weight: 500; }
		.switch { position: relative; display: inline-block; width: 34px; height: 20px; }
		.switch input { opacity: 0; width: 0; height: 0; }
		.slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; -webkit-transition: .4s; transition: .4s; border-radius: 34px; }
		.slider:before { position: absolute; content: ""; height: 12px; width: 12px; left: 4px; bottom: 4px; background-color: white; -webkit-transition: .4s; transition: .4s; border-radius: 50%; }
		input:checked + .slider { background-color: #1a73e8; }
		input:checked + .slider:before { -webkit-transform: translateX(14px); -ms-transform: translateX(14px); transform: translateX(14px); }
		input:disabled + .slider { background-color: #e0e0e0; cursor: not-allowed; }


        @media (max-width: 768px) {
            .sidebar-toggle-btn { display: inline-block; }
            .conversations-sidebar { position: absolute; top: 0; left: 0; height: 100%; z-index: 10; background: var(--gemini-sidebar-bg); transform: translateX(-100%); box-shadow: 2px 0 5px rgba(0,0,0,0.1); }
            .gemini-chat-container.sidebar-open .conversations-sidebar { transform: translateX(0); }
            .gemini-chat-wrapper { padding: 0 15px; }
			.chat-input-area { margin-bottom: 15px; }
        }
    `;
	$("<style>").text(styles).appendTo("head");
	$('<link href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&display=swap" rel="stylesheet">').appendTo("head");


	let html = `
        <div class="gemini-chat-container">
            <div class="conversations-sidebar">
                <div class="sidebar-header">
                    <h4>Conversations</h4>
                    <div>
                        <button id="new-chat-button" class="btn btn-default btn-sm">
							<i class="fa fa-plus" style="margin-right: 5px;"></i> New Chat
						</button>
                        <button id="close-sidebar-btn" class="btn btn-default btn-sm visible-xs"><i class="fa fa-times"></i></button>
                    </div>
                </div>
                <ul id="conversations-list" class="list-group" style="flex-grow: 1;"></ul>
				<div class="sidebar-controls">
					<div class="model-selector-container"></div>
					<button class="btn btn-default btn-sm google-connect-btn">
						<i class="fa fa-google" style="margin-right: 5px;"></i>
						Connect Google Account
					</button>
					<button class="btn btn-default btn-sm help-btn" title="Help">
						<i class="fa fa-question-circle-o" style="margin-right: 5px;"></i> Help
					</button>
                    <div class="google-search-toggle">
                        <label for="google-search-checkbox" class="mb-0">Search with Google</label>
                        <label class="switch">
                            <input type="checkbox" id="google-search-checkbox">
                            <span class="slider"></span>
                        </label>
                    </div>
				</div>
            </div>
            <div class="gemini-chat-wrapper">
				<div class="page-header">
					 <button class="btn btn-default btn-sm sidebar-toggle-btn">
                        <i class="fa fa-bars"></i>
                    </button>
				</div>
                <div class="chat-history">
					<!-- Greeting will be injected here -->
				</div>
                <div class="chat-input-area">
                    <textarea class="form-control" rows="1" placeholder="Enter a prompt here"></textarea>
                    <button class="btn btn-primary send-btn"><i class="fa fa-arrow-up"></i></button>
                </div>
            </div>
        </div>
    `;
	$(page.body).html(html);

	let chat_history = $(page.body).find(".chat-history");
	let chat_input = $(page.body).find(".chat-input-area textarea");
	let send_btn = $(page.body).find(".send-btn");
	let google_search_checkbox = $(page.body).find("#google-search-checkbox");
	let google_connect_btn = $(page.body).find(".google-connect-btn");
	let help_btn = $(page.body).find(".help-btn");
	let new_chat_btn = $(page.body).find("#new-chat-button");
	let conversations_list = $(page.body).find("#conversations-list");
	let sidebar_toggle_btn = $(page.body).find(".sidebar-toggle-btn");
	let close_sidebar_btn = $(page.body).find("#close-sidebar-btn");
	let gemini_chat_container = $(page.body).find(".gemini-chat-container");
	let gemini_chat_wrapper = $(page.body).find(".gemini-chat-wrapper");
	let conversation = [];

	page.model_selector = frappe.ui.form.make_control({
		parent: $(page.body).find(".model-selector-container"),
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

	// Check if Google Search is enabled in settings and update the checkbox
	frappe.db.get_single_value("Gemini Settings", "enable_google_search").then((is_enabled) => {
		if (is_enabled) {
			google_search_checkbox.prop("disabled", false);
			google_search_checkbox.prop("checked", true);
		} else {
			google_search_checkbox.prop("disabled", true);
			google_search_checkbox.prop("checked", false);
		}
	});

	google_connect_btn.on("click", () => {
		frappe.call({
			method: "gemini_integration.api.get_auth_url",
			callback: (r) => {
				if (r.message) window.open(r.message, "_blank");
			},
		});
	});

	sidebar_toggle_btn.on("click", (e) => {
		e.stopPropagation();
		gemini_chat_container.toggleClass("sidebar-open");
	});
	close_sidebar_btn.on("click", () => gemini_chat_container.removeClass("sidebar-open"));
	gemini_chat_wrapper.on("click", () => gemini_chat_container.removeClass("sidebar-open"));

	help_btn.on("click", () => {
		const help_html = `
            <div>
                <h4>How to Use the Assistant</h4>
                <p>You can interact with the assistant in two main ways: by using specific tools to access your data or by asking general questions just like you would with a standard chatbot.</p>

                <h5>Using Tools with @-Mentions</h5>
                <p>To use a specific tool, mention it in your prompt using the <code>@</code> symbol. This tells the assistant exactly where to look for information or what service to use.</p>
                <ul>
                    <li>
                        <strong>@ERPNext:</strong> Accesses documents and data from your ERPNext instance.
                        <br><em>Example: "Pull the quarterly sales report for 'Innovate Corp' from @ERPNext."</em>
                        <br><em>Example: "What is the status of project @PRJ-00219?"</em>
                    </li>
                    <li>
                        <strong>@Gmail:</strong> Searches your emails or drafts new ones.
                        <br><em>Example: "Using @Gmail, draft a follow-up email to 'contact@example.com' regarding our meeting last Tuesday."</em>
                    </li>
                    <li>
                        <strong>@Drive:</strong> Finds files in your Google Drive.
                        <br><em>Example: "Find the 'Q3 Marketing Strategy' document in @Drive."</em>
                    </li>
                    <li>
                        <strong>@Calendar:</strong> Checks your upcoming events.
                        <br><em>Example: "What are my appointments for next week according to my @Calendar?"</em>
                    </li>
                    <li>
                        <strong>@Contacts:</strong> Searches your Google Contacts.
                        <br><em>Example: "Find the phone number for 'Jane Doe' in my @Contacts."</em>
                    </li>
                    <li>
                        <strong>@Google:</strong> Performs a broad search across all your connected Google Workspace apps (Gmail, Drive, Calendar, Contacts).
                        <br><em>Example: "Search @Google for all communications with 'Client Solutions Inc.'."</em>
                    </li>
                </ul>

                <h5>General AI Queries</h5>
                <p>If you don't mention a specific tool, the assistant will use its general knowledge to answer your questions. This is useful for brainstorming, summarization, and problem-solving.</p>
                <ul>
                    <li><em>"Summarize the latest market trends for enterprise software."</em></li>
                    <li><em>"Help me outline a business plan for a new subscription service."</em></li>
                    <li><em>"Draft a professional response to a customer complaint about a delayed shipment."</em></li>
                </ul>

                <h5>Tool Confirmation</h5>
                <p>For actions that have external effects, like sending an email, the model will first generate a draft or a plan. It will present this to you for confirmation before proceeding with the action.</p>
            </div>`;
		frappe.msgprint({
			title: __("Help: Using the Assistant"),
			indicator: "blue",
			message: help_html,
		});
	});

	/**
	 * Sends a message to the Gemini API and displays the response.
	 * @param {string} [prompt] - The message to send. If not provided, the value from the chat input is used.
	 */
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
				use_google_search: google_search_checkbox.is(":checked"),
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
						add_to_history("gemini", r.message.response, r.message.image_url);
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

	/**
	 * Renders a list of clarification options for the user to choose from.
	 * @param {string} intro_text - The introductory text to display before the options.
	 * @param {Array<Object>} suggestions - A list of suggestion objects.
	 */
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

	/**
	 * Adds a message to the chat history.
	 * @param {string} role - The role of the message sender ('user', 'gemini', or 'thoughts').
	 * @param {string} text - The content of the message.
	 * @param {string} [image_url] - The URL of an image to display.
	 */
	const add_to_history = (role, text, image_url) => {
		// If the greeting is visible, remove it.
		chat_history.find(".greeting-card").remove();

		let bubble_wrapper = $(`<div class="chat-bubble-wrapper ${role}"></div>`);
		let avatar = $(`<div class="avatar"></div>`);
		let bubble = $(`<div class="chat-bubble ${role}"></div>`);

		// Add initials to avatar
		if (role === "user") {
			const set_fallback_avatar = () => {
				avatar.empty();
				avatar.text(frappe.session.user_abbr);
				avatar.css("background-color", frappe.get_palette(frappe.session.user_fullname));
			};

			if (frappe.session.user_image) {
				let user_image_url = frappe.session.user_image;
				if (!user_image_url.startsWith("/") && !user_image_url.startsWith("http")) {
					user_image_url = "/" + user_image_url;
				}
				const img = $(`<img src="${user_image_url}" alt="${frappe.session.user_fullname}">`);
				img.on("error", set_fallback_avatar);
				avatar.html(img);
			} else {
				set_fallback_avatar();
			}
		} else {
			avatar.html('<img src="/app/gemini_integration/public/images/gemini_logo.svg" alt="Gemini">');
			avatar.css("background-color", "transparent");
		}

		if (text) {
			if (window.showdown) {
				let converter = new showdown.Converter();
				bubble.html(converter.makeHtml(text));
			} else {
				bubble.text(text);
			}
		}

		if (image_url) {
			const image = $(`<img src="${image_url}" class="generated-image">`);
			bubble.append(image);
		}

		if (role === 'user') {
			bubble_wrapper.append(bubble).append(avatar);
		} else {
			bubble_wrapper.append(avatar).append(bubble);
		}

		chat_history.append(bubble_wrapper);
		chat_history.scrollTop(chat_history[0].scrollHeight);

		if (role !== "thoughts") {
			const message_to_save = { role: role, text: text };
			if (image_url) {
				message_to_save.image_url = image_url;
			}
			conversation.push(message_to_save);
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

	/**
	 * Loads the list of conversations from the server and displays them in the sidebar.
	 */
	const load_conversations = () => {
		frappe.call({
			method: "gemini_integration.api.get_conversations",
			callback: function (r) {
				conversations_list.empty();
				if (r.message) {
					r.message.forEach((conv) => {
						let active_class = conv.name === currentConversation ? "active" : "";
						let conversation_link = $(
							`<a href="/app/gemini-chat/${conv.name}" class="list-group-item ${active_class}" data-id="${conv.name}">${conv.title}</a>`
						);
						conversations_list.append($("<li>").append(conversation_link));
					});
				}
			},
		});
	};

	/**
	 * Loads a specific conversation from the server and displays it in the chat history.
	 * @param {string} conversation_id - The ID of the conversation to load.
	 */
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

	const show_greeting = () => {
		const user_name = frappe.session.user_fullname;
		const greeting_html = `
            <div class="greeting-card">
                <h1 class="greeting-title">Hello, ${user_name}</h1>
                <p class="greeting-subtitle">How can I help you today?</p>
            </div>
        `;
		chat_history.html(greeting_html);
	};

	new_chat_btn.on("click", () => {
		history.pushState(null, "", "/app/gemini-chat");
		currentConversation = null;
		conversation = [];
		chat_history.empty();
		show_greeting();
		load_conversations();
	});

	conversations_list.on("click", ".list-group-item", function (e) {
		e.preventDefault();
		const conversation_id = $(this).data("id");
		history.pushState({ conversation_id: conversation_id }, "", `/app/gemini-chat/${conversation_id}`);
		load_conversation(conversation_id);
	});

	load_conversations();

	/**
	 * Handles the initial loading of the chat page, either loading a specific conversation
	 * from the URL or starting a new one.
	 */
	const handle_initial_load = () => {
		const path = window.location.pathname;
		const match = path.match(/^\/app\/gemini-chat\/(CON-\d{5,})$/);
		if (match) {
			load_conversation(match[1]);
		} else {
			show_greeting();
		}
	};
	handle_initial_load();

	window.addEventListener("popstate", (e) => {
		handle_initial_load();
	});
};
