"""
Unified CN market daily price provider.

A-share K-lines and index closes come from AkShare (Tencent backend).
Narrative Data Agents use Doubao web search when structured AkShare data is missing.
Failed K-line fetches skip the symbol (no Yahoo fallback).
"""
from __future__ import annotations

import os

from datetime import datetime

import pandas as pd

from utils.akshare_utils import akshare_cached

AKSHARE_COLUMNS = [
    "日期",
    "股票代码",
    "开盘",
    "收盘",
    "最高",
    "最低",
    "成交量",
    "成交额",
    "振幅",
    "涨跌幅",
    "涨跌额",
    "换手率",
]


def _to_compact(date_text: str) -> str:
    digits = "".join(ch for ch in str(date_text or "") if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else digits


def _normalize_akshare_frame(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=AKSHARE_COLUMNS)
    frame = df.copy()
    if "日期" in frame.columns:
        frame["日期"] = pd.to_datetime(frame["日期"], errors="coerce").dt.strftime("%Y-%m-%d")
    keep = [col for col in AKSHARE_COLUMNS if col in frame.columns]
    return frame[keep].dropna(subset=["日期"]).drop_duplicates("日期", keep="last").sort_values("日期")


def _fetch_akshare_hist(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str = "qfq",
    verbose: bool = False,
) -> pd.DataFrame:
    base_symbol = "".join(ch for ch in str(symbol) if ch.isdigit())[-6:].zfill(6)
    raw = akshare_cached.run(
        func_name="stock_zh_a_hist",
        func_kwargs={
            "symbol": base_symbol,
            "period": "daily",
            "start_date": start_date,
            "end_date": end_date,
            "adjust": adjust,
        },
        verbose=verbose,
    )
    return _normalize_akshare_frame(raw)


def _asof_end_date() -> str:
    """Return a forced 'as-of' date override for historical replays (YYYYMMDD)."""
    val = os.environ.get("CONTEST_TRADE_ASOF_DATE", "").strip().replace("-", "").replace("/", "")
    if len(val) == 8 and val.isdigit():
        return val
    return ""


def get_stock_zh_a_hist(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str = "qfq",
    verbose: bool = False,
) -> pd.DataFrame:
    start_date = _to_compact(start_date)
    end_date = _to_compact(end_date)
    asof = _asof_end_date()
    if asof and (not end_date or end_date > asof):
        # Force the K-line query to stop at the replay's trigger date so the
        # system never sees bars after the analysis point during historical backtest.
        end_date = asof
    if not start_date or not end_date:
        return pd.DataFrame(columns=AKSHARE_COLUMNS)
    return _fetch_akshare_hist(symbol, start_date, end_date, adjust=adjust, verbose=verbose)


def _index_frame_from_akshare(raw: pd.DataFrame, start_compact: str, end_compact: str) -> pd.DataFrame:
    date_col = next((col for col in ("date", "日期") if col in raw.columns), None)
    close_col = next((col for col in ("close", "收盘") if col in raw.columns), None)
    if not date_col or not close_col:
        return pd.DataFrame(columns=["date", "close"])
    prepared = pd.DataFrame(
        {
            "date": pd.to_datetime(raw[date_col], errors="coerce"),
            "close": pd.to_numeric(raw[close_col], errors="coerce"),
        }
    ).dropna(subset=["date", "close"]).sort_values("date")
    if start_compact:
        prepared = prepared[prepared["date"] >= datetime.strptime(start_compact, "%Y%m%d")]
    if end_compact:
        prepared = prepared[prepared["date"] <= datetime.strptime(end_compact, "%Y%m%d")]
    return prepared.reset_index(drop=True)


def get_index_daily(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    verbose: bool = False,
) -> pd.DataFrame:
    """Return index daily bars with columns date/close (lowercase)."""
    ak_symbol = str(symbol or "").strip().lower()
    if not ak_symbol.startswith(("sh", "sz")):
        ak_symbol = f"sh{''.join(ch for ch in ak_symbol if ch.isdigit())}"

    start_compact = _to_compact(start_date or "19700101")
    end_compact = _to_compact(end_date or datetime.now().strftime("%Y%m%d"))

    raw = akshare_cached.run(
        func_name="stock_zh_index_daily",
        func_kwargs={"symbol": ak_symbol},
        verbose=verbose,
    )
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "close"])
    return _index_frame_from_akshare(raw, start_compact, end_compact)
