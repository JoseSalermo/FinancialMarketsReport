from __future__ import annotations

import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from pathlib import Path


def send_html_email_with_attachment(
    *,
    sender_email: str,
    receiver_email: str | list[str],
    subject: str,
    html_path: str | Path,
    app_password: str,
    summary_html: str | None = None,
    smtp_host: str = "smtp.gmail.com",
    smtp_port: int = 465,
) -> None:
    html_file = Path(html_path)
    if not html_file.exists():
        raise FileNotFoundError(f"HTML file not found: {html_file}")

    msg = MIMEMultipart("mixed")
    msg["From"] = sender_email
    msg["To"] = ", ".join(receiver_email) if isinstance(receiver_email, list) else receiver_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText("Full market report attached.", "plain", _charset="utf-8"))
    alt.attach(MIMEText(summary_html or "<p>Full market report attached.</p>", "html", _charset="utf-8"))
    msg.attach(alt)

    part = MIMEApplication(html_file.read_bytes(), _subtype="html")
    part.add_header("Content-Disposition", "attachment", filename=html_file.name)
    msg.attach(part)

    size_mb = os.path.getsize(html_file) / (1024 * 1024)
    print(f"Attachment size: {size_mb:.2f} MB.")

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        server.login(sender_email, app_password)
        server.send_message(msg)
