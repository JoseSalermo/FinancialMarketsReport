from __future__ import annotations

import sqlite3
from pathlib import Path

from financial_market_report.config import PROJECT_ROOT


DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "financial_market_report.sqlite3"


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    params_json TEXT NOT NULL,
    error_message TEXT,
    ticker_count INTEGER NOT NULL DEFAULT 0,
    email_sent INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES report_runs(id) ON DELETE CASCADE,
    report_date TEXT NOT NULL,
    html_path TEXT NOT NULL,
    email_status TEXT NOT NULL DEFAULT 'not_requested',
    email_sent_at TEXT
);

CREATE TABLE IF NOT EXISTS ticker_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES report_runs(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    source TEXT,
    price REAL,
    change_value REAL,
    changes_percentage REAL,
    volume REAL,
    company_name TEXT,
    row_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES report_runs(id) ON DELETE CASCADE,
    symbol TEXT,
    title TEXT,
    source TEXT,
    published_at TEXT,
    url TEXT,
    row_json TEXT NOT NULL
);
"""


def resolve_db_path(path: str | Path | None = None) -> Path:
    return Path(path) if path else DEFAULT_DB_PATH


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = resolve_db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | Path | None = None) -> Path:
    db_path = resolve_db_path(path)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
    return db_path
