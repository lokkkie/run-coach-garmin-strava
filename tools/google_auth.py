"""
Shared Google OAuth helper for Sheets integration.
First run triggers a browser-based auth flow and writes token.json.
Subsequent runs read/refresh from token.json automatically.
"""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
TOKEN_FILE = PROJECT_ROOT / "token.json"


def get_credentials():
    """Return valid Google OAuth credentials, prompting browser auth if needed."""
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"credentials.json not found at {CREDENTIALS_FILE}.\n\n"
                    "Setup steps:\n"
                    "  1. Go to https://console.cloud.google.com/\n"
                    "  2. Enable the Google Sheets API\n"
                    "  3. Create OAuth 2.0 Client ID (Desktop app)\n"
                    "  4. Download the JSON and save it as credentials.json in the project root."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return creds
