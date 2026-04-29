from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="financial-market-report")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Generate the market report")
    run_parser.add_argument("--config", type=Path, default=None, help="Path to defaults YAML")
    run_parser.add_argument("--output-dir", type=Path, default=None, help="Directory for generated reports")
    run_parser.add_argument("--db-path", type=Path, default=None, help="Path to SQLite database")
    run_parser.add_argument("--send-email", dest="send_email", action="store_true", default=None)
    run_parser.add_argument("--no-email", dest="send_email", action="store_false")
    run_parser.add_argument("--news", dest="get_news", action="store_true", default=None)
    run_parser.add_argument("--no-news", dest="get_news", action="store_false")
    run_parser.add_argument("--plots", dest="get_plots", action="store_true", default=None)
    run_parser.add_argument("--no-plots", dest="get_plots", action="store_false")

    init_db_parser = subparsers.add_parser("init-db", help="Initialize the SQLite database")
    init_db_parser.add_argument("--db-path", type=Path, default=None, help="Path to SQLite database")

    runs_parser = subparsers.add_parser("runs", help="List recent report runs")
    runs_parser.add_argument("--db-path", type=Path, default=None, help="Path to SQLite database")
    runs_parser.add_argument("--limit", type=int, default=10, help="Number of runs to show")

    secrets_parser = subparsers.add_parser("secrets-status", help="Show configured secret availability")
    secrets_parser.add_argument(
        "--include-email",
        action="store_true",
        help="Include email delivery secrets in the status check",
    )

    serve_parser = subparsers.add_parser("serve", help="Start the internal web app")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    serve_parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    serve_parser.add_argument("--db-path", type=Path, default=None, help="Path to SQLite database")
    serve_parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    serve_parser.add_argument("--no-scheduler", action="store_true", help="Disable the background scheduler")
    serve_parser.add_argument(
        "--scheduler-interval-seconds",
        type=int,
        default=60,
        help="How often the background scheduler checks settings",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        from financial_market_report.runner import run_report

        result = run_report(
            config_path=args.config,
            output_dir=args.output_dir,
            db_path=args.db_path,
            send_email_override=args.send_email,
            get_news_override=args.get_news,
            get_plots_override=args.get_plots,
        )
        print(f"Run ID: {result.run_id}")
        print(f"Report written: {result.report_path}")
        print(f"Tickers of interest: {result.ticker_count}")
        print(f"Email sent: {result.email_sent}")
        return 0

    if args.command == "init-db":
        from financial_market_report.storage.db import init_db

        db_path = init_db(args.db_path)
        print(f"Database initialized: {db_path}")
        return 0

    if args.command == "runs":
        from financial_market_report.storage.repository import list_report_runs

        rows = list_report_runs(args.db_path, limit=args.limit)
        if not rows:
            print("No report runs recorded.")
            return 0

        for row in rows:
            status = row["status"]
            email_status = row["email_status"] or "not_recorded"
            html_path = row["html_path"] or ""
            print(
                f"#{row['id']} {status} "
                f"started={row['started_at']} "
                f"finished={row['finished_at'] or '-'} "
                f"tickers={row['ticker_count']} "
                f"email={email_status} "
                f"report={html_path}"
            )
            if row["error_message"]:
                print(f"  error={row['error_message']}")
        return 0

    if args.command == "secrets-status":
        from financial_market_report.secrets import clear_secret_cache, secret_status, vault_error
        from financial_market_report.vault import load_vault_config

        names = ["FMP_API_KEY", "NEWS_API_KEY"]
        if args.include_email:
            names.extend(["SENDER_EMAIL", "TARGET_EMAIL", "GMAIL_APP_PASSWORD"])

        clear_secret_cache()
        config = load_vault_config()
        print(f"Vault configured: {config is not None}")
        for name, configured in secret_status(names).items():
            print(f"{name}: {'configured' if configured else 'missing'}")
        if vault_error():
            print(f"Vault error: {vault_error()}")
        return 0

    if args.command == "serve":
        from financial_market_report.web.app import run_dev_server

        run_dev_server(
            host=args.host,
            port=args.port,
            db_path=args.db_path,
            debug=args.debug,
            enable_scheduler=not args.no_scheduler,
            scheduler_interval_seconds=args.scheduler_interval_seconds,
        )
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
