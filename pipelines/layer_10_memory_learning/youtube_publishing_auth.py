"""
Helpers for authenticated access to the owner's YouTube channel.

This module manages:
  - OAuth client secret discovery
  - local token storage / refresh
  - interactive authorization for first-time setup
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from config.paths import ENV_FILE, ROOT, SECRETS_DIR


YOUTUBE_OWNER_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def _load_env() -> None:
    load_dotenv(ENV_FILE)


def _require_google_auth():
    try:
        from google.auth.transport.requests import AuthorizedSession, Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError(
            "Google OAuth dependencies are missing. Install requirements.txt "
            "so the YouTube publishing workflow can authenticate."
        ) from exc
    return AuthorizedSession, Request, Credentials, InstalledAppFlow


def oauth_client_secret_path() -> Path:
    _load_env()
    raw = os.getenv(
        "YOUTUBE_OAUTH_CLIENT_SECRET_PATH",
        str(SECRETS_DIR / "youtube_oauth_client.json"),
    )
    return Path(raw).expanduser()


def oauth_token_path() -> Path:
    _load_env()
    raw = os.getenv(
        "YOUTUBE_OAUTH_TOKEN_PATH",
        str(SECRETS_DIR / "youtube_oauth_token.json"),
    )
    return Path(raw).expanduser()


def _save_credentials(creds, token_path: Path) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")


def _load_credentials_from_disk(token_path: Path, scopes: list[str]):
    _, _, Credentials, _ = _require_google_auth()
    if not token_path.exists():
        return None
    return Credentials.from_authorized_user_file(str(token_path), scopes=scopes)


def ensure_credentials(
    interactive: bool = False,
    scopes: list[str] | None = None,
    open_browser: bool = True,
):
    """
    Return valid OAuth credentials for the publishing channel owner.

    If `interactive` is False and no valid token exists yet, this raises a clear
    error that tells the user to run the authorization flow first.
    """
    AuthorizedSession, Request, _, InstalledAppFlow = _require_google_auth()
    scopes = scopes or list(YOUTUBE_OWNER_SCOPES)
    client_path = oauth_client_secret_path()
    token_path = oauth_token_path()

    if not client_path.exists():
        raise FileNotFoundError(
            f"YouTube OAuth client secret file not found at {client_path}. "
            "Place the downloaded desktop-app OAuth JSON there or update "
            "YOUTUBE_OAUTH_CLIENT_SECRET_PATH in .env."
        )

    creds = _load_credentials_from_disk(token_path, scopes)
    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_credentials(creds, token_path)
        return creds

    if not interactive:
        raise RuntimeError(
            "No valid YouTube OAuth token is available. Run the publishing-memory "
            "authorization flow first with interactive auth enabled."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), scopes=scopes)
    creds = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        authorization_prompt_message=(
            "Open this URL in your browser to authorize YouTube owner-channel access:\n{url}"
        ),
        success_message=(
            "YouTube channel authorization completed. You can close this browser tab."
        ),
        open_browser=open_browser,
    )
    _save_credentials(creds, token_path)
    return creds


def authorized_session(interactive: bool = False, scopes: list[str] | None = None):
    AuthorizedSession, _, _, _ = _require_google_auth()
    creds = ensure_credentials(interactive=interactive, scopes=scopes)
    return AuthorizedSession(creds)


def authorization_status() -> dict:
    """
    Lightweight local status check used by docs / CLI messages.
    """
    client_path = oauth_client_secret_path()
    token_path = oauth_token_path()
    return {
        "oauth_client_secret_path": str(client_path),
        "oauth_client_secret_exists": client_path.exists(),
        "oauth_token_path": str(token_path),
        "oauth_token_exists": token_path.exists(),
        "scopes": list(YOUTUBE_OWNER_SCOPES),
    }


if __name__ == "__main__":
    status = authorization_status()
    print(json.dumps(status, indent=2))
