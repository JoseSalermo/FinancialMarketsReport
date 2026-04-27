from __future__ import annotations

import pandas as pd
import requests


FMP_BASE_URL = "https://financialmodelingprep.com/stable"


def _get_json(url: str, *, timeout: int = 30) -> list[dict]:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


def fetch_market_movers(api_key: str, *, timeout: int = 30) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    endpoints = {
        "gainers": f"{FMP_BASE_URL}/biggest-gainers?apikey={api_key}",
        "losers": f"{FMP_BASE_URL}/biggest-losers?apikey={api_key}",
        "top_traded": f"{FMP_BASE_URL}/most-actives?apikey={api_key}",
    }

    gainers_df = pd.DataFrame(_get_json(endpoints["gainers"], timeout=timeout))
    losers_df = pd.DataFrame(_get_json(endpoints["losers"], timeout=timeout))
    top_traded_df = pd.DataFrame(_get_json(endpoints["top_traded"], timeout=timeout))

    if not gainers_df.empty and "change" in gainers_df:
        gainers_df = gainers_df.sort_values(by=["change"], ascending=False).reset_index(drop=True)
    if not losers_df.empty and "change" in losers_df:
        losers_df = losers_df.sort_values(by=["change"], ascending=True).reset_index(drop=True)
    if not top_traded_df.empty and "change" in top_traded_df:
        top_traded_df = top_traded_df.sort_values(by=["change"], ascending=False).reset_index(drop=True)

    return gainers_df, losers_df, top_traded_df
