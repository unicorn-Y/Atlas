# Google Drive and Gmail read-only connector

The Integrations settings panel can sign in to one Google account, search its Drive files or Gmail messages, and import only documents the user selects. Atlas requests `drive.readonly` and `gmail.readonly`; it does not send, move, edit, or delete cloud data. OAuth uses a PKCE verifier and a loopback callback bound to `127.0.0.1`. The access and refresh tokens stay in the local Atlas data directory and never appear in the API response, UI, logs, or agent context.

## Set up a local OAuth client

1. Create or select a Google Cloud project, enable the Google Drive API and Gmail API, and configure the OAuth consent screen.
2. Create an OAuth client with application type **Desktop app**. Add your Google account as a test user while the consent screen is in Testing.
3. Copy the client ID into Atlas → Settings → Integrations → Google Drive and Gmail. Atlas uses PKCE and does not ask for a client secret.
4. Select **Save and sign in to Google**, finish consent in the system browser, then search Drive or Gmail in the same panel.

Google continues to support loopback redirects for desktop OAuth clients. Gmail `gmail.readonly` is a restricted scope; when an app uses a consent screen you control, Google may require user/test-user configuration or verification according to the app's publishing status. See [Google's desktop OAuth guidance](https://developers.google.com/identity/protocols/oauth2/resources/loopback-migration) and [Gmail scope classifications](https://developers.google.com/workspace/gmail/api/auth/scopes).

## Import behavior

Drive shows recent files and accepts a filename search. Google Docs are exported as `text/plain`; `text/*`, JSON, and XML files are imported as UTF-8 with replacement for malformed bytes. Other binary types fail with an explicit unsupported-format message. Gmail searches recent message metadata first and fetches the full body only after the user chooses **Import this turn**. Imported content is bounded to 200,000 characters, includes its source URL, and is labeled as untrusted reference material before it enters the current message draft. Drive export follows the [Google Drive files.export API](https://developers.google.com/workspace/drive/api/guides/manage-downloads); Gmail uses [messages.list](https://developers.google.com/workspace/gmail/api/guides/list-messages) followed by messages.get.

The existing generic MCP server list and OAuth integrations remain available alongside this connector.
