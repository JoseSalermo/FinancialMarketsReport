from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf


def get_stock_data(
    symbols: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
    interval: str = "1d",
) -> pd.DataFrame:
    start = start_date or (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    end = end_date or datetime.now().strftime("%Y-%m-%d")
    return yf.download(symbols, start=start, end=end, interval=interval)


def get_company_name(ticker: str) -> str:
    try:
        stock = yf.Ticker(ticker)
        return stock.info.get("longName", "N/A")
    except Exception:
        return "N/A"


def download_latest_volumes(symbols: list[str]) -> pd.Series:
    if not symbols:
        return pd.Series(dtype="float64")

    data = yf.download(symbols, period="1d", auto_adjust=True, progress=False)
    if data.empty:
        return pd.Series(dtype="float64")

    volumes = data["Volume"] if "Volume" in data else data
    if isinstance(volumes, pd.DataFrame):
        return volumes.iloc[-1]
    return pd.Series({symbols[0]: volumes.iloc[-1]})


def get_history_table(symbol: str) -> pd.DataFrame:
    tick = yf.Ticker(symbol)
    hist = tick.history(period="7mo", interval="1d", actions=False)
    if hist.empty:
        raise ValueError("No history returned. Try a different ticker or wider period.")

    last7 = hist.tail(7).copy()
    last7["label"] = "last_7d"

    anchor = hist.index.max()
    one_month_row = hist.loc[: anchor - pd.DateOffset(months=1)].tail(1).copy()
    one_month_row["label"] = "1M_ago"
    six_month_row = hist.loc[: anchor - pd.DateOffset(months=6)].tail(1).copy()
    six_month_row["label"] = "6M_ago"

    table = (
        pd.concat([last7, one_month_row, six_month_row], axis=0)
        .reset_index()
        .rename(columns={"Date": "datetime"})
        .sort_values("datetime", ascending=False)
        .reset_index(drop=True)
    )

    table["symbol"] = symbol
    table["DayVar"] = (table["Close"] - table["Open"]).round(3)
    return table
