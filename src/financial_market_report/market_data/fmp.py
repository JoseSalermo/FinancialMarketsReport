from __future__ import annotations

import pandas as pd
import requests


FMP_BASE_URL = "https://financialmodelingprep.com/stable"


def _get_json(endpoint: str, *, api_key: str, timeout: int = 30) -> list[dict]:
    url = f"{FMP_BASE_URL}/{endpoint}"
    try:
        response = requests.get(url, params={"apikey": api_key}, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"FMP API request failed for {endpoint}: {exc.__class__.__name__}") from None
    except ValueError:
        raise RuntimeError(f"FMP API returned invalid JSON for {endpoint}") from None

    return data if isinstance(data, list) else []


def fetch_market_movers(api_key: str, *, timeout: int = 30) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    gainers_df = pd.DataFrame(_get_json("biggest-gainers", api_key=api_key, timeout=timeout))
    losers_df = pd.DataFrame(_get_json("biggest-losers", api_key=api_key, timeout=timeout))
    top_traded_df = pd.DataFrame(_get_json("most-actives", api_key=api_key, timeout=timeout))

    if not gainers_df.empty and "change" in gainers_df:
        gainers_df = gainers_df.sort_values(by=["change"], ascending=False).reset_index(drop=True)
    if not losers_df.empty and "change" in losers_df:
        losers_df = losers_df.sort_values(by=["change"], ascending=True).reset_index(drop=True)
    if not top_traded_df.empty and "change" in top_traded_df:
        top_traded_df = top_traded_df.sort_values(by=["change"], ascending=False).reset_index(drop=True)

    return gainers_df, losers_df, top_traded_df
