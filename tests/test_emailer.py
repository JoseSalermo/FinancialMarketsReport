from pathlib import Path

import financial_market_report.emailer.smtp as smtp_module


def test_smtp_sender_uses_ssl_timeout(monkeypatch, tmp_path: Path) -> None:
    html_path = tmp_path / "report.html"
    html_path.write_text("<html><body>Report</body></html>", encoding="utf-8")
    calls: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            calls["host"] = host
            calls["port"] = port
            calls["timeout"] = timeout

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def login(self, sender_email: str, app_password: str) -> None:
            calls["sender_email"] = sender_email
            calls["app_password"] = app_password

        def send_message(self, message: object) -> None:
            calls["sent"] = True

    monkeypatch.setattr(smtp_module.smtplib, "SMTP_SSL", FakeSMTP)

    smtp_module.send_html_email_with_attachment(
        sender_email="sender@example.com",
        receiver_email="target@example.com",
        subject="Report",
        html_path=html_path,
        app_password="password",
        smtp_timeout_seconds=12.5,
    )

    assert calls["host"] == "smtp.gmail.com"
    assert calls["port"] == 465
    assert calls["timeout"] == 12.5
    assert calls["sender_email"] == "sender@example.com"
    assert calls["app_password"] == "password"
    assert calls["sent"] is True


def test_smtp_sender_supports_starttls(monkeypatch, tmp_path: Path) -> None:
    html_path = tmp_path / "report.html"
    html_path.write_text("<html><body>Report</body></html>", encoding="utf-8")
    calls: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            calls["host"] = host
            calls["port"] = port
            calls["timeout"] = timeout

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def starttls(self) -> None:
            calls["starttls"] = True

        def ehlo(self) -> None:
            calls["ehlo_count"] = int(calls.get("ehlo_count", 0)) + 1

        def login(self, sender_email: str, app_password: str) -> None:
            calls["sender_email"] = sender_email
            calls["app_password"] = app_password

        def send_message(self, message: object) -> None:
            calls["sent"] = True

    monkeypatch.setattr(smtp_module.smtplib, "SMTP", FakeSMTP)

    smtp_module.send_html_email_with_attachment(
        sender_email="sender@example.com",
        receiver_email="target@example.com",
        subject="Report",
        html_path=html_path,
        app_password="password",
        smtp_port=587,
        smtp_use_ssl=False,
    )

    assert calls["host"] == "smtp.gmail.com"
    assert calls["port"] == 587
    assert calls["timeout"] == 30.0
    assert calls["ehlo_count"] == 2
    assert calls["starttls"] is True
    assert calls["sender_email"] == "sender@example.com"
    assert calls["app_password"] == "password"
    assert calls["sent"] is True


def test_smtp_sender_retries_transient_starttls_failure(monkeypatch, tmp_path: Path) -> None:
    html_path = tmp_path / "report.html"
    html_path.write_text("<html><body>Report</body></html>", encoding="utf-8")
    calls = {"attempts": 0}

    class FakeSMTP:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            calls["attempts"] += 1

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def ehlo(self) -> None:
            return None

        def starttls(self) -> None:
            if calls["attempts"] == 1:
                raise TimeoutError("timed out")

        def login(self, sender_email: str, app_password: str) -> None:
            return None

        def send_message(self, message: object) -> None:
            calls["sent"] = True

    monkeypatch.setattr(smtp_module.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtp_module.time, "sleep", lambda seconds: None)

    smtp_module.send_html_email_with_attachment(
        sender_email="sender@example.com",
        receiver_email="target@example.com",
        subject="Report",
        html_path=html_path,
        app_password="password",
        smtp_port=587,
        smtp_use_ssl=False,
    )

    assert calls["attempts"] == 2
    assert calls["sent"] is True
