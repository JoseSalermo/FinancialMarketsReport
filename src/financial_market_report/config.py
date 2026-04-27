from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
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
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    use_ssl: bool = True


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


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    data = _load_yaml(config_path)

    return AppConfig(
        report=ReportSettings(**_section(data, "report")),
        schedule=ScheduleSettings(**_section(data, "schedule")),
        email=EmailSettings(**_section(data, "email")),
    )
