"""OAuth2 authentication and token management for Gmail API."""

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _get_credentials_dir() -> Path:
    return Path(__file__).parent / "credentials"


def _get_client_secrets_path() -> Path:
    return _get_credentials_dir() / "credentials.json"


def _get_token_path(account_alias: str) -> Path:
    return _get_credentials_dir() / f"token_{account_alias}.json"


def load_credentials(account_alias: str) -> Credentials | None:
    """Load saved credentials for an account, refreshing if expired."""
    token_path = _get_token_path(account_alias)
    if not token_path.exists():
        return None

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
    return creds


def run_oauth_flow(account_alias: str) -> Credentials:
    """Run the interactive OAuth2 flow for an account. Opens a browser."""
    client_secrets = _get_client_secrets_path()
    if not client_secrets.exists():
        raise FileNotFoundError(
            f"OAuth client secrets not found at {client_secrets}. "
            "Download from Google Cloud Console → APIs & Services → Credentials."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path = _get_token_path(account_alias)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())

    return creds
