"""Shared SMTP transport; notification policies belong to their callers."""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

from .imports.config import setting


def send_message(message: EmailMessage) -> None:
    host = os.environ.get("RPG_LIBRARIAN_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("RPG_LIBRARIAN_SMTP_PORT", "465"))
    context = ssl.create_default_context()
    mode = os.environ.get("RPG_LIBRARIAN_SMTP_TLS", "ssl")
    if mode not in ("ssl", "starttls"):
        raise ValueError("SMTP requires ssl or starttls.")
    connection = (
        smtplib.SMTP_SSL(host, port, timeout=30, context=context)
        if mode == "ssl"
        else smtplib.SMTP(host, port, timeout=30)
    )
    with connection as smtp:
        if mode == "starttls":
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
        smtp.login(setting("SMTP_USERNAME"), setting("SMTP_PASSWORD").replace(" ", ""))
        if smtp.send_message(message):
            raise RuntimeError("SMTP refused a notification recipient.")
