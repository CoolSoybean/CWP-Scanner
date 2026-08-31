from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText


def send_email(
    subject: str,
    html: str,
    *,
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    sender: str | None = None,
    recipient: str | None = None,
) -> None:
    smtp_host = host or os.getenv("SMTP_HOST")
    smtp_port = port or int(os.getenv("SMTP_PORT", "587"))
    smtp_username = username or os.getenv("SMTP_USERNAME")
    smtp_password = password or os.getenv("SMTP_PASSWORD")
    from_address = sender or os.getenv("EMAIL_FROM") or smtp_username
    to_address = recipient or os.getenv("EMAIL_TO")
    missing = [
        name
        for name, value in {
            "SMTP_HOST": smtp_host,
            "SMTP_USERNAME": smtp_username,
            "SMTP_PASSWORD": smtp_password,
            "EMAIL_FROM": from_address,
            "EMAIL_TO": to_address,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Email configuration missing: {', '.join(missing)}")

    message = MIMEText(html, "html", "utf-8")
    message["Subject"] = subject
    message["From"] = from_address
    message["To"] = to_address
    with smtplib.SMTP(str(smtp_host), smtp_port, timeout=30) as client:
        client.starttls()
        client.login(str(smtp_username), str(smtp_password))
        client.sendmail(str(from_address), [str(to_address)], message.as_string())
