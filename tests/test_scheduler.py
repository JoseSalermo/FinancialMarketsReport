from datetime import datetime
from zoneinfo import ZoneInfo

import financial_market_report.scheduler as scheduler_module
from financial_market_report.config import apply_settings_overrides, load_config
from financial_market_report.scheduler import ReportScheduler
from financial_market_report.storage.repository import update_settings


def test_scheduler_skips_unselected_weekend_day(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "app.sqlite3"
    update_settings(
        db_path,
        {
            "schedule.enabled": True,
            "schedule.run_time": "09:00",
            "schedule.run_days": ["mon", "tue", "wed", "thu", "fri"],
        },
    )
    calls = []
    monkeypatch.setattr(scheduler_module, "run_report", lambda **kwargs: calls.append(kwargs))

    scheduler = ReportScheduler(db_path=db_path)
    result = scheduler.tick(datetime(2026, 5, 2, 9, 5, tzinfo=ZoneInfo("America/Toronto")))

    assert result is False
    assert calls == []


def test_scheduler_runs_on_selected_weekday(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "app.sqlite3"
    update_settings(
        db_path,
        {
            "schedule.enabled": True,
            "schedule.run_time": "09:00",
            "schedule.run_days": ["mon", "tue", "wed", "thu", "fri"],
        },
    )
    calls = []
    monkeypatch.setattr(scheduler_module, "run_report", lambda **kwargs: calls.append(kwargs))

    scheduler = ReportScheduler(db_path=db_path)
    result = scheduler.tick(datetime(2026, 5, 4, 9, 5, tzinfo=ZoneInfo("America/Toronto")))

    assert result is True
    assert len(calls) == 1


def test_next_scheduled_at_skips_to_next_selected_day(tmp_path) -> None:
    config = apply_settings_overrides(
        load_config(),
        {
            "schedule.enabled": True,
            "schedule.run_time": "09:00",
            "schedule.run_days": ["mon", "tue", "wed", "thu", "fri"],
        },
    )
    scheduler = ReportScheduler(db_path=tmp_path / "app.sqlite3")

    next_run = scheduler._next_scheduled_at(
        config,
        datetime(2026, 5, 2, 10, 0, tzinfo=ZoneInfo("America/Toronto")),
    )

    assert next_run == datetime(2026, 5, 4, 9, 0, tzinfo=ZoneInfo("America/Toronto"))
