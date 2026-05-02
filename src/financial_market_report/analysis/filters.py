from __future__ import annotations

import pandas as pd

from financial_market_report.config import ReportSettings


REQUIRED_MOVER_COLUMNS = {"symbol", "price", "change"}


def _filter_movers(df: pd.DataFrame, *, settings: ReportSettings, source: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    missing = REQUIRED_MOVER_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Market mover data is missing columns: {sorted(missing)}")

    filtered = df[
        (df["price"] <= settings.price_of_interest)
        & (df["change"].abs() >= settings.price_change)
        & (df["price"] >= settings.lowest_price)
    ].copy()
    filtered["source"] = source
    return filtered.reset_index(drop=True)


def build_interest_table(
    gainers_df: pd.DataFrame,
    losers_df: pd.DataFrame,
    top_traded_df: pd.DataFrame,
    *,
    settings: ReportSettings,
) -> pd.DataFrame:
    frames = [
        _filter_movers(top_traded_df, settings=settings, source="toptraded"),
        _filter_movers(gainers_df, settings=settings, source="winners"),
        _filter_movers(losers_df, settings=settings, source="losers"),
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True).drop_duplicates(subset=["symbol"]).reset_index(drop=True)


def add_volume_filter(df_interest: pd.DataFrame, *, settings: ReportSettings) -> pd.DataFrame:
    from financial_market_report.market_data.yahoo import download_latest_volumes

    if df_interest.empty:
        return df_interest

    tickers = df_interest["symbol"].dropna().astype(str).tolist()
    volumes = download_latest_volumes(tickers)

    filtered = df_interest.copy()
    filtered["volume"] = filtered["symbol"].map(volumes)
    filtered = filtered[filtered["volume"] >= settings.daily_volume].reset_index(drop=True)

    if "changesPercentage" in filtered.columns:
        filtered["changesPercentage"] = filtered["changesPercentage"].round(2)

    return filtered.head(settings.max_tickers).reset_index(drop=True)
