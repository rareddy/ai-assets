"""Google OAuth 2.0 consent flow and credential management."""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger(__name__)

# Read-only scopes required by Calendar, Drive, and Gmail skills
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/drive.activity.readonly",
    # gmail.metadata enforces body exclusion at the OAuth layer (FR-010a)
    "https://www.googleapis.com/auth/gmail.metadata",
]

_CREDENTIALS_PATH = Path.home() / ".status-report" / "google_credentials.json"


def _ensure_dir() -> None:
    """Create ~/.status-report/ with restricted permissions if needed."""
    cred_dir = _CREDENTIALS_PATH.parent
    cred_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(cred_dir, stat.S_IRWXU)  # chmod 700


def load_credentials() -> Optional[Credentials]:
    """Load stored Google credentials, refreshing if expired.

    Returns None if no credentials file exists (consent not yet completed).
    """
    if not _CREDENTIALS_PATH.exists():
        return None

    creds = Credentials.from_authorized_user_file(str(_CREDENTIALS_PATH), SCOPES)

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds)
        except Exception as exc:
            logger.warning("Failed to refresh Google credentials: %s", exc)
            return None

    return creds if creds.valid else None


def _save_credentials(creds: Credentials) -> None:
    """Write credentials to disk with chmod 600."""
    _ensure_dir()
    _CREDENTIALS_PATH.write_text(creds.to_json())
    os.chmod(_CREDENTIALS_PATH, stat.S_IRUSR | stat.S_IWUSR)  # chmod 600


def run_consent_flow(client_id: str, client_secret: str) -> Credentials:
    """Run the one-time browser-based OAuth consent flow.

    Called by: uv run python -m status_report.auth.google --consent
    """
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)
    _save_credentials(creds)
    logger.info("Google credentials saved to %s", _CREDENTIALS_PATH)
    return creds


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Google OAuth consent flow")
    parser.add_argument("--consent", action="store_true", help="Run one-time consent flow")
    args = parser.parse_args()

    if args.consent:
        client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            print("ERROR: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in your .env or environment", file=sys.stderr)
            sys.exit(1)
        run_consent_flow(client_id, client_secret)
        print(f"Credentials saved to {_CREDENTIALS_PATH}")
    else:
        parser.print_help()
