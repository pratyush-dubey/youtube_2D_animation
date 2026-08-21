"""
YouTube Data API v3 — OAuth 2.0 authentication.

Flow:
  1. First run: opens browser for user consent → saves token to disk.
  2. Subsequent runs: loads saved token, refreshes automatically when expired.

Never stores secrets in code. All credentials come from environment variables.
"""
from __future__ import annotations

import json
from pathlib import Path

import structlog

from app.config.settings import settings

logger = structlog.get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def get_credentials():
    """
    Return valid Google OAuth2 credentials for the YouTube Data API.

    On first call (no token file):
      - Opens a browser window for the user to grant access.
      - Saves the resulting token (including refresh token) to disk.

    On subsequent calls:
      - Loads the saved token.
      - Refreshes it automatically if expired.

    Returns:
        google.oauth2.credentials.Credentials

    Raises:
        ValueError: If client_id or client_secret are not configured.
        ImportError: If google-auth-oauthlib is not installed.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
    except ImportError as exc:
        raise ImportError(
            "google-auth-oauthlib not installed. "
            "Run: pip install google-auth-oauthlib google-auth-httplib2"
        ) from exc

    if not settings.youtube_client_id or not settings.youtube_client_secret:
        raise ValueError(
            "YouTube credentials not configured. "
            "Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env"
        )

    token_path: Path = settings.youtube_token_file
    creds = None

    # Load existing token
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            logger.info("youtube_token_loaded", path=str(token_path))
        except Exception as exc:
            logger.warning("youtube_token_load_failed", error=str(exc))
            creds = None

    # Refresh or re-authenticate
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            logger.info("youtube_token_refreshed")
            _save_token(creds, token_path)
        except Exception as exc:
            logger.warning("youtube_token_refresh_failed", error=str(exc))
            creds = None

    if not creds or not creds.valid:
        client_config = {
            "installed": {
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        logger.info("youtube_oauth_starting_browser_flow")
        creds = flow.run_local_server(port=0)
        _save_token(creds, token_path)
        logger.info("youtube_oauth_complete", token_path=str(token_path))

    return creds


def _save_token(creds, token_path: Path) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else [],
    }
    token_path.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
    logger.info("youtube_token_saved", path=str(token_path))
