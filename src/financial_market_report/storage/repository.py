from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from financial_market_report.storage.db import connect, init_db


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_default(value: Any) -> str | int | float | bool | None:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def to_json(value: Any) -> str:
    if is_dataclass(value):
        value = asdict(value)
    return json.dumps(value, default=_json_default, sort_keys=True)


def create_report_run(db_path: str | Path | None, *, started_at: str, params: Any) -> int:
    init_db(db_path)
    with connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO report_runs (started_at, status, params_json)
            VALUES (?, 'running', ?)
            """,
            (started_at, to_json(params)),
        )
        return int(cursor.lastrowid)


def save_settings_snapshot(db_path: str | Path | None, *, settings: Any, updated_at: str) -> None:
    init_db(db_path)
    values = asdict(settings) if is_dataclass(settings) else settings
    if not isinstance(values, dict):
        raise TypeError("settings must be a dataclass or mapping")

    flattened: list[tuple[str, str, str]] = []

    def visit(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                child_prefix = f"{prefix}.{child_key}" if prefix else str(child_key)
                visit(child_prefix, child_value)
            return
        flattened.append((prefix, to_json(value), updated_at))

    visit("", values)

    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            flattened,
        )


def get_settings(db_path: str | Path | None) -> dict[str, str]:
    init_db(db_path)
    with connect(db_path) as conn:
        return {
            row["key"]: row["value"]
            for row in conn.execute("SELECT key, value FROM settings ORDER BY key")
        }


def update_settings(db_path: str | Path | None, values: dict[str, Any]) -> None:
    init_db(db_path)
    updated_at = utc_now_iso()
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            [(key, to_json(value), updated_at) for key, value in values.items()],
        )


def finish_report_run(
    db_path: str | Path | None,
    *,
    run_id: int,
    status: str,
    finished_at: str,
    ticker_count: int = 0,
    email_sent: bool = False,
    error_message: str | None = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE report_runs
            SET finished_at = ?,
                status = ?,
                error_message = ?,
                ticker_count = ?,
                email_sent = ?
            WHERE id = ?
            """,
            (finished_at, status, error_message, ticker_count, int(email_sent), run_id),
        )


def record_report(
    db_path: str | Path | None,
    *,
    run_id: int,
    report_date: str,
    html_path: str | Path,
    email_status: str,
    email_sent_at: str | None = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO reports (run_id, report_date, html_path, email_status, email_sent_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, report_date, str(html_path), email_status, email_sent_at),
        )


def replace_ticker_candidates(db_path: str | Path | None, *, run_id: int, rows: pd.DataFrame) -> None:
    with connect(db_path) as conn:
        conn.execute("DELETE FROM ticker_candidates WHERE run_id = ?", (run_id,))
        if rows is None or rows.empty:
            return

        payload = []
        for row in rows.to_dict(orient="records"):
            payload.append(
                (
                    run_id,
                    row.get("symbol"),
                    row.get("source"),
                    row.get("price"),
                    row.get("change"),
                    row.get("changesPercentage"),
                    row.get("volume"),
                    row.get("name") or row.get("companyName") or row.get("company_name"),
                    to_json(row),
                )
            )
        conn.executemany(
            """
            INSERT INTO ticker_candidates (
                run_id, symbol, source, price, change_value,
                changes_percentage, volume, company_name, row_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )


def replace_news_articles(db_path: str | Path | None, *, run_id: int, rows: pd.DataFrame | None) -> None:
    with connect(db_path) as conn:
        conn.execute("DELETE FROM news_articles WHERE run_id = ?", (run_id,))
        if rows is None or rows.empty:
            return

        payload = []
        for row in rows.to_dict(orient="records"):
            payload.append(
                (
                    run_id,
                    row.get("Ticker"),
                    row.get("Title"),
                    row.get("Source"),
                    str(row.get("Published Local") or row.get("Published At") or ""),
                    None,
                    to_json(row),
                )
            )
        conn.executemany(
            """
            INSERT INTO news_articles (run_id, symbol, title, source, published_at, url, row_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )


def list_report_runs(db_path: str | Path | None, *, limit: int = 10) -> list[sqlite3.Row]:
    init_db(db_path)
    with connect(db_path) as conn:
        return list(
            conn.execute(
                """
                SELECT rr.id,
                       rr.started_at,
                       rr.finished_at,
                       rr.status,
                       rr.ticker_count,
                       rr.email_sent,
                       rr.error_message,
                       r.html_path,
                       r.email_status
                FROM report_runs rr
                LEFT JOIN reports r ON r.run_id = rr.id
                ORDER BY rr.id DESC
                LIMIT ?
                """,
                (limit,),
            )
        )


def get_latest_report_run(db_path: str | Path | None) -> sqlite3.Row | None:
    rows = list_report_runs(db_path, limit=1)
    return rows[0] if rows else None


def get_running_report_run(db_path: str | Path | None) -> sqlite3.Row | None:
    init_db(db_path)
    with connect(db_path) as conn:
        return conn.execute(
            """
            SELECT id,
                   started_at,
                   status,
                   params_json
            FROM report_runs
            WHERE status = 'running'
            ORDER BY id DESC
            LIMIT 1
            """,
        ).fetchone()


def scheduled_run_exists(db_path: str | Path | None, *, run_date: str, trigger: str = "schedule") -> bool:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT params_json
            FROM report_runs
            WHERE started_at LIKE ?
            ORDER BY id DESC
            """,
            (f"{run_date}%",),
        )
        for row in rows:
            try:
                params = json.loads(row["params_json"])
            except json.JSONDecodeError:
                continue
            runtime = params.get("runtime", {})
            if isinstance(runtime, dict) and runtime.get("trigger") == trigger:
                return True
    return False


def get_report_run(db_path: str | Path | None, run_id: int) -> sqlite3.Row | None:
    init_db(db_path)
    with connect(db_path) as conn:
        return conn.execute(
            """
            SELECT rr.id,
                   rr.started_at,
                   rr.finished_at,
                   rr.status,
                   rr.params_json,
                   rr.error_message,
                   rr.ticker_count,
                   rr.email_sent,
                   r.html_path,
                   r.email_status,
                   r.email_sent_at,
                   r.report_date
            FROM report_runs rr
            LEFT JOIN reports r ON r.run_id = rr.id
            WHERE rr.id = ?
            """,
            (run_id,),
        ).fetchone()


def list_ticker_candidates(db_path: str | Path | None, *, run_id: int) -> list[sqlite3.Row]:
    init_db(db_path)
    with connect(db_path) as conn:
        return list(
            conn.execute(
                """
                SELECT symbol,
                       source,
                       price,
                       change_value,
                       changes_percentage,
                       volume,
                       company_name
                FROM ticker_candidates
                WHERE run_id = ?
                ORDER BY source, symbol
                """,
                (run_id,),
            )
        )


def list_reports(db_path: str | Path | None, *, limit: int = 25) -> list[sqlite3.Row]:
    init_db(db_path)
    with connect(db_path) as conn:
        return list(
            conn.execute(
                """
                SELECT r.id,
                       r.run_id,
                       r.report_date,
                       r.html_path,
                       r.email_status,
                       rr.status,
                       rr.started_at,
                       rr.ticker_count
                FROM reports r
                JOIN report_runs rr ON rr.id = r.run_id
                ORDER BY r.id DESC
                LIMIT ?
                """,
                (limit,),
            )
        )
