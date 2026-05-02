from __future__ import annotations

import os
import smtplib
import time
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
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
    body_html: str | None = None,
    inline_image_paths: list[str | Path] | None = None,
    smtp_host: str = "smtp.gmail.com",
    smtp_port: int = 465,
    smtp_use_ssl: bool = True,
    smtp_timeout_seconds: float = 30.0,
    smtp_attempts: int = 3,
) -> None:
    html_file = Path(html_path)
    if not html_file.exists():
        raise FileNotFoundError(f"HTML file not found: {html_file}")

    msg = MIMEMultipart("mixed")
    msg["From"] = sender_email
    msg["To"] = ", ".join(receiver_email) if isinstance(receiver_email, list) else receiver_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)

    related = MIMEMultipart("related")
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText("Full market report included below and attached.", "plain", _charset="utf-8"))
    alt.attach(MIMEText(body_html or summary_html or "<p>Full market report attached.</p>", "html", _charset="utf-8"))
    related.attach(alt)

    seen_images: set[Path] = set()
    for raw_path in inline_image_paths or []:
        image_path = Path(raw_path)
        if image_path in seen_images or not image_path.exists():
            continue
        seen_images.add(image_path)
        image = MIMEImage(image_path.read_bytes())
        image.add_header("Content-ID", f"<{image_path.name}>")
        image.add_header("Content-Disposition", "inline", filename=image_path.name)
        related.attach(image)

    msg.attach(related)

    part = MIMEApplication(html_file.read_bytes(), _subtype="html")
    part.add_header("Content-Disposition", "attachment", filename=html_file.name)
    msg.attach(part)

    size_mb = os.path.getsize(html_file) / (1024 * 1024)
    print(f"Attachment size: {size_mb:.2f} MB.")

    if smtp_attempts < 1:
        raise ValueError("smtp_attempts must be at least 1")

    def send_once() -> None:
        if smtp_use_ssl:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=smtp_timeout_seconds) as server:
                server.login(sender_email, app_password)
                server.send_message(msg)
            return

        with smtplib.SMTP(smtp_host, smtp_port, timeout=smtp_timeout_seconds) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender_email, app_password)
            server.send_message(msg)

    for attempt in range(1, smtp_attempts + 1):
        try:
            send_once()
            return
        except smtplib.SMTPAuthenticationError:
            raise
        except (OSError, smtplib.SMTPException):
            if attempt == smtp_attempts:
                raise
            time.sleep(min(2 * attempt, 5))
