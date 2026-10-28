# ClipboardToSheets

## Setup

1. Install Python 3.10 or newer on Windows.
2. Download and extract this repository.
3. Set up a Google Cloud service account with the Google Sheets API and Google Drive API enabled.
4. Save its JSON key beside the app as `credentials.json`.
5. Share your Google Sheet with the service account email and give it Editor access.
6. Open `clipboard_to_sheets.py` and set `SPREADSHEET_KEY`, `SPREADSHEET_NAME`, and `WORKSHEET_NAME` in the configuration section.

Run `RUN.bat`. It checks and installs the Python packages, then opens ClipboardToSheets without leaving a console window running.

## Use

- Click **Turn ON** to log new clipboard text to Google Sheets.
- Click **Turn OFF** to pause logging.
- Click **Reconnect** if the connection fails.
- Desktop notifications report connection status, toggles, successful writes, and write errors.
- Values are written in a zigzag pattern: A1, B1, A2, B2, and so on. No timestamps are written to the sheet.

## Important

When logging is ON, copied text is sent to your configured Google Sheet. Do not copy passwords or other sensitive information while logging is enabled. Turn logging OFF first when needed.

The app processes clipboard text locally before sending it to the configured Google Sheet. Keep `credentials.json` private; it is excluded from Git by `.gitignore`.
