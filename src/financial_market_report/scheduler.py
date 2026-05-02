from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from financial_market_report.config import RUN_DAY_CHOICES, RUN_DAY_VALUES, AppConfig, apply_settings_overrides, load_config
from financial_market_report.runner import run_report
from financial_market_report.storage.repository import (
    get_running_report_run,
    get_settings,
    scheduled_run_exists,
)


LOGGER = logging.getLogger(__name__)


def parse_run_time(value: str) -> tuple[int, int]:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("run_time must use HH:MM format")

    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("run_time must be a valid 24-hour time")
    return hour, minute


def format_scheduler_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S %Z%z")


def format_run_days(run_days: tuple[str, ...]) -> str:
    labels = {value: label for value, label in RUN_DAY_CHOICES}
    return ", ".join(labels[day] for day in run_days if day in labels)


class ReportScheduler:
    def __init__(
        self,
        *,
        db_path: str | Path | None,
        output_dir: str | Path | None = None,
        interval_seconds: int = 60,
    ) -> None:
        self.db_path = db_path
        self.output_dir = output_dir
        self.interval_seconds = max(5, interval_seconds)
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_run_date: str | None = None
        self._last_checked_at: str | None = None
        self._last_started_at: str | None = None
        self._last_finished_at: str | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="financial-market-report-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def tick(self, now: datetime | None = None) -> bool:
        try:
            config = self._load_effective_config()
            tz = ZoneInfo(config.report.timezone)
            checked_at = now.astimezone(tz) if now else datetime.now(tz)
            self._set_state(last_checked_at=format_scheduler_datetime(checked_at), last_error=None)

            if not config.schedule.enabled:
                return False

            scheduled_at = self._scheduled_at(config, checked_at)
            if not self._is_scheduled_day(config, scheduled_at):
                return False

            if checked_at < scheduled_at:
                return False

            run_date = scheduled_at.date().isoformat()
            if self._already_handled(run_date):
                return False

            if scheduled_run_exists(self.db_path, run_date=run_date, trigger="schedule"):
                self._set_state(last_run_date=run_date)
                return False

            if get_running_report_run(self.db_path) is not None:
                return False

            return self._run_report(run_date=run_date, started_at=checked_at)
        except Exception as exc:
            message = f"{exc.__class__.__name__}: {exc}"
            self._set_state(last_error=message)
            LOGGER.exception("Scheduler tick failed")
            return False

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            state = {
                "thread_alive": self._thread is not None and self._thread.is_alive(),
                "running": self._running,
                "last_run_date": self._last_run_date,
                "last_checked_at": self._last_checked_at,
                "last_started_at": self._last_started_at,
                "last_finished_at": self._last_finished_at,
                "last_error": self._last_error,
                "interval_seconds": self.interval_seconds,
            }

        try:
            config = self._load_effective_config()
            tz = ZoneInfo(config.report.timezone)
            now = datetime.now(tz)
            next_run_at = None
            if config.schedule.enabled:
                next_run = self._next_scheduled_at(config, now)
                next_run_at = format_scheduler_datetime(next_run) if next_run else None

            state.update(
                {
                    "enabled": config.schedule.enabled,
                    "run_time": config.schedule.run_time,
                    "run_days": config.schedule.run_days,
                    "run_days_label": format_run_days(config.schedule.run_days),
                    "timezone": config.report.timezone,
                    "next_run_at": next_run_at,
                }
            )
        except Exception as exc:
            state.update(
                {
                    "enabled": False,
                    "run_time": None,
                    "run_days": (),
                    "run_days_label": None,
                    "timezone": None,
                    "next_run_at": None,
                    "last_error": f"{exc.__class__.__name__}: {exc}",
                }
            )

        return state

    def clear_last_run_date(self) -> str | None:
        with self._state_lock:
            previous = self._last_run_date
            self._last_run_date = None
            return previous

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self.tick()
            self._stop_event.wait(self.interval_seconds)

    def _load_effective_config(self) -> AppConfig:
        return apply_settings_overrides(load_config(), get_settings(self.db_path))

    def _scheduled_at(self, config: AppConfig, now: datetime) -> datetime:
        hour, minute = parse_run_time(config.schedule.run_time)
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def _next_scheduled_at(self, config: AppConfig, now: datetime) -> datetime | None:
        hour, minute = parse_run_time(config.schedule.run_time)
        for day_offset in range(8):
            candidate_day = now + timedelta(days=day_offset)
            candidate = candidate_day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now:
                continue
            if self._is_scheduled_day(config, candidate):
                return candidate
        return None

    def _is_scheduled_day(self, config: AppConfig, value: datetime) -> bool:
        day = RUN_DAY_VALUES[value.weekday()]
        return day in config.schedule.run_days

    def _already_handled(self, run_date: str) -> bool:
        with self._state_lock:
            return self._running or self._last_run_date == run_date

    def _run_report(self, *, run_date: str, started_at: datetime) -> bool:
        with self._state_lock:
            if self._running:
                return False
            self._running = True
            self._last_run_date = run_date
            self._last_started_at = format_scheduler_datetime(started_at)
            self._last_error = None

        try:
            run_report(db_path=self.db_path, output_dir=self.output_dir, trigger="schedule")
            return True
        except Exception as exc:
            message = f"{exc.__class__.__name__}: {exc}"
            self._set_state(last_error=message)
            LOGGER.exception("Scheduled report failed")
            return False
        finally:
            finished_at = datetime.now(started_at.tzinfo)
            self._set_state(running=False, last_finished_at=format_scheduler_datetime(finished_at))

    def _set_state(self, **values: Any) -> None:
        with self._state_lock:
            for key, value in values.items():
                setattr(self, f"_{key}", value)
