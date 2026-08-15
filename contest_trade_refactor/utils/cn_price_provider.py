"""
Unified CN market daily price provider.

Priority:
1. JQData (when configured and auth succeeds)
2. AkShare (Tencent fallback for K-line; narrative agents use Doubao web search on failure)

For JQData formal accounts, recent history is included end-to-end.
Trial accounts may need AkShare to backfill the latest ~3 months.
"""
from __future__ import annotations

import os

from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

from config.config import cfg
from utils.akshare_utils import akshare_cached
from utils.jqdata_utils import (
    _map_adjust,
    clip_range_to_jqdata,
    compact_to_dash,
    dash_to_compact,
    get_jqdata_allowed_range,
    jqdata_cached,
    jqdata_configured,
    to_jq_security,
)

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


def _provider_mode() -> str:
    mode = str(getattr(cfg, "cn_market_data_provider", "auto") or "auto").lower()
    return mode


def _should_use_jqdata() -> bool:
    mode = _provider_mode()
    if mode == "akshare":
        return False
    if mode == "jqdata":
        return jqdata_configured()
    return jqdata_configured()


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


def _fetch_jqdata_hist(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str = "qfq",
    verbose: bool = False,
) -> pd.DataFrame:
    clipped_start, clipped_end = clip_range_to_jqdata(start_date, end_date)
    if not clipped_start or not clipped_end:
        return pd.DataFrame(columns=AKSHARE_COLUMNS)
    fq = _map_adjust(adjust)
    try:
        raw = jqdata_cached.run(
            func_name="get_price",
            func_kwargs={
                "security": symbol,
                "start_date": clipped_start,
                "end_date": clipped_end,
                "frequency": "daily",
                "fq": fq,
            },
            verbose=verbose,
        )
    except Exception as exc:
        logger.warning("JQData get_price failed for {} ({}-{}): {}", symbol, clipped_start, clipped_end, exc)
        return pd.DataFrame(columns=AKSHARE_COLUMNS)
    return _normalize_akshare_frame(raw)


def _prev_day_compact(date_text: str) -> str:
    dt = datetime.strptime(dash_to_compact(date_text), "%Y%m%d") - timedelta(days=1)
    return dt.strftime("%Y%m%d")


def _merge_hist_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    valid = [frame for frame in frames if frame is not None and not frame.empty]
    if not valid:
        return pd.DataFrame(columns=AKSHARE_COLUMNS)
    merged = pd.concat(valid, ignore_index=True)
    return merged.drop_duplicates("日期", keep="last").sort_values("日期").reset_index(drop=True)


def _next_day_compact(date_text: str) -> str:
    dt = datetime.strptime(dash_to_compact(date_text), "%Y%m%d") + timedelta(days=1)
    return dt.strftime("%Y%m%d")


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
    start_date = dash_to_compact(start_date)
    end_date = dash_to_compact(end_date)
    asof = _asof_end_date()
    if asof and (not end_date or end_date > asof):
        # Force the K-line query to stop at the replay's trigger date so the
        # system never sees bars after the analysis point during historical backtest.
        end_date = asof
    if not start_date or not end_date:
        return pd.DataFrame(columns=AKSHARE_COLUMNS)

    frames: list[pd.DataFrame] = []

    if _should_use_jqdata():
        allowed_start, allowed_end = get_jqdata_allowed_range()
        if allowed_start and start_date < allowed_start:
            head = _fetch_akshare_hist(symbol, start_date, _prev_day_compact(allowed_start), adjust=adjust, verbose=verbose)
            if not head.empty:
                frames.append(head)

        jq_frame = _fetch_jqdata_hist(symbol, start_date, end_date, adjust=adjust, verbose=verbose)
        if not jq_frame.empty:
            frames.append(jq_frame)

        if allowed_end and end_date > allowed_end:
            tail = _fetch_akshare_hist(symbol, _next_day_compact(allowed_end), end_date, adjust=adjust, verbose=verbose)
            if not tail.empty:
                frames.append(tail)

        merged = _merge_hist_frames(frames)
        if not merged.empty:
            return merged
        logger.warning("JQData+AkShare merge empty for {}, falling back to AkShare only", symbol)

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

    start_compact = dash_to_compact(start_date or "19700101")
    end_compact = dash_to_compact(end_date or datetime.now().strftime("%Y%m%d"))

    if _should_use_jqdata():
        frames: list[pd.DataFrame] = []
        allowed_start, allowed_end = get_jqdata_allowed_range()
        jq_symbol = to_jq_security(ak_symbol)

        if allowed_start and start_compact < allowed_start:
            head_raw = akshare_cached.run(
                func_name="stock_zh_index_daily",
                func_kwargs={"symbol": ak_symbol},
                verbose=verbose,
            )
            if head_raw is not None and not head_raw.empty:
                frames.append(_index_frame_from_akshare(head_raw, start_compact, _prev_day_compact(allowed_start)))

        clipped_start, clipped_end = clip_range_to_jqdata(start_compact, end_compact)
        if clipped_start and clipped_end:
            try:
                jq_frame = jqdata_cached.run(
                    func_name="get_price",
                    func_kwargs={
                        "security": jq_symbol,
                        "start_date": clipped_start,
                        "end_date": clipped_end,
                        "frequency": "daily",
                        "fq": None,
                    },
                    verbose=verbose,
                )
            except Exception as exc:
                logger.warning("JQData index get_price failed for {}: {}", jq_symbol, exc)
                jq_frame = pd.DataFrame()
            if jq_frame is not None and not jq_frame.empty:
                frames.append(
                    pd.DataFrame(
                        {
                            "date": pd.to_datetime(jq_frame["日期"], errors="coerce"),
                            "close": pd.to_numeric(jq_frame["收盘"], errors="coerce"),
                        }
                    ).dropna(subset=["date", "close"])
                )

        if allowed_end and end_compact > allowed_end:
            tail_raw = akshare_cached.run(
                func_name="stock_zh_index_daily",
                func_kwargs={"symbol": ak_symbol},
                verbose=verbose,
            )
            if tail_raw is not None and not tail_raw.empty:
                frames.append(_index_frame_from_akshare(tail_raw, _next_day_compact(allowed_end), end_compact))

        if frames:
            merged = pd.concat(frames, ignore_index=True).drop_duplicates("date", keep="last").sort_values("date")
            if not merged.empty:
                return merged.reset_index(drop=True)

    raw = akshare_cached.run(
        func_name="stock_zh_index_daily",
        func_kwargs={"symbol": ak_symbol},
        verbose=verbose,
    )
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "close"])

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
        start_dt = datetime.strptime(start_compact, "%Y%m%d")
        prepared = prepared[prepared["date"] >= start_dt]
    if end_compact:
        end_dt = datetime.strptime(end_compact, "%Y%m%d")
        prepared = prepared[prepared["date"] <= end_dt]
    return prepared.reset_index(drop=True)
