"""Send the daily 'group pack' email through Gmail (or any SMTP_SSL server)."""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


def smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_USER") and os.environ.get("SMTP_APP_PASSWORD"))


def send_pack(subject: str, body: str, attachment: Path | None = None, smtp_cls=smtplib.SMTP_SSL) -> str:
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_APP_PASSWORD"]
    to = os.environ.get("NOTIFY_EMAIL") or user
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or 465)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    msg.set_content(body)
    if attachment:
        msg.add_attachment(Path(attachment).read_bytes(), maintype="image", subtype="jpeg",
                           filename=Path(attachment).name)
    with smtp_cls(host, port, timeout=30) as server:
        server.login(user, password)
        server.send_message(msg)
    return to
