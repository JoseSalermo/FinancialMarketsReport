from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import mplfinance as mpf
import pandas as pd
import yfinance as yf


DEFAULT_TITLE_PAD = 18
DEFAULT_TITLE_Y = 0.995
DEFAULT_TOP_MARGIN = 0.88


def _granularity_ok(idx: pd.DatetimeIndex, requested_interval: str, tolerance: float = 1.5) -> bool:
    if len(idx) < 3:
        return True
    to_min = {"1m": 1, "2m": 2, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "90m": 90, "1h": 60, "1d": 1440}
    req_min = to_min.get(requested_interval)
    if req_min is None:
        return True
    s1 = pd.Series(idx[1:], index=range(len(idx) - 1))
    s0 = pd.Series(idx[:-1], index=range(len(idx) - 1))
    med_minutes = (s1 - s0).dt.total_seconds().median() / 60.0
    return med_minutes <= req_min * tolerance


def _format_volume_axis(ax) -> None:
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _p: f"{x / 1_000_000:.1f}M"))


def plot_candles(
    ticker: str,
    *,
    interval: str = "5m",
    period: Optional[str] = "7d",
    start: Optional[str | pd.Timestamp] = None,
    end: Optional[str | pd.Timestamp] = None,
    prepost: bool = False,
    include_volume: bool = True,
    style: str | Any = "yahoo",
    figsize: tuple[int, int] = (12, 6),
    mav: Iterable[int] | None = (10, 20, 50),
    vwap: bool = True,
    strip_regular_only: bool = False,
    tz: str = "America/Toronto",
    earnings_markers: bool = True,
    show_legend: bool = True,
    savepath: Optional[str | Path] = None,
    title_pad: int = DEFAULT_TITLE_PAD,
    title_y: float = DEFAULT_TITLE_Y,
    top_margin: float = DEFAULT_TOP_MARGIN,
):
    if period and (start or end):
        raise ValueError("Use either period or start/end, not both.")

    yf_ticker = yf.Ticker(ticker)
    hist_kwargs = {"interval": interval, "actions": False, "prepost": prepost}
    if period:
        hist_kwargs["period"] = period
    else:
        hist_kwargs["start"] = start
        hist_kwargs["end"] = end

    df = yf_ticker.history(**hist_kwargs)
    if df.empty:
        raise ValueError(f"No data returned for {ticker} ({interval}, {period or f'{start} to {end}'}).")

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    try:
        df.index = df.index.tz_convert(tz)
    except Exception:
        df.index = df.index.tz_localize(tz)

    if strip_regular_only:
        df = df.between_time("09:30", "16:00")
        if df.empty:
            raise ValueError("No bars remain after filtering to 09:30-16:00.")

    if not _granularity_ok(df.index, interval):
        raise ValueError(f"Requested interval '{interval}' likely not honored.")

    if isinstance(style, str):
        mc = mpf.make_marketcolors(up="#16a34a", down="#dc2626", wick="inherit", edge="inherit", volume="in")
        style = mpf.make_mpf_style(base_mpf_style=style, marketcolors=mc, gridstyle=":", gridcolor="#999999")

    addplots = []
    if mav:
        for n in map(int, mav):
            ma = df["Close"].rolling(window=n, min_periods=max(1, n // 2)).mean()
            addplots.append(mpf.make_addplot(ma, panel=0, width=1, linestyle="-", alpha=0.9, label=f"MA{n}"))

    if vwap:
        day_groups = pd.Series(df.index.date, index=df.index)
        typical = (df["High"] + df["Low"] + df["Close"]) / 3.0
        cum_pv = (typical * df["Volume"]).groupby(day_groups).cumsum()
        cum_v = df["Volume"].groupby(day_groups).cumsum()
        addplots.append(mpf.make_addplot((cum_pv / cum_v).rename("VWAP"), panel=0, width=1, alpha=0.9, label="VWAP"))

    vlines = []
    if earnings_markers:
        try:
            earnings_dates = yf_ticker.get_earnings_dates(limit=6)
            if earnings_dates is not None and not earnings_dates.empty:
                ed_idx = pd.to_datetime(earnings_dates.index).tz_localize("UTC").tz_convert(tz).normalize()
                vlines = [ts for ts in ed_idx.unique() if df.index.min().normalize() <= ts <= df.index.max().normalize()]
        except Exception:
            vlines = []

    range_txt = period or f"{pd.to_datetime(start).date()} to {pd.to_datetime(end).date()}"
    base_kwargs = {
        "type": "candle",
        "style": style,
        "title": f"{ticker} - {interval} candles ({range_txt})",
        "ylabel": "Price ($)",
        "ylabel_lower": "Vol (M)" if include_volume else None,
        "volume": include_volume,
        "figsize": figsize,
        "returnfig": True,
        "tight_layout": True,
        "xrotation": 0,
    }
    if savepath:
        base_kwargs["savefig"] = {"fname": str(savepath), "dpi": 160, "pad_inches": 0.1}

    extra_kwargs: dict[str, Any] = {}
    if addplots:
        extra_kwargs["addplot"] = addplots
    if vlines:
        extra_kwargs["vlines"] = {"vlines": vlines, "linewidths": 0.8, "alpha": 0.7}

    fig, axes = mpf.plot(df, **base_kwargs, **extra_kwargs)

    suptitle = getattr(fig, "_suptitle", None)
    if suptitle is not None:
        suptitle.set_y(float(title_y))
        fig.subplots_adjust(top=float(top_margin))
    else:
        main_ax = axes[0] if isinstance(axes, (list, tuple)) else axes
        main_ax.set_title(main_ax.get_title(), pad=int(title_pad))

    if include_volume:
        vol_ax = axes[2] if isinstance(axes, (list, tuple)) and len(axes) >= 3 else None
        if vol_ax:
            _format_volume_axis(vol_ax)

    main_ax = axes[0] if isinstance(axes, (list, tuple)) else axes
    last_px = float(df["Close"].iloc[-1])
    main_ax.annotate(
        f"{last_px:.2f}",
        xy=(df.index[-1], last_px),
        xytext=(10, 0),
        textcoords="offset points",
        va="center",
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.2", "fc": "white", "alpha": 0.6},
    )

    if show_legend:
        handles, labels = main_ax.get_legend_handles_labels()
        filtered = [(h, label) for h, label in zip(handles, labels) if label and not label.startswith("_")]
        if filtered:
            h, labels = zip(*filtered)
            main_ax.legend(h, labels, loc="upper left", fontsize=8, frameon=True)

    return fig, axes


def save_standard_chart_set(ticker: str, output_dir: Path, *, timezone: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_specs = [("5m", "1d"), ("1h", "7d"), ("1h", "1mo")]
    saved_paths = []

    for interval, period in chart_specs:
        path = output_dir / f"{ticker}_{interval}_{period}.png"
        fig = None
        try:
            fig, _axes = plot_candles(
                ticker=ticker,
                interval=interval,
                period=period,
                prepost=True,
                strip_regular_only=True,
                tz=timezone,
                savepath=path,
            )
            saved_paths.append(path)
        except ValueError:
            continue
        finally:
            if fig is not None:
                plt.close(fig)

    return saved_paths
