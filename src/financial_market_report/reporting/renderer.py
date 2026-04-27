from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd


def dataframe_to_html(df: pd.DataFrame, *, escape_html: bool = True) -> str:
    if df is None or df.empty:
        return "<p>No rows.</p>"
    return df.to_html(index=False, escape=escape_html, classes="data-table")


def render_report_html(
    *,
    title: str,
    generated_at: str,
    interest_table: pd.DataFrame,
    events: pd.DataFrame | None = None,
    news: pd.DataFrame | None = None,
    chart_paths: dict[str, list[Path]] | None = None,
) -> str:
    chart_sections = []
    for ticker, paths in (chart_paths or {}).items():
        images = "\n".join(
            f'<img src="{escape(str(path.name))}" alt="{escape(ticker)} chart" loading="lazy">'
            for path in paths
        )
        chart_sections.append(f"<section><h3>{escape(ticker)}</h3><div class=\"charts\">{images}</div></section>")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; color: #1f2933; }}
    h1, h2, h3 {{ color: #102a43; }}
    .meta {{ color: #52606d; }}
    .data-table {{ border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; font-size: 0.9rem; }}
    .data-table th, .data-table td {{ border: 1px solid #d9e2ec; padding: 0.45rem 0.55rem; text-align: left; }}
    .data-table th {{ background: #f0f4f8; }}
    .charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1rem; }}
    img {{ width: 100%; height: auto; border: 1px solid #d9e2ec; }}
  </style>
</head>
<body>
  <h1>{escape(title)}</h1>
  <p class="meta">Generated at {escape(generated_at)}</p>

  <h2>Tickers Of Interest</h2>
  {dataframe_to_html(interest_table)}

  <h2>Upcoming Events</h2>
  {dataframe_to_html(events) if events is not None else "<p>Events disabled.</p>"}

  <h2>Recent News</h2>
  {dataframe_to_html(news, escape_html=False) if news is not None else "<p>News disabled.</p>"}

  <h2>Charts</h2>
  {"".join(chart_sections) if chart_sections else "<p>Charts disabled or unavailable.</p>"}
</body>
</html>
"""


def write_report_html(html: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
