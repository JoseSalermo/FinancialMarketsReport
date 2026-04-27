from __future__ import annotations

import pandas as pd
import requests

from financial_market_report.market_data.yahoo import get_company_name


NEWS_API_URL = "https://newsapi.org/v2/everything"


def search_news_to_df(ticker: str, api_key: str, page_size: int, *, timeout: int = 30) -> pd.DataFrame:
    params = {
        "q": ticker,
        "apiKey": api_key,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": page_size,
    }
    response = requests.get(NEWS_API_URL, params=params, timeout=timeout)
    if response.status_code != 200:
        return pd.DataFrame()

    articles = (response.json() or {}).get("articles", [])
    if not articles:
        return pd.DataFrame()

    company_name = get_company_name(ticker)
    rows = []
    for article in articles:
        title = article.get("title") or "N/A"
        url = article.get("url")
        title_link = (
            f'<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'
            if url
            else title
        )
        rows.append(
            [
                ticker,
                company_name,
                title_link,
                article.get("author") or "N/A",
                (article.get("source") or {}).get("name") or "N/A",
                article.get("publishedAt") or "N/A",
            ]
        )

    return (
        pd.DataFrame(rows, columns=["Ticker", "Company Name", "Title", "Author", "Source", "Published At"])
        .sort_values("Published At", ascending=False)
        .reset_index(drop=True)
    )


def collect_recent_news(
    symbols: list[str],
    *,
    api_key: str,
    page_size: int,
    days_interest: int,
    num_news: int,
    timezone: str,
) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame(columns=["Ticker", "Company Name", "Title", "Author", "Source", "Published Local"])

    news = pd.concat(
        [search_news_to_df(symbol, api_key, page_size) for symbol in sorted(set(symbols))],
        ignore_index=True,
    )
    if news.empty:
        return news

    news = news.drop_duplicates(subset=["Title"])
    news["Published At"] = pd.to_datetime(news["Published At"], utc=True, errors="coerce")
    news = news.dropna(subset=["Published At"])
    news["Published Local"] = news["Published At"].dt.tz_convert(timezone)

    cutoff = pd.Timestamp.now(timezone) - pd.Timedelta(days=days_interest)
    recent = news.loc[news["Published Local"] >= cutoff]

    return (
        recent.sort_values(["Ticker", "Published Local"], ascending=[True, False])
        .groupby("Ticker", as_index=False, group_keys=False)
        .head(num_news)
        .reset_index(drop=True)
    )
