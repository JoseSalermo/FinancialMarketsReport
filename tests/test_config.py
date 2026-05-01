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
