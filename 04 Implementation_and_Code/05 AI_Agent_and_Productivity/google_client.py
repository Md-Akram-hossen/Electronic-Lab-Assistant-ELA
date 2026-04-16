from __future__ import annotations

import base64
import logging
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Iterable

from .config import get_settings

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except Exception:
    Request = None
    Credentials = None
    InstalledAppFlow = None
    build = None

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def get_google_credentials():
    settings = get_settings()
    if Credentials is None or build is None:
        return None
    creds = None
    if settings.token_path.exists():
        creds = Credentials.from_authorized_user_file(str(settings.token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token and Request is not None:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds:
            if not settings.credentials_path.exists() or InstalledAppFlow is None:
                logging.error("Google credentials.json not found")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(str(settings.credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)
            settings.token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_gmail_service():
    creds = get_google_credentials()
    if not creds or build is None:
        return None
    try:
        return build("gmail", "v1", credentials=creds)
    except Exception as exc:
        logging.error("Gmail service build failed: %s", exc)
        return None


def get_calendar_service():
    creds = get_google_credentials()
    if not creds or build is None:
        return None
    try:
        return build("calendar", "v3", credentials=creds)
    except Exception as exc:
        logging.error("Calendar service build failed: %s", exc)
        return None


def _gmail_send_raw_mime(mime_root):
    service = get_gmail_service()
    if not service:
        return False, "Gmail not configured"
    try:
        raw = base64.urlsafe_b64encode(mime_root.as_bytes()).decode()
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True, f"Email sent ({sent.get('id')})"
    except Exception as exc:
        logging.error("Send email error: %s", exc)
        return False, f"Error: {exc}"


def send_simple_email(to: str, subject: str, body: str):
    message = MIMEText(body, "plain")
    message["to"] = to
    message["subject"] = subject
    return _gmail_send_raw_mime(message)


def send_email_with_attachment(
    to: str,
    subject: str,
    body: str,
    attachments: Iterable[tuple[str, str, bytes]] | None = None,
):
    message = MIMEMultipart()
    message["to"] = to
    message["subject"] = subject
    message.attach(MIMEText(body, "plain"))
    for filename, mimetype, content in attachments or []:
        main, sub = mimetype.split("/", 1)
        part = MIMEBase(main, sub)
        part.set_payload(content)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        message.attach(part)
    return _gmail_send_raw_mime(message)
