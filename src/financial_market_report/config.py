from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


def _project_root() -> Path:
    configured = os.environ.get("FINANCIAL_MARKET_REPORT_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _project_root()
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "defaults.yaml"


@dataclass(frozen=True)
class ReportSettings:
    max_tickers: int = 50
    price_of_interest: float = 30.0
    lowest_price: float = 7.0
    daily_volume: int = 1_000_000
    price_change: float = 0.5
    dates_days_interest: int = 30
    news_days_interest: int = 3
    news_page_size: int = 5
    num_news: int = 5
    timezone: str = "America/Toronto"
    get_news: bool = True
    get_plots: bool = True
    send_email: bool = False


@dataclass(frozen=True)
class ScheduleSettings:
    enabled: bool = False
    run_time: str = "04:00"


@dataclass(frozen=True)
class EmailSettings:
    sender_email: str = ""
    target_email: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    use_ssl: bool = False


@dataclass(frozen=True)
class AppConfig:
    report: ReportSettings
    schedule: ScheduleSettings
    email: EmailSettings


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a mapping: {path}")
    return data


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Config section '{name}' must be a mapping")
    return value


def _decode_override_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _coerce_override_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        return int(value)
    if isinstance(default, float):
        return float(value)
    if isinstance(default, str):
        return str(value)
    return value


def _uses_implicit_smtp_ssl(smtp_port: int) -> bool:
    return smtp_port == 465


def _normalize_email_settings(email: dict[str, Any]) -> dict[str, Any]:
    email["smtp_port"] = int(email["smtp_port"])
    email["use_ssl"] = _uses_implicit_smtp_ssl(email["smtp_port"])
    return email


def apply_settings_overrides(config: AppConfig, flat_settings: Mapping[str, Any]) -> AppConfig:
    report = asdict(config.report)
    schedule = asdict(config.schedule)
    email = asdict(config.email)
    sections = {
        "report": report,
        "schedule": schedule,
        "email": email,
    }

    for key, raw_value in flat_settings.items():
        section_name, separator, field_name = key.partition(".")
        if not separator:
            continue
        section = sections.get(section_name)
        if section is None or field_name not in section:
            continue

        value = _decode_override_value(raw_value)
        section[field_name] = _coerce_override_value(value, section[field_name])

    email = _normalize_email_settings(email)

    return AppConfig(
        report=ReportSettings(**report),
        schedule=ScheduleSettings(**schedule),
        email=EmailSettings(**email),
    )


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    data = _load_yaml(config_path)

    email = _section(data, "email")
    email = _normalize_email_settings({**asdict(EmailSettings()), **email})

    return AppConfig(
        report=ReportSettings(**_section(data, "report")),
        schedule=ScheduleSettings(**_section(data, "schedule")),
        email=EmailSettings(**email),
    )
