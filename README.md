### Gemini Integration

Google Gemini integration with Frappe ERPNext 15.

### Features

*   **Conversational AI:** Chat with Google Gemini to ask questions and get information.
*   **ERPNext Data Integration:** Reference any document in your ERPNext instance to pull its data directly into the chat.
*   **Google Workspace Integration:**
    *   Search your Gmail, Google Drive, and Google Calendar.
    *   Reference specific emails and documents to get their details and a direct link.
*   **Context-Aware Responses:** The integration combines data from ERPNext and Google Workspace to provide comprehensive, context-aware answers.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch main
bench install-app gemini_integration
```

### Usage

Once installed, you can access the chat interface from the "Gemini Chat" page in your Desk. Here’s how to interact with the AI:

#### 1. Interacting with ERPNext Data

To pull data from a specific ERPNext document, use the `@` symbol followed by the document's ID. 

**Syntax:** `@DOCTYPE-ID` or `@"Document Name"`

**Examples:**
*   `What is the status of project @PRJ-00183?`
*   `Summarize the last communication with customer @"Valley Fair"`
*   `Who is the contact for supplier @SUPP-0001?`

> **Note:** If you write a query that looks like it contains a document ID (e.g., `PRJ-00183`) but forget the `@`, the system will gently remind you to use the correct format to avoid errors.

#### 2. Interacting with Google Workspace

##### Searching Your Workspace

You can perform searches across your Google Workspace by using keywords or just asking a general question.

*   **Keyword Search:** Use terms like `email`, `drive`, `file`, or `calendar` to target a specific service.
    *   `Search my email for the latest updates from Riverton City.`
    *   `Find the contract file in my drive for the Main Street Fountain project.`
    *   `What is on my calendar for next week?`

*   **General Search:** If you don't use keywords, Gemini will automatically search Gmail and Google Drive for relevant information based on your query.
    *   `What's the latest on the Riverton City project?` (This will search both Gmail and Drive for that text).

##### Referencing Specific Items

To pull in a specific file from Google Drive or a specific email thread from Gmail, use the `@gdrive` or `@gmail` reference followed by the item's ID.

**Syntax:**
*   `@gdrive/file_id`
*   `@gmail/message_id`

**Examples:**
*   `Summarize the document @gdrive/1a2b3c4d5e6f...`
*   `What was the final decision in the email thread @gmail/a1b2c3d4e5f6...?`

#### 3. Combining Queries

The real power comes from combining these references in a single query.

**Example:**
`Draft a follow-up email to the contact in @CUST-00234 regarding the issues mentioned in @gmail/a1b2c3d4e5f6. Use the service details from @SC-00105 as a reference.`

### Contributing

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

### License

mit
