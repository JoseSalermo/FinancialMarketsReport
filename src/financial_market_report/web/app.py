from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from flask import Flask, abort, flash, redirect, render_template, request, send_file, url_for

from financial_market_report.config import DEFAULT_CONFIG_PATH, PROJECT_ROOT, load_config
from financial_market_report.runner import run_report
from financial_market_report.secrets import clear_secret_cache, secret_status, vault_error
from financial_market_report.storage.db import DEFAULT_DB_PATH, init_db
from financial_market_report.storage.repository import (
    get_latest_report_run,
    get_report_run,
    get_settings,
    list_report_runs,
    list_reports,
    list_ticker_candidates,
    update_settings,
)
from financial_market_report.vault import load_vault_config


SETTING_FIELDS = [
    ("report.max_tickers", "Max Tickers", "number"),
    ("report.price_of_interest", "Max Price", "number"),
    ("report.lowest_price", "Min Price", "number"),
    ("report.daily_volume", "Daily Volume", "number"),
    ("report.price_change", "Min Price Change", "number"),
    ("report.dates_days_interest", "Event Window Days", "number"),
    ("report.news_days_interest", "News Window Days", "number"),
    ("report.news_page_size", "News Page Size", "number"),
    ("report.num_news", "News Per Ticker", "number"),
    ("report.timezone", "Timezone", "text"),
    ("report.get_news", "Get News", "checkbox"),
    ("report.get_plots", "Get Plots", "checkbox"),
    ("report.send_email", "Send Email", "checkbox"),
    ("schedule.enabled", "Schedule Enabled", "checkbox"),
    ("schedule.run_time", "Run Time", "text"),
]


def _decode_setting(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _field_value(settings: dict[str, str], key: str, fallback: Any) -> Any:
    return _decode_setting(settings.get(key)) if key in settings else fallback


def _default_settings_map() -> dict[str, Any]:
    config = load_config(DEFAULT_CONFIG_PATH)
    return {
        "report.max_tickers": config.report.max_tickers,
        "report.price_of_interest": config.report.price_of_interest,
        "report.lowest_price": config.report.lowest_price,
        "report.daily_volume": config.report.daily_volume,
        "report.price_change": config.report.price_change,
        "report.dates_days_interest": config.report.dates_days_interest,
        "report.news_days_interest": config.report.news_days_interest,
        "report.news_page_size": config.report.news_page_size,
        "report.num_news": config.report.num_news,
        "report.timezone": config.report.timezone,
        "report.get_news": config.report.get_news,
        "report.get_plots": config.report.get_plots,
        "report.send_email": config.report.send_email,
        "schedule.enabled": config.schedule.enabled,
        "schedule.run_time": config.schedule.run_time,
    }


def create_app(*, db_path: str | Path | None = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = "local-dev-change-me"
    app.config["DB_PATH"] = str(db_path or DEFAULT_DB_PATH)
    init_db(app.config["DB_PATH"])

    @app.get("/")
    def dashboard():
        latest_run = get_latest_report_run(app.config["DB_PATH"])
        reports = list_reports(app.config["DB_PATH"], limit=5)
        return render_template("dashboard.html", latest_run=latest_run, reports=reports)

    @app.get("/runs")
    def runs():
        rows = list_report_runs(app.config["DB_PATH"], limit=50)
        return render_template("runs.html", runs=rows)

    @app.get("/runs/<int:run_id>")
    def run_detail(run_id: int):
        run = get_report_run(app.config["DB_PATH"], run_id)
        if run is None:
            abort(404)
        tickers = list_ticker_candidates(app.config["DB_PATH"], run_id=run_id)
        return render_template("run_detail.html", run=run, tickers=tickers)

    @app.post("/runs")
    def run_now():
        def target() -> None:
            run_report(db_path=app.config["DB_PATH"])

        threading.Thread(target=target, daemon=True).start()
        flash("Report run started. Refresh run history to see progress.")
        return redirect(url_for("runs"))

    @app.get("/reports")
    def reports():
        rows = list_reports(app.config["DB_PATH"], limit=50)
        return render_template("reports.html", reports=rows)

    @app.get("/reports/<int:run_id>/open")
    def open_report(run_id: int):
        run = get_report_run(app.config["DB_PATH"], run_id)
        if run is None or not run["html_path"]:
            abort(404)
        path = Path(run["html_path"])
        if not path.exists():
            abort(404)
        return send_file(path)

    @app.get("/settings")
    def settings():
        stored = get_settings(app.config["DB_PATH"])
        defaults = _default_settings_map()
        fields = [
            {
                "key": key,
                "label": label,
                "type": field_type,
                "value": _field_value(stored, key, defaults.get(key)),
            }
            for key, label, field_type in SETTING_FIELDS
        ]
        return render_template("settings.html", fields=fields)

    @app.post("/settings")
    def update_settings_view():
        defaults = _default_settings_map()
        values: dict[str, Any] = {}
        for key, _label, field_type in SETTING_FIELDS:
            if field_type == "checkbox":
                values[key] = key in request.form
            elif key in request.form:
                raw = request.form[key].strip()
                default = defaults.get(key)
                if isinstance(default, int):
                    values[key] = int(raw)
                elif isinstance(default, float):
                    values[key] = float(raw)
                else:
                    values[key] = raw
        update_settings(app.config["DB_PATH"], values)
        flash("Settings saved to SQLite. Runner config-file overrides are not wired yet.")
        return redirect(url_for("settings"))

    @app.get("/secrets")
    def secrets():
        clear_secret_cache()
        names = ["FMP_API_KEY", "NEWS_API_KEY", "SENDER_EMAIL", "TARGET_EMAIL", "GMAIL_APP_PASSWORD"]
        return render_template(
            "secrets.html",
            vault_configured=load_vault_config() is not None,
            statuses=secret_status(names),
            vault_error=vault_error(),
        )

    return app


def run_dev_server(*, host: str, port: int, db_path: str | Path | None = None, debug: bool = False) -> None:
    app = create_app(db_path=db_path)
    app.run(host=host, port=port, debug=debug)
