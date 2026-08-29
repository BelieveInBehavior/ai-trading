"""Strategy-agnostic daily bar store.

Bars are stored per symbol (not per query range). Callers slice with
``date <= asof`` so backtests can reuse the same file across days and strategies.
"""
from __future__ import annotations

import os
import pickle
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from utils.market_data_paths import legacy_market_bar_store_dir, market_bar_store_dir

DEFAULT_STORE_DIR = market_bar_store_dir()
_STORE: Optional["MarketBarStore"] = None
_STORE_LOCK = threading.Lock()


def store_enabled() -> bool:
    return str(os.environ.get("CN_MARKET_BAR_STORE", "1")).lower() not in {"0", "false", "no", "off"}


def _compact(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    text = str(value).strip().replace("-", "").replace("/", "")
    return text[:8] if len(text) >= 8 and text[:8].isdigit() else ""


def _stock_key(symbol: str) -> str:
    digits = "".join(ch for ch in str(symbol or "") if ch.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def _safe_key(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value or "").strip())


def _shift_compact(date_text: str, days: int) -> str:
    dt = datetime.strptime(_compact(date_text), "%Y%m%d") + timedelta(days=days)
    return dt.strftime("%Y%m%d")


class MarketBarStore:
    def __init__(self, root: Path | None = None):
        if root:
            self.root = Path(root)
        else:
            preferred = market_bar_store_dir()
            self.root = preferred if preferred.exists() else legacy_market_bar_store_dir()
        self._mem: dict[tuple[str, str, str], pd.DataFrame] = {}
        self._lock = threading.RLock()

    def _path(self, kind: str, key: str, adjust: str = "") -> Path:
        parts = [self.root, kind]
        if adjust:
            parts.append(adjust)
        return Path(*parts) / f"{_safe_key(key)}.pkl"

    def load(self, kind: str, key: str, adjust: str = "") -> pd.DataFrame:
        cache_key = (kind, key, adjust)
        with self._lock:
            cached = self._mem.get(cache_key)
            if cached is not None:
                return cached.copy()
            path = self._path(kind, key, adjust)
            if not path.exists():
                empty = pd.DataFrame()
                self._mem[cache_key] = empty
                return empty.copy()
            try:
                with path.open("rb") as fh:
                    frame = pickle.load(fh)
            except Exception:
                frame = pd.DataFrame()
            if not isinstance(frame, pd.DataFrame):
                frame = pd.DataFrame()
            self._mem[cache_key] = frame
            return frame.copy()

    def upsert(self, kind: str, key: str, df: pd.DataFrame, *, date_col: str, adjust: str = "") -> pd.DataFrame:
        if df is None or df.empty or not key or date_col not in df.columns:
            return self.load(kind, key, adjust)
        incoming = df.copy()
        with self._lock:
            existing = self.load(kind, key, adjust)
            merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming
            merged = merged.dropna(subset=[date_col]).drop_duplicates(date_col, keep="last")
            if date_col == "日期":
                merged[date_col] = pd.to_datetime(merged[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
                merged = merged.dropna(subset=[date_col]).drop_duplicates(date_col, keep="last")
                merged = merged.sort_values(date_col).reset_index(drop=True)
            else:
                merged[date_col] = pd.to_datetime(merged[date_col], errors="coerce")
                merged = merged.dropna(subset=[date_col]).drop_duplicates(date_col, keep="last")
                merged = merged.sort_values(date_col).reset_index(drop=True)
            path = self._path(kind, key, adjust)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".pkl.tmp")
            with tmp.open("wb") as fh:
                pickle.dump(merged, fh)
            tmp.replace(path)
            self._mem[(kind, key, adjust)] = merged
            return merged.copy()

    def slice(self, df: pd.DataFrame, start_date: str, end_date: str, *, date_col: str) -> pd.DataFrame:
        if df is None or df.empty or date_col not in df.columns:
            return pd.DataFrame()
        start = _compact(start_date)
        end = _compact(end_date)
        keys = df[date_col].map(_compact)
        mask = pd.Series(True, index=df.index)
        if start:
            mask &= keys >= start
        if end:
            mask &= keys <= end
        return df.loc[mask].copy().reset_index(drop=True)

    def covers(self, df: pd.DataFrame, start_date: str, end_date: str, *, date_col: str) -> bool:
        if df is None or df.empty or date_col not in df.columns:
            return False
        keys = [k for k in (_compact(v) for v in df[date_col]) if k]
        if not keys:
            return False
        start = _compact(start_date)
        end = _compact(end_date)
        if start and min(keys) > start:
            return False
        if end and max(keys) < end:
            return False
        return True

    def missing_ranges(self, df: pd.DataFrame, start_date: str, end_date: str, *, date_col: str) -> list[tuple[str, str]]:
        start = _compact(start_date)
        end = _compact(end_date)
        if not start or not end or start > end:
            return []
        if df is None or df.empty or date_col not in df.columns:
            return [(start, end)]
        keys = [k for k in (_compact(v) for v in df[date_col]) if k]
        if not keys:
            return [(start, end)]
        first, last = min(keys), max(keys)
        gaps: list[tuple[str, str]] = []
        if first > start:
            head_end = _shift_compact(first, -1)
            if head_end >= start:
                gaps.append((start, head_end))
        if last < end:
            tail_start = _shift_compact(last, 1)
            if tail_start <= end:
                gaps.append((tail_start, end))
        return gaps

    def load_stock(self, symbol: str, adjust: str = "qfq") -> pd.DataFrame:
        key = _stock_key(symbol)
        return self.load("stocks", key, adjust) if key else pd.DataFrame()

    def upsert_stock(self, symbol: str, df: pd.DataFrame, adjust: str = "qfq") -> pd.DataFrame:
        key = _stock_key(symbol)
        if not key:
            return pd.DataFrame()
        return self.upsert("stocks", key, df, date_col="日期", adjust=adjust)


def get_market_bar_store() -> MarketBarStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = MarketBarStore()
        return _STORE


def reset_market_bar_store(root: Path | None = None) -> MarketBarStore:
    global _STORE
    with _STORE_LOCK:
        _STORE = MarketBarStore(root=root)
        return _STORE
