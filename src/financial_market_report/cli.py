from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="financial-market-report")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Generate the market report")
    run_parser.add_argument("--config", type=Path, default=None, help="Path to defaults YAML")
    run_parser.add_argument("--output-dir", type=Path, default=None, help="Directory for generated reports")
    run_parser.add_argument("--send-email", dest="send_email", action="store_true", default=None)
    run_parser.add_argument("--no-email", dest="send_email", action="store_false")
    run_parser.add_argument("--news", dest="get_news", action="store_true", default=None)
    run_parser.add_argument("--no-news", dest="get_news", action="store_false")
    run_parser.add_argument("--plots", dest="get_plots", action="store_true", default=None)
    run_parser.add_argument("--no-plots", dest="get_plots", action="store_false")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        from financial_market_report.runner import run_report

        result = run_report(
            config_path=args.config,
            output_dir=args.output_dir,
            send_email_override=args.send_email,
            get_news_override=args.get_news,
            get_plots_override=args.get_plots,
        )
        print(f"Report written: {result.report_path}")
        print(f"Tickers of interest: {result.ticker_count}")
        print(f"Email sent: {result.email_sent}")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
