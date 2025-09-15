# Gemini Integration for Frappe ERPNext

## 1. Purpose

This app integrates Google's Gemini AI and Google Workspace (Gmail, Drive, Calendar) directly into your Frappe ERPNext v15 instance. It provides a powerful, centralized chat interface where you can interact with your ERP data and Google Workspace content seamlessly. The goal is to streamline workflows by allowing users to query documents, generate content, and get insights without leaving their ERP.

## 2. Key Features

*   **Conversational AI Chat:** A central chat interface powered by Google Gemini.
*   **ERPNext Data Integration:**
    *   Directly reference any DocType in your ERPNext instance (e.g., `Project`, `Customer`, `Sales Invoice`) to pull its data into the chat.
    *   An intelligent search function helps you find the right document even if you don't know the exact ID.
*   **Google Workspace Integration:**
    *   Securely connect your Google account using OAuth 2.0.
    *   Search across Gmail, Google Drive, and Google Calendar.
    *   Reference specific emails and documents to get their details and a direct link.
*   **Context-Aware Responses:** The integration combines data from ERPNext and Google Workspace to provide comprehensive, context-aware answers in a single response.
*   **Project Management Tools:**
    *   Automatically generate a list of tasks for a project based on its details.
    *   Analyze a project for potential risks (e.g., budget, timeline, scope creep).

## 3. How It Works

The integration uses a combination of techniques to understand your queries and fetch the right information:

1.  **Reference Detection:** The system scans your chat message for special syntax (`@` references) to identify direct links to ERPNext documents (`@PROJ-00123`) or Google files (`@gdrive/...`).
2.  **Keyword-Based Search:** If no direct references are found, the system looks for keywords like "email," "drive," or "calendar" to target a specific Google Workspace service. It also listens for action words like "list" or "find" to initiate a search in ERPNext.
3.  **Fuzzy Search & Ranking:** When searching ERPNext, the system uses a weighted fuzzy search algorithm (`thefuzz`) to find the most relevant documents, even if your query has typos or incomplete names. It ranks results based on relevance and user feedback.
4.  **Context Assembly:** All the retrieved data from ERPNext and Google Workspace is compiled into a single context block.
5.  **AI Processing:** This context, along with your original prompt and a system instruction, is sent to the Google Gemini API to generate a helpful, human-readable response.

## 4. Installation and Setup

#### Step 1: Install the App

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/Sapphire-Fountains/gemini-integration.git --branch main
bench install-app gemini_integration
```

#### Step 2: Configure Google Cloud Platform

To use the Google Workspace integration, you need to set up a project in the Google Cloud Platform (GCP) and enable the necessary APIs.

1.  **Create a GCP Project:** If you don't have one already, create a new project at the [GCP Console](https://console.cloud.google.com/).
2.  **Enable APIs:** In your project, go to the "APIs & Services" dashboard and enable the following APIs:
    *   Google Drive API
    *   Gmail API
    *   Google Calendar API
    *   Google People API
3.  **Configure OAuth Consent Screen:**
    *   Go to "OAuth consent screen" in the APIs & Services dashboard.
    *   Choose "External" user type and create a new consent screen.
    *   Add the necessary scopes: `.../auth/drive.readonly`, `.../auth/gmail.readonly`, `.../auth/calendar.readonly`, `.../auth/userinfo.email`, and `openid`.
    *   Add your Frappe site domain to the "Authorized domains" list.
4.  **Create OAuth 2.0 Credentials:**
    *   Go to "Credentials" and create a new "OAuth 2.0 Client ID."
    *   Select "Web application" as the type.
    *   Add your site's callback URL to the "Authorized redirect URIs" list:
        `https://<your-frappe-site>/api/method/gemini_integration.api.handle_google_callback`
    *   Copy the **Client ID** and **Client Secret**.

#### Step 3: Configure the App in ERPNext

1.  **Gemini Settings:**
    *   Go to the "Gemini Settings" page in your ERPNext Desk.
    *   Enter the **API Key** for the Google Gemini AI service. You can get this from [Google AI Studio](https://aistudio.google.com/app/apikey).
2.  **Social Login Keys (Google):**
    *   Go to the "Social Login Keys" page and open the "Google" document.
    *   Check the "Enable Social Login" box.
    *   Paste the **Client ID** and **Client Secret** you copied from GCP.

## 5. Usage

Once installed and configured, you can access the chat interface from the **Gemini Chat** page in your Desk.

#### 1. Interacting with ERPNext Data

*   **Direct Reference:** To pull data from a specific ERPNext document, use the `@` symbol followed by the document's ID.
    *   **Syntax:** `@DOCTYPE-ID` or `@"Document Name"`
    *   **Example:** `What is the status of project @PRJ-00183?` or `Summarize the last communication with customer @"Valley Fair"`.
*   **Smart Search:** If you're not sure of the exact ID, you can ask a general question. The system will try to find the most relevant document for you.
    *   **Example:** `Find the sales order for the latest shipment to ACME Corp.`
    *   If multiple potential matches are found, the system will ask you to choose the correct one.

#### 2. Interacting with Google Workspace

1.  **Connect Your Account:** The first time you use a Google service, the system will prompt you to connect your account. Click the link, sign in with Google, and grant the necessary permissions.
2.  **Search Your Workspace:**
    *   **Keyword Search:** Use terms like `email`, `drive`, `file`, or `calendar` to target a specific service.
        *   `Search my email for the latest updates from Riverton City.`
        *   `Find the contract file in my drive for the Main Street Fountain project.`
        *   `What is on my calendar for next week?`
    *   **General Search:** If you don't use keywords, Gemini will automatically search Gmail and Google Drive for relevant information based on your query.
3.  **Reference Specific Items:** To pull in a specific file or email, use the `@gdrive` or `@gmail` reference followed by the item's ID.
    *   **Syntax:** `@gdrive/file_id` or `@gmail/message_id`
    *   **Example:** `Summarize the document @gdrive/1a2b3c4d5e6f...`

#### 3. Combining Queries

The real power comes from combining these references in a single, natural language query.

**Example:**
`Draft a follow-up email to the contact in @CUST-00234 regarding the issues mentioned in @gmail/a1b2c3d4e5f6. Use the service details from @SC-00105 as a reference.`

## 6. Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/gemini_integration
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

## 7. License

This project is licensed under the **MIT License**. See the `license.txt` file for details.
