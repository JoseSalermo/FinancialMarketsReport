from financial_market_report.config import apply_settings_overrides, load_config


def test_email_addresses_are_regular_settings() -> None:
    config = load_config()

    updated = apply_settings_overrides(
        config,
        {
            "email.sender_email": "sender@example.com",
            "email.target_email": "target@example.com",
        },
    )

    assert updated.email.sender_email == "sender@example.com"
    assert updated.email.target_email == "target@example.com"


def test_email_ssl_mode_is_inferred_from_smtp_port() -> None:
    config = load_config()

    starttls = apply_settings_overrides(config, {"email.smtp_port": "587", "email.use_ssl": "true"})
    implicit_ssl = apply_settings_overrides(config, {"email.smtp_port": "465", "email.use_ssl": "false"})

    assert starttls.email.use_ssl is False
    assert implicit_ssl.email.use_ssl is True


def test_schedule_run_days_default_to_weekdays() -> None:
    config = load_config()

    assert config.schedule.run_days == ("mon", "tue", "wed", "thu", "fri")


def test_schedule_run_days_can_be_overridden() -> None:
    config = load_config()

    updated = apply_settings_overrides(config, {"schedule.run_days": '["mon", "wed", "sunday"]'})

    assert updated.schedule.run_days == ("mon", "wed", "sun")
