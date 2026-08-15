"""
JQData (聚宽) SDK wrapper with disk cache and AkShare-compatible output.
"""
from __future__ import annotations

import hashlib
import json
import pickle
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from config.config import cfg

DEFAULT_JQDATA_CACHE_DIR = Path(__file__).parent / "jqdata_cache"

_AUTH_LOCK = threading.Lock()
_AUTH_OK = False


def _env(name: str) -> str:
    return (getattr(cfg, name, None) or "").strip()


def jqdata_configured() -> bool:
    return bool(_env("jqdata_username") and _env("jqdata_password"))


def ensure_jqdata_auth(force: bool = False) -> bool:
    global _AUTH_OK
    if _AUTH_OK and not force:
        return True
    if not jqdata_configured():
        return False
    with _AUTH_LOCK:
        if _AUTH_OK and not force:
            return True
        try:
            from jqdatasdk import auth

            auth(_env("jqdata_username"), _env("jqdata_password"))
            _AUTH_OK = True
            logger.info("JQData auth success")
            return True
        except Exception as exc:
            logger.warning("JQData auth failed: {}", exc)
            _AUTH_OK = False
            return False


def get_jqdata_account_info() -> dict[str, Any] | None:
    if not ensure_jqdata_auth():
        return None
    try:
        from jqdatasdk import get_account_info

        info = get_account_info()
        if isinstance(info, pd.DataFrame) and not info.empty:
            return info.iloc[0].to_dict()
        if isinstance(info, dict):
            return info
    except Exception as exc:
        logger.warning("JQData get_account_info failed: {}", exc)
    return None


def to_jq_security(symbol: str) -> str:
    text = str(symbol or "").strip().upper()
    if not text:
        return ""
    if text.endswith(".XSHG") or text.endswith(".XSHE"):
        return text
    if "." in text:
        code, suffix = text.split(".", 1)
        code = "".join(ch for ch in code if ch.isdigit())[-6:].zfill(6)
        if suffix in {"SH", "XSHG", "SS"}:
            return f"{code}.XSHG"
        if suffix in {"SZ", "XSHE"}:
            return f"{code}.XSHE"
    if text.startswith("SH") and len(text) > 2:
        return f"{text[2:].zfill(6)}.XSHG"
    if text.startswith("SZ") and len(text) > 2:
        return f"{text[2:].zfill(6)}.XSHE"
    code = "".join(ch for ch in text if ch.isdigit())[-6:].zfill(6)
    if not code:
        return ""
    suffix = ".XSHG" if code.startswith("6") else ".XSHE"
    return f"{code}{suffix}"


def compact_to_dash(date_text: str) -> str:
    digits = "".join(ch for ch in str(date_text or "") if ch.isdigit())
    if len(digits) < 8:
        return str(date_text)
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def dash_to_compact(date_text: str) -> str:
    digits = "".join(ch for ch in str(date_text or "") if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else digits


def _map_adjust(adjust: str) -> str | None:
    mapping = {"qfq": "pre", "pre": "pre", "hfq": "post", "post": "post"}
    return mapping.get(str(adjust or "").lower())


def _normalize_price_frame(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()

    frame = raw.copy()
    if isinstance(frame.index, pd.DatetimeIndex):
        frame = frame.reset_index()
    if "index" in frame.columns and "date" not in frame.columns:
        frame = frame.rename(columns={"index": "date"})

    date_col = next(
        (col for col in ("date", "time", "datetime") if col in frame.columns),
        None,
    )
    if not date_col:
        return pd.DataFrame()

    rename = {
        "open": "开盘",
        "close": "收盘",
        "high": "最高",
        "low": "最低",
        "volume": "成交量",
        "money": "成交额",
    }
    for src, dst in rename.items():
        if src in frame.columns and dst not in frame.columns:
            frame[dst] = frame[src]

    base_code = to_jq_security(symbol).split(".")[0]
    frame["日期"] = pd.to_datetime(frame[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
    frame["股票代码"] = base_code
    for col in ("开盘", "收盘", "最高", "最低", "成交量", "成交额"):
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")

    frame = frame.dropna(subset=["日期", "收盘"]).sort_values("日期")
    if frame.empty:
        return pd.DataFrame()

    prev_close = frame["收盘"].shift(1)
    frame["涨跌额"] = (frame["收盘"] - prev_close).round(4)
    frame["涨跌幅"] = ((frame["涨跌额"] / prev_close) * 100).round(2)
    frame["振幅"] = (
        ((frame["最高"] - frame["最低"]) / prev_close) * 100
    ).round(2)
    if "换手率" not in frame.columns:
        frame["换手率"] = 0.0

    columns = [
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
    return frame[columns].drop_duplicates("日期", keep="last").reset_index(drop=True)


class CachedJqData:
    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or DEFAULT_JQDATA_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def run(self, func_name: str, func_kwargs: dict, verbose: bool = False) -> Any:
        payload = json.dumps(func_kwargs, sort_keys=True, ensure_ascii=False)
        args_hash = hashlib.md5(payload.encode()).hexdigest()
        func_cache_dir = self.cache_dir / func_name
        func_cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = func_cache_dir / f"{args_hash}.pkl"
        if cache_file.exists():
            if verbose:
                logger.debug("JQData cache hit: {} {}", func_name, func_kwargs)
            with open(cache_file, "rb") as handle:
                return pickle.load(handle)

        if not ensure_jqdata_auth():
            return None

        if func_name == "get_price":
            result = self._get_price(**func_kwargs)
        elif func_name == "get_mtss":
            result = self._get_mtss(**func_kwargs)
        else:
            raise ValueError(f"Unsupported JQData func: {func_name}")

        with open(cache_file, "wb") as handle:
            pickle.dump(result, handle)
        return result

    def _get_price(
        self,
        security: str,
        start_date: str,
        end_date: str,
        frequency: str = "daily",
        fq: str | None = "pre",
        fields: list[str] | None = None,
    ) -> pd.DataFrame:
        from jqdatasdk import get_price

        jq_symbol = to_jq_security(security)
        if not jq_symbol:
            return pd.DataFrame()

        raw = get_price(
            jq_symbol,
            start_date=compact_to_dash(start_date),
            end_date=compact_to_dash(end_date),
            frequency=frequency,
            fields=fields,
            fq=fq,
            skip_paused=False,
            panel=False,
        )
        return _normalize_price_frame(raw, jq_symbol)

    def _get_mtss(
        self,
        security_list: list[str],
        start_date: str,
        end_date: str,
        fields: list[str] | None = None,
    ) -> pd.DataFrame:
        from jqdatasdk import get_mtss

        jq_symbols = [to_jq_security(code) for code in security_list if to_jq_security(code)]
        if not jq_symbols:
            return pd.DataFrame()
        return get_mtss(
            jq_symbols,
            start_date=compact_to_dash(start_date),
            end_date=compact_to_dash(end_date),
            fields=fields,
        )


jqdata_cached = CachedJqData()


def get_jqdata_allowed_range() -> tuple[str | None, str | None]:
    """Return (start, end) compact dates permitted by the current JQData account."""
    info = get_jqdata_account_info()
    if not info:
        return None, None
    start = dash_to_compact(str(info.get("date_range_start") or ""))
    end = dash_to_compact(str(info.get("date_range_end") or ""))
    if len(start) != 8 or len(end) != 8:
        return None, None
    return start, end


def clip_range_to_jqdata(start_date: str, end_date: str) -> tuple[str | None, str | None]:
    start_date = dash_to_compact(start_date)
    end_date = dash_to_compact(end_date)
    allowed_start, allowed_end = get_jqdata_allowed_range()
    if not allowed_start or not allowed_end:
        return start_date, end_date
    clipped_start = max(start_date, allowed_start)
    clipped_end = min(end_date, allowed_end)
    if clipped_start > clipped_end:
        return None, None
    return clipped_start, clipped_end


def is_jqdata_trial_account() -> bool:
    """Return True when account has a restricted historical window."""
    account_type = str(getattr(cfg, "jqdata_account_type", "formal") or "formal").lower()
    if account_type == "trial":
        return True
    if account_type == "formal":
        allowed_start, allowed_end = get_jqdata_allowed_range()
        if allowed_end:
            end_dt = datetime.strptime(allowed_end, "%Y%m%d")
            if (datetime.now() - end_dt).days > 30:
                return True
        return False


def jqdata_latest_available_date() -> str | None:
    """Upper bound for JQData history on trial accounts (~3 months lag)."""
    if not is_jqdata_trial_account():
        return None
    info = get_jqdata_account_info()
    if info:
        expire = info.get("expire_time") or info.get("expire_date")
        if expire:
            logger.debug("JQData trial account expire: {}", expire)
    return dash_to_compact((datetime.now() - timedelta(days=92)).strftime("%Y-%m-%d"))
