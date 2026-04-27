from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from financial_market_report.analysis.filters import add_volume_filter, build_interest_table
from financial_market_report.config import PROJECT_ROOT, AppConfig, load_config
from financial_market_report.emailer.smtp import send_html_email_with_attachment
from financial_market_report.market_data.fmp import fetch_market_movers
from financial_market_report.reporting.renderer import render_report_html, write_report_html
from financial_market_report.secrets import read_secret


@dataclass(frozen=True)
class ReportRunResult:
    report_path: Path
    ticker_count: int
    email_sent: bool


def _reports_root(output_dir: str | Path | None = None) -> Path:
    return Path(output_dir) if output_dir else PROJECT_ROOT / "reports"


def _summary_email_html(*, report_date: str, generated_at: str, ticker_count: int) -> str:
    return f"""
<html>
  <body>
    <h2>Market Analysis - {report_date}</h2>
    <p>Generated at: {generated_at}</p>
    <p>Tickers of interest: {ticker_count}</p>
    <p>Full report attached.</p>
  </body>
</html>
"""


def run_report(
    *,
    config_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    send_email_override: bool | None = None,
    get_news_override: bool | None = None,
    get_plots_override: bool | None = None,
) -> ReportRunResult:
    config: AppConfig = load_config(config_path)
    settings = config.report

    get_news = settings.get_news if get_news_override is None else get_news_override
    get_plots = settings.get_plots if get_plots_override is None else get_plots_override
    send_email = settings.send_email if send_email_override is None else send_email_override

    timezone = settings.timezone
    now = datetime.now(ZoneInfo(timezone))
    report_date = now.date().isoformat()
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S %Z%z")

    report_dir = _reports_root(output_dir) / report_date
    report_dir.mkdir(parents=True, exist_ok=True)

    fmp_api_key = read_secret("FMP_API_KEY")
    gainers_df, losers_df, top_traded_df = fetch_market_movers(api_key=fmp_api_key)
    interest_table = build_interest_table(gainers_df, losers_df, top_traded_df, settings=settings)
    interest_table = add_volume_filter(interest_table, settings=settings)

    symbols = []
    if not interest_table.empty and "symbol" in interest_table.columns:
        symbols = sorted({str(symbol).strip().upper() for symbol in interest_table["symbol"].dropna()})

    events_df: pd.DataFrame | None = None
    news_df: pd.DataFrame | None = None
    if get_news and symbols:
        from financial_market_report.analysis.events import events_within_window
        from financial_market_report.market_data.news import collect_recent_news

        events_df = events_within_window(
            symbols,
            window_days=settings.dates_days_interest,
            tz=timezone,
            upcoming_only=True,
        )

        news_api_key = read_secret("NEWS_API_KEY", required=False)
        if news_api_key:
            news_df = collect_recent_news(
                symbols,
                api_key=news_api_key,
                page_size=settings.news_page_size,
                days_interest=settings.news_days_interest,
                num_news=settings.num_news,
                timezone=timezone,
            )

    chart_paths: dict[str, list[Path]] = {}
    if get_plots and symbols:
        from financial_market_report.reporting.charts import save_standard_chart_set

        for symbol in symbols:
            paths = save_standard_chart_set(symbol, report_dir, timezone=timezone)
            if paths:
                chart_paths[symbol] = paths

    html = render_report_html(
        title=f"Market Analysis - {report_date}",
        generated_at=generated_at,
        interest_table=interest_table,
        events=events_df,
        news=news_df,
        chart_paths=chart_paths,
    )
    report_path = write_report_html(html, report_dir / f"Market_{report_date}.html")

    email_sent = False
    if send_email:
        sender_email = read_secret("SENDER_EMAIL")
        target_email = read_secret("TARGET_EMAIL")
        gmail_app_password = read_secret("GMAIL_APP_PASSWORD")
        send_html_email_with_attachment(
            sender_email=sender_email,
            receiver_email=target_email,
            subject=f"Market Analysis - {report_date}",
            html_path=report_path,
            app_password=gmail_app_password,
            summary_html=_summary_email_html(
                report_date=report_date,
                generated_at=generated_at,
                ticker_count=len(interest_table),
            ),
            smtp_host=config.email.smtp_host,
            smtp_port=config.email.smtp_port,
        )
        email_sent = True

    return ReportRunResult(
        report_path=report_path,
        ticker_count=len(interest_table),
        email_sent=email_sent,
    )
