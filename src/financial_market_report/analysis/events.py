from __future__ import annotations

import contextlib
import io
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf


def _to_dt_local_from_date(d: date, tz: str, at_time: time | None = None):
    if pd.isna(d):
        return pd.NaT
    if isinstance(d, (pd.Timestamp, datetime)):
        ts = pd.to_datetime(d, errors="coerce")
        if ts is pd.NaT:
            return pd.NaT
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert(tz)

    t = at_time or time(0, 0)
    dt_local = datetime(d.year, d.month, d.day, t.hour, t.minute, t.second, tzinfo=ZoneInfo(tz))
    return pd.Timestamp(dt_local)


def _is_date_like(value):
    if value is None or pd.isna(value):
        return False
    try:
        if isinstance(value, (datetime, pd.Timestamp, date)):
            return True
        pd.to_datetime(value)
        return True
    except Exception:
        return False


def _extract_calendar_events_from_dict(cal: dict, symbol: str, tz: str):
    events = []

    earn_hi = cal.get("Earnings High")
    earn_lo = cal.get("Earnings Low")
    earn_avg = cal.get("Earnings Average")
    rev_hi = cal.get("Revenue High")
    rev_lo = cal.get("Revenue Low")
    rev_avg = cal.get("Revenue Average")

    earnings_date = cal.get("Earnings Date")
    dates = earnings_date if isinstance(earnings_date, (list, tuple)) else [earnings_date]
    for candidate in dates:
        if _is_date_like(candidate):
            events.append(
                {
                    "symbol": symbol,
                    "event": "Earnings",
                    "date_local": _to_dt_local_from_date(pd.to_datetime(candidate).date(), tz, at_time=time(16, 0)),
                    "details": {
                        "Earnings High": earn_hi,
                        "Earnings Low": earn_lo,
                        "Earnings Average": earn_avg,
                        "Revenue High": rev_hi,
                        "Revenue Low": rev_lo,
                        "Revenue Average": rev_avg,
                    },
                }
            )

    for key, event_name in [
        ("Ex-Dividend Date", "Ex-Dividend"),
        ("Dividend Date", "Dividend"),
        ("Record Date", "Dividend Record"),
        ("Payment Date", "Dividend Payment"),
        ("Declaration Date", "Dividend Declaration"),
    ]:
        candidate = cal.get(key)
        if _is_date_like(candidate):
            events.append(
                {
                    "symbol": symbol,
                    "event": event_name,
                    "date_local": _to_dt_local_from_date(pd.to_datetime(candidate).date(), tz),
                    "details": {},
                }
            )

    return events


def _extract_calendar_events_from_df(cal_df: pd.DataFrame, symbol: str, tz: str):
    events = []
    try:
        items = list(cal_df.copy().stack(dropna=False).items())
        for (_, key), value in items:
            if not _is_date_like(value):
                continue
            name = str(key)
            event = (
                "Earnings"
                if "Earnings Date" in name
                else "Ex-Dividend"
                if "Ex-Dividend" in name
                else "Dividend"
                if name == "Dividend Date"
                else name
            )
            at_time = time(16, 0) if event == "Earnings" else None
            events.append(
                {
                    "symbol": symbol,
                    "event": event,
                    "date_local": _to_dt_local_from_date(pd.to_datetime(value).date(), tz, at_time=at_time),
                    "details": {},
                }
            )
    except Exception:
        pass
    return events


def collect_events_for_ticker(ticker: str, tz: str = "America/Toronto") -> pd.DataFrame:
    ticker_client = yf.Ticker(ticker)
    rows = []

    try:
        calendar = ticker_client.calendar
        if isinstance(calendar, dict):
            rows += _extract_calendar_events_from_dict(calendar, ticker, tz)
        elif calendar is not None and hasattr(calendar, "empty") and not calendar.empty:
            rows += _extract_calendar_events_from_df(calendar, ticker, tz)
    except Exception:
        pass

    try:
        earnings_dates = ticker_client.get_earnings_dates(limit=16)
        if earnings_dates is not None and not earnings_dates.empty:
            for dt in pd.to_datetime(earnings_dates.index, errors="coerce"):
                if not pd.isna(dt):
                    rows.append(
                        {
                            "symbol": ticker,
                            "event": "Earnings",
                            "date_local": _to_dt_local_from_date(dt.date(), tz, at_time=time(16, 0)),
                            "details": {},
                        }
                    )
    except Exception:
        pass

    if not rows:
        return pd.DataFrame(columns=["symbol", "event", "date_local"])

    df = pd.DataFrame(rows)
    return (
        df.assign(day=df["date_local"].dt.normalize())
        .drop_duplicates(subset=["symbol", "event", "day"])
        .drop(columns=["day"])
        .sort_values(["symbol", "date_local"])
        .reset_index(drop=True)
    )


def events_within_window(
    tickers,
    *,
    window_days: int = 10,
    tz: str = "America/Toronto",
    upcoming_only: bool = True,
    normalize_symbols: bool = True,
) -> pd.DataFrame:
    syms_in = [tickers] if isinstance(tickers, str) else list(tickers)

    seen, symbols = set(), []
    for symbol in syms_in:
        normalized = str(symbol).strip()
        if normalize_symbols:
            normalized = normalized.upper().replace(".", "-")
        if normalized and normalized not in seen:
            symbols.append(normalized)
            seen.add(normalized)

    now = pd.Timestamp.now(tz).normalize()
    parts = []

    for symbol in symbols:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            df = collect_events_for_ticker(symbol, tz=tz)

        if df is None or df.empty:
            continue

        if "details" not in df.columns:
            df["details"] = [{} for _ in range(len(df))]

        df = df.assign(days_from_today=(df["date_local"].dt.normalize() - now).dt.days)
        mask = (
            df["days_from_today"].between(0, window_days)
            if upcoming_only
            else df["days_from_today"].abs() <= window_days
        )
        picked = df.loc[mask, ["symbol", "event", "date_local", "days_from_today", "details"]]
        if not picked.empty:
            parts.append(picked)

    if not parts:
        return pd.DataFrame(columns=["symbol", "event", "date_local", "days_from_today", "details"])

    return (
        pd.concat(parts, ignore_index=True)
        .assign(_day=lambda df: df["date_local"].dt.normalize())
        .drop_duplicates(subset=["symbol", "event", "_day"])
        .drop(columns="_day")
        .sort_values(["days_from_today", "symbol"])
        .reset_index(drop=True)
    )
