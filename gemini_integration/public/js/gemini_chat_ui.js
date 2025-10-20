/* global showdown, DOMPurify */

function createGeminiChatUI(parentElement) {
    let container = $(parentElement);
    container.html(""); // Clear any existing content

    let currentConversation = null;

    const styles = `
        #gemini-chat-container {
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
            font-family: var(--gemini-font-family);
            display: flex; flex-grow: 1; position: relative; overflow: hidden; background-color: var(--gemini-bg-color);
        }
        .gemini-chat-page .page-content {
            height: calc(100vh - var(--page-head-height) - var(--margin-top) - var(--margin-bottom) - 2px);
            display: flex;
            flex-direction: column;
        }
        .gemini-chat-page .page-content .layout-main-section {
            flex-grow: 1;
            display: flex;
            flex-direction: column;
            padding-top: 0;
            padding-bottom: 0;
        }
        #gemini-chat-container .conversations-sidebar { width: 260px; border-right: 1px solid var(--gemini-border-color); padding: 15px; display: flex; flex-direction: column; transition: transform 0.3s ease; background-color: var(--gemini-sidebar-bg); }
        #gemini-chat-container .sidebar-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        #gemini-chat-container #new-chat-button { border-radius: 20px; }
        #gemini-chat-container #conversations-list { list-style: none; padding: 0; margin: 0; overflow-y: auto; }
        #gemini-chat-container #conversations-list .list-group-item { cursor: pointer; padding: 10px 15px; border-radius: 20px; margin-bottom: 8px; border: none; }
        #gemini-chat-container #conversations-list .list-group-item:hover { background-color: #e8f0fe; }
        #gemini-chat-container #conversations-list .list-group-item.active { background-color: #d2e3fc; font-weight: 500; }
        #gemini-chat-container .gemini-chat-wrapper { flex-grow: 1; display: flex; flex-direction: column; max-width: 900px; margin: 0 auto; width: 100%; }
		#gemini-chat-container .page-header { padding: 15px 20px 0; display: none; }
        #gemini-chat-container .chat-history { flex-grow: 1; overflow-y: auto; padding: 20px; }
		#gemini-chat-container .chat-bubble-wrapper { display: flex; margin-bottom: 20px; }
		#gemini-chat-container .chat-bubble-wrapper.user { justify-content: flex-end; }
		#gemini-chat-container .chat-bubble-wrapper.gemini { justify-content: flex-start; }
		#gemini-chat-container .avatar { width: 32px; height: 32px; border-radius: 50%; margin-right: 15px; background-color: #ccc; display: flex; align-items: center; justify-content: center; font-weight: bold; overflow: hidden; }
		#gemini-chat-container .avatar img { width: 100%; height: 100%; object-fit: cover; }
		#gemini-chat-container .chat-bubble-wrapper.user .avatar { margin-left: 15px; margin-right: 0; }
        #gemini-chat-container .chat-bubble { max-width: 80%; padding: 15px 20px; border-radius: 18px; word-wrap: break-word; line-height: 1.6; }
        #gemini-chat-container .chat-bubble.user { background-color: var(--gemini-user-bubble); color: white; border-bottom-right-radius: 4px; }
        #gemini-chat-container .chat-bubble.gemini { background-color: var(--gemini-model-bubble); color: var(--gemini-text-color); border-bottom-left-radius: 4px; }
        #gemini-chat-container .chat-bubble.thoughts { background-color: #f3f4f6; border: 1px solid var(--gemini-border-color); color: #4b5563; width: 100%; max-width: 100%; margin: 15px 0; padding: 15px; }
		#gemini-chat-container .chat-bubble .generated-image { max-width: 100%; border-radius: 10px; margin-top: 10px; }
		#gemini-chat-container .greeting-card { padding: 24px; border-radius: 12px; margin-bottom: 30px; text-align: center; }
		#gemini-chat-container .greeting-title { font-size: 32px; font-weight: 500; margin-bottom: 10px; }
		#gemini-chat-container .greeting-subtitle { font-size: 16px; color: var(--gemini-light-text); }
        #gemini-chat-container .chat-input-area { display: flex; align-items: center; gap: 15px; position: relative; background-color: var(--gemini-input-bg); padding: 10px 20px; border-radius: 28px; border: 1px solid var(--gemini-border-color); margin-bottom: 20px; }
        #gemini-chat-container .chat-input-area textarea { flex-grow: 1; border: none; outline: none; resize: none; background-color: transparent; font-size: 16px; }
		#gemini-chat-container .chat-input-area textarea:focus { box-shadow: none; }
		#gemini-chat-container .send-btn { border-radius: 50%; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
		#gemini-chat-container .spinner-container { width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
		#gemini-chat-container .spinner { border: 4px solid var(--gemini-border-color); border-top: 4px solid var(--gemini-user-bubble); border-radius: 50%; width: 24px; height: 24px; animation: spin 1s linear infinite; }
		@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
		#gemini-chat-container .sidebar-controls { display: flex; flex-direction: column; gap: 10px; padding-top: 15px; border-top: 1px solid var(--gemini-border-color); }
		#gemini-chat-container .google-search-toggle { display: flex; align-items: center; justify-content: space-between; padding: 8px 15px; cursor: pointer; border-radius: 20px; }
		#gemini-chat-container .switch { position: relative; display: inline-block; width: 34px; height: 20px; }
		#gemini-chat-container .switch input { opacity: 0; width: 0; height: 0; }
		#gemini-chat-container .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .4s; border-radius: 34px; }
		#gemini-chat-container .slider:before { position: absolute; content: ""; height: 12px; width: 12px; left: 4px; bottom: 4px; background-color: white; transition: .4s; border-radius: 50%; }
		#gemini-chat-container input:checked + .slider { background-color: #1a73e8; }
		#gemini-chat-container input:checked + .slider:before { transform: translateX(14px); }
		#gemini-chat-container input:disabled + .slider { background-color: #e0e0e0; cursor: not-allowed; }
        @media (max-width: 768px) {
            #gemini-chat-container .page-header { display: block; }
            #gemini-chat-container .conversations-sidebar { position: absolute; top: 0; left: 0; height: 100%; z-index: 10; background: var(--gemini-sidebar-bg); transform: translateX(-100%); box-shadow: 2px 0 5px rgba(0,0,0,0.1); }
            #gemini-chat-container.sidebar-open .conversations-sidebar { transform: translateX(0); }
            #gemini-chat-container .gemini-chat-wrapper { padding: 0 15px; }
			#gemini-chat-container .chat-input-area { margin-bottom: 15px; }
        }
    `;
    $("<style>").text(styles).appendTo("head");
    $('<link href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&display=swap" rel="stylesheet">').appendTo("head");

    let html = `
        <div id="gemini-chat-container">
             <div class="conversations-sidebar">
                <div class="sidebar-header">
                    <h4>Conversations</h4>
                    <div>
                        <button id="new-chat-button" class="btn btn-default btn-sm"><i class="fa fa-plus"></i></button>
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
                <div class="chat-history"></div>
                <div class="chat-input-area">
                    <textarea class="form-control" rows="1" placeholder="Enter a prompt here"></textarea>
                    <button class="btn btn-primary send-btn"><i class="fa fa-arrow-up"></i></button>
					<div class="spinner-container" style="display: none;"><div class="spinner"></div></div>
                </div>
            </div>
        </div>
    `;
    container.html(html);

    let chat_history = container.find(".chat-history");
    let chat_input = container.find(".chat-input-area textarea");
    let send_btn = container.find(".send-btn");
    let spinner_container = container.find(".spinner-container");
    let google_search_checkbox = container.find("#google-search-checkbox");
	let google_connect_btn = container.find(".google-connect-btn");
	let help_btn = container.find(".help-btn");
    let new_chat_btn = container.find("#new-chat-button");
    let conversations_list = container.find("#conversations-list");
	let sidebar_toggle_btn = container.find(".sidebar-toggle-btn");
	let close_sidebar_btn = container.find("#close-sidebar-btn");
    let conversation = [];

	sidebar_toggle_btn.on("click", (e) => {
		e.stopPropagation();
		container.find("#gemini-chat-container").toggleClass("sidebar-open");
	});
	close_sidebar_btn.on("click", () => container.find("#gemini-chat-container").removeClass("sidebar-open"));
	container.find(".gemini-chat-wrapper").on("click", () => container.find("#gemini-chat-container").removeClass("sidebar-open"));

	let model_selector = frappe.ui.form.make_control({
		parent: container.find(".model-selector-container"),
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
		model_selector.set_value(
			localStorage.getItem("gemini_last_model") || "gemini-1.5-flash"
		);
	} catch (e) {
		console.error("localStorage is not available. Using default model.", e);
		model_selector.set_value("gemini-1.5-flash");
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

    frappe.db.get_single_value("Gemini Settings", "enable_google_search").then((is_enabled) => {
        google_search_checkbox.prop("disabled", !is_enabled);
        google_search_checkbox.prop("checked", is_enabled);
    });

	google_connect_btn.on("click", () => {
		frappe.call({
			method: "gemini_integration.api.get_auth_url",
			callback: (r) => {
				if (r.message) window.open(r.message, "_blank");
			},
		});
	});

	help_btn.on("click", () => {
		const help_html = `
            <div>
                <h4>How to Use the Assistant</h4>
                <p>You can interact with the assistant in two main ways: by using specific tools to access your data or by asking general questions just like you would with a standard chatbot.</p>
                <h5>Using Tools with @-Mentions</h5>
                <p>To use a specific tool, mention it in your prompt using the <code>@</code> symbol. This tells the assistant exactly where to look for information or what service to use.</p>
            </div>`;
		frappe.msgprint({
			title: __("Help: Using the Assistant"),
			indicator: "blue",
			message: help_html,
		});
	});

    let streaming_bubble = null;
    let full_response = "";
    frappe.realtime.on("gemini_chat_update", function (data) {
        if (data.conversation_id && !currentConversation) {
            currentConversation = data.conversation_id;
            load_conversations();
        }
        if (data.message) {
            full_response += data.message;
            if (streaming_bubble) {
                streaming_bubble.html(DOMPurify.sanitize(new showdown.Converter().makeHtml(full_response)));
                chat_history.scrollTop(chat_history[0].scrollHeight);
            }
        }
        if (data.end_of_stream) {
            chat_input.prop("disabled", false);
            spinner_container.hide();
            send_btn.show();
            streaming_bubble = null;
            full_response = "";
        }
    });

    const send_message = (prompt, context) => {
        if (!prompt) {
            prompt = chat_input.val().trim();
            if (!prompt) return;
        }
        add_to_history("user", prompt);
        chat_input.val("");
        chat_input.prop("disabled", true);
        send_btn.hide();
        spinner_container.show();
        streaming_bubble = add_to_history("gemini", "");
        full_response = "";

        frappe.call({
            method: "gemini_integration.api.stream_chat",
            args: {
                prompt: prompt,
                model: model_selector.get_value(),
                conversation_id: currentConversation,
                use_google_search: google_search_checkbox.is(":checked"),
                context: context,
            },
            error: function (r) {
                chat_input.prop("disabled", false);
                spinner_container.hide();
                send_btn.show();
                add_to_history("gemini", `Error: ${r.message}`);
            },
        });
    };

    const add_to_history = (role, text) => {
        chat_history.find(".greeting-card").remove();
        let bubble_wrapper = $(`<div class="chat-bubble-wrapper ${role}"></div>`);
        let avatar = $(`<div class="avatar"></div>`);
        let bubble = $(`<div class="chat-bubble ${role}"></div>`);

        if (role === "user") {
			const set_fallback_avatar = () => {
				avatar.empty().text(frappe.session.user_abbr).css("background-color", frappe.get_palette(frappe.session.user_fullname));
			};
			if (frappe.session.user_image) {
				let user_image_url = frappe.session.user_image.startsWith("/") || frappe.session.user_image.startsWith("http") ? frappe.session.user_image : "/" + frappe.session.user_image;
				$("<img>").attr("alt", frappe.session.user_fullname).on("error", set_fallback_avatar).attr("src", user_image_url).appendTo(avatar);
			} else {
				set_fallback_avatar();
			}
        } else {
            avatar.html(`<svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 65 65"><mask id="maskme" style="mask-type:alpha" maskUnits="userSpaceOnUse" x="0" y="0" width="65" height="65"><path d="M32.447 0c.68 0 1.273.465 1.439 1.125a38.904 38.904 0 001.999 5.905c2.152 5 5.105 9.376 8.854 13.125 3.751 3.75 8.126 6.703 13.125 8.855a38.98 38.98 0 005.906 1.999c.66.166 1.124.758 1.124 1.438 0 .68-.464 1.273-1.125 1.439a38.902 38.902 0 00-5.905 1.999c-5 2.152-9.375 5.105-13.125 8.854-3.749 3.751-6.702 8.126-8.854 13.125a38.973 38.973 0 00-2 5.906 1.485 1.485 0 01-1.438 1.124c-.68 0-1.272-.464-1.438-1.125a38.913 38.913 0 00-2-5.905c-2.151-5-5.103-9.375-8.854-13.125-3.75-3.749-8.125-6.702-13.125-8.854a38.973 38.973 0 00-5.905-2A1.485 1.485 0 010 32.448c0-.68.465-1.272 1.125-1.438a38.903 38.903 0 005.905-2c5-2.151 9.376-5.104 13.125-8.854 3.75-3.749 6.703-8.125 8.855-13.125a38.972 38.972 0 001.999-5.905A1.485 1.485 0 0132.447 0z" fill="#000"/><path d="M32.447 0c.68 0 1.273.465 1.439 1.125a38.904 38.904 0 001.999 5.905c2.152 5 5.105 9.376 8.854 13.125 3.751 3.75 8.126 6.703 13.125 8.855a38.98 38.98 0 005.906 1.999c.66.166 1.124.758 1.124 1.438 0 .68-.464 1.273-1.125 1.439a38.902 38.902 0 00-5.905 1.999c-5 2.152-9.375 5.105-13.125 8.854-3.749 3.751-6.702 8.126-8.854 13.125a38.973 38.973 0 00-2 5.906 1.485 1.485 0 01-1.438 1.124c-.68 0-1.272-.464-1.438-1.125a38.913 38.913 0 00-2-5.905c-2.151-5-5.103-9.375-8.854-13.125-3.75-3.749-8.125-6.702-13.125-8.854a38.973 38.973 0 00-5.905-2A1.485 1.485 0 010 32.448c0-.68.465-1.272 1.125-1.438a38.903 38.903 0 005.905-2c5-2.151 9.376-5.104 13.125-8.854 3.75-3.749 6.703-8.125 8.855-13.125a38.972 38.972 0 001.999-5.905A1.485 1.485 0 0132.447 0z" fill="url(#prefix__paint0_linear_2001_67)"/></mask><g mask="url(#maskme)"><g filter="url(#prefix__filter0_f_2001_67)"><path d="M-5.859 50.734c7.498 2.663 16.116-2.33 19.249-11.152 3.133-8.821-.406-18.131-7.904-20.794-7.498-2.663-16.116 2.33-19.25 11.151-3.132 8.822.407 18.132 7.905 20.795z" fill="#FFE432"/></g><g filter="url(#prefix__filter1_f_2001_67)"><path d="M27.433 21.649c10.3 0 18.651-8.535 18.651-19.062 0-10.528-8.35-19.062-18.651-19.062S8.78-7.94 8.78 2.587c0 10.527 8.35 19.062 18.652 19.062z" fill="#FC413D"/></g><g filter="url(#prefix__filter2_f_2001_67)"><path d="M20.184 82.608c10.753-.525 18.918-12.244 18.237-26.174-.68-13.93-9.95-24.797-20.703-24.271C6.965 32.689-1.2 44.407-.519 58.337c.681 13.93 9.95 24.797 20.703 24.271z" fill="#00B95C"/></g><g filter="url(#prefix__filter3_f_2001_67)"><path d="M20.184 82.608c10.753-.525 18.918-12.244 18.237-26.174-.68-13.93-9.95-24.797-20.703-24.271C6.965 32.689-1.2 44.407-.519 58.337c.681 13.93 9.95 24.797 20.703 24.271z" fill="#00B95C"/></g><g filter="url(#prefix__filter4_f_2001_67)"><path d="M30.954 74.181c9.014-5.485 11.427-17.976 5.389-27.9-6.038-9.925-18.241-13.524-27.256-8.04-9.015 5.486-11.428 17.977-5.39 27.902 6.04 9.924 18.242 13.523 27.257 8.038z" fill="#00B95C"/></g><g filter="url(#prefix__filter5_f_2001_67)"><path d="M67.391 42.993c10.132 0 18.346-7.91 18.346-17.666 0-9.757-8.214-17.667-18.346-17.667s-18.346 7.91-18.346 17.667c0 9.757 8.214 17.666 18.346 17.666z" fill="#3186FF"/></g><g filter="url(#prefix__filter6_f_2001_67)"><path d="M-13.065 40.944c9.33 7.094 22.959 4.869 30.442-4.972 7.483-9.84 5.987-23.569-3.343-30.663C4.704-1.786-8.924.439-16.408 10.28c-7.483 9.84-5.986 23.57 3.343 30.664z" fill="#FBBC04"/></g><g filter="url(#prefix__filter7_f_2001_67)"><path d="M34.74 51.43c11.135 7.656 25.896 5.524 32.968-4.764 7.073-10.287 3.779-24.832-7.357-32.488C49.215 6.52 34.455 8.654 27.382 18.94c-7.072 10.288-3.779 24.833 7.357 32.49z" fill="#3186FF"/></g><g filter="url(#prefix__filter8_f_2001_67)"><path d="M54.984-2.336c2.833 3.852-.808 11.34-8.131 16.727-7.324 5.387-15.557 6.631-18.39 2.78-2.833-3.853.807-11.342 8.13-16.728 7.324-5.387 15.558-6.631 18.39-2.78z" fill="#749BFF"/></g><g filter="url(#prefix__filter9_f_2001_67)"><path d="M31.727 16.104C43.053 5.598 46.94-8.626 40.41-15.666c-6.53-7.04-21.006-4.232-32.332 6.274s-15.214 24.73-8.683 31.77c6.53 7.04 21.006 4.232 32.332-6.274z" fill="#FC413D"/></g><g filter="url(#prefix__filter10_f_2001_67)"><path d="M8.51 53.838c6.732 4.818 14.46 5.55 17.262 1.636 2.802-3.915-.384-10.994-7.116-15.812-6.731-4.818-14.46-5.55-17.261-1.636-2.802 3.915.383 10.994 7.115 15.812z" fill="#FFEE48"/></g></g><defs><filter id="prefix__filter0_f_2001_67" x="-19.824" y="13.152" width="39.274" height="43.217" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB"><feFlood flood-opacity="0" result="BackgroundImageFix"/><feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape"/><feGaussianBlur stdDeviation="2.46" result="effect1_foregroundBlur_2001_67"/></filter><filter id="prefix__filter1_f_2001_67" x="-15.001" y="-40.257" width="84.868" height="85.688" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB"><feFlood flood-opacity="0" result="BackgroundImageFix"/><feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape"/><feGaussianBlur stdDeviation="11.891" result="effect1_foregroundBlur_2001_67"/></filter><filter id="prefix__filter2_f_2001_67" x="-20.776" y="11.927" width="79.454" height="90.916" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB"><feFlood flood-opacity="0" result="BackgroundImageFix"/><feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape"/><feGaussianBlur stdDeviation="10.109" result="effect1_foregroundBlur_2001_67"/></filter><filter id="prefix__filter3_f_2001_67" x="-20.776" y="11.927" width="79.454" height="90.916" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB"><feFlood flood-opacity="0" result="BackgroundImageFix"/><feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape"/><feGaussianBlur stdDeviation="10.109" result="effect1_foregroundBlur_2001_67"/></filter><filter id="prefix__filter4_f_2001_67" x="-19.845" y="15.459" width="79.731" height="81.505" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB"><feFlood flood-opacity="0" result="BackgroundImageFix"/><feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape"/><feGaussianBlur stdDeviation="10.109" result="effect1_foregroundBlur_2001_67"/></filter><filter id="prefix__filter5_f_2001_67" x="29.832" y="-11.552" width="75.117" height="73.758" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB"><feFlood flood-opacity="0" result="BackgroundImageFix"/><feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape"/><feGaussianBlur stdDeviation="9.606" result="effect1_foregroundBlur_2001_67"/></filter><filter id="prefix__filter6_f_2001_67" x="-38.583" y="-16.253" width="78.135" height="78.758" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB"><feFlood flood-opacity="0" result="BackgroundImageFix"/><feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape"/><feGaussianBlur stdDeviation="8.706" result="effect1_foregroundBlur_2001_67"/></filter><filter id="prefix__filter7_f_2001_67" x="8.107" y="-5.966" width="78.877" height="77.539" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB"><feFlood flood-opacity="0" result="BackgroundImageFix"/><feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape"/><feGaussianBlur stdDeviation="7.775" result="effect1_foregroundBlur_2001_67"/></filter><filter id="prefix__filter8_f_2001_67" x="13.587" y="-18.488" width="56.272" height="51.81" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB"><feFlood flood-opacity="0" result="BackgroundImageFix"/><feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape"/><feGaussianBlur stdDeviation="6.957" result="effect1_foregroundBlur_2001_67"/></filter><filter id="prefix__filter9_f_2001_67" x="-15.526" y="-31.297" width="70.856" height="69.306" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB"><feFlood flood-opacity="0" result="BackgroundImageFix"/><feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape"/><feGaussianBlur stdDeviation="5.876" result="effect1_foregroundBlur_2001_67"/></filter><filter id="prefix__filter10_f_2001_67" x="-14.168" y="20.964" width="55.501" height="51.571" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB"><feFlood flood-opacity="0" result="BackgroundImageFix"/><feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape"/><feGaussianBlur stdDeviation="7.273" result="effect1_foregroundBlur_2001_67"/></filter><linearGradient id="prefix__paint0_linear_2001_67" x1="18.447" y1="43.42" x2="52.153" y2="15.004" gradientUnits="userSpaceOnUse"><stop stop-color="#4893FC"/><stop offset=".27" stop-color="#4893FC"/><stop offset=".777" stop-color="#969DFF"/><stop offset="1" stop-color="#BD99FE"/></linearGradient></defs></svg>`).css("background-color", "transparent");
        }
        bubble.html(DOMPurify.sanitize(new showdown.Converter().makeHtml(text)));
        bubble_wrapper.append(role === 'user' ? [bubble, avatar] : [avatar, bubble]);
        chat_history.append(bubble_wrapper).scrollTop(chat_history[0].scrollHeight);
        conversation.push({ role: role, text: text });
        return bubble;
    };

    send_btn.on("click", () => send_message());
    chat_input.on("keydown", (e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), send_message()));

    const load_conversations = () => {
        frappe.call({
            method: "gemini_integration.api.get_conversations",
            callback: (r) => {
                conversations_list.empty();
                if (r.message) {
                    r.message.forEach((conv) => {
                        let active_class = conv.name === currentConversation ? "active" : "";
                        $(`<li><a href="#" class="list-group-item ${active_class}" data-id="${conv.name}">${conv.title}</a></li>`).appendTo(conversations_list);
                    });
                }
            },
        });
    };

    const load_conversation = (conversation_id) => {
        frappe.call({
            method: "gemini_integration.api.get_conversation",
            args: { conversation_id: conversation_id },
            callback: (r) => {
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
        chat_history.html(`<div class="greeting-card"><h1 class="greeting-title">Hello, ${frappe.session.user_fullname}</h1><p class="greeting-subtitle">How can I help you today?</p></div>`);
    };

    new_chat_btn.on("click", () => {
        currentConversation = null;
        conversation = [];
        chat_history.empty();
        show_greeting();
        load_conversations();
    });

    conversations_list.on("click", ".list-group-item", function (e) {
        e.preventDefault();
        load_conversation($(this).data("id"));
    });

    load_conversations();
    show_greeting();

    // Make the send_message function accessible from outside
    container.data("send_message", send_message);
}

