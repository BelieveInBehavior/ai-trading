"""Outcome label utilities for First Board Continue.

核心标签（P0）：
  - Entry 必须是实际可买点，而不是首板当天。
  - MFE/MAE 必须对应 Entry 之后的 T+1~T+3（持仓窗口）。
  - 主目标：Target_3 = MFE(T+1~T+3) >= +3%。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from strategies.first_board_continue.schemas import OutcomeMetrics


def normalize_dates(frame_or_rows) -> Dict[str, Dict[str, Any]]:
    """Convert a dataframe or list of rows into date-keyed dict with common col names.

    Accepts: pd.DataFrame, list[dict], or existing map.
    """
    try:
        import pandas as pd
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"pandas required for DataFrame handling: {exc}")

    if isinstance(frame_or_rows, pd.DataFrame):
        frame = frame_or_rows.copy()
        date_col = "日期" if "日期" in frame.columns else ("date" if "date" in frame.columns else None)
        if not date_col:
            return {}
        frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce").dt.strftime("%Y%m%d")
        frame = frame.dropna(subset=[date_col]).drop_duplicates(date_col, keep="last").sort_values(date_col)
        rows: List[Dict[str, Any]] = []
        for _, r in frame.iterrows():
            rows.append({str(k): v for k, v in r.to_dict().items()})
        return _rows_to_map(rows)
    if isinstance(frame_or_rows, dict):
        return frame_or_rows
    # assume list of rows
    return _rows_to_map(list(frame_or_rows) if frame_or_rows is not None else [])


def _rows_to_map(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        date = _first_str(row, "日期", "date", "trade_date", "timestamp")
        compact = "".join(ch for ch in str(date or "") if ch.isdigit())
        if len(compact) < 8:
            continue
        compact = compact[:8]
        out[compact] = row
    return out


def _first_str(row: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        if k in row and row[k] is not None:
            return str(row[k])
    return ""


def _num(row: Dict[str, Any], *keys: str, default: Optional[float] = None) -> Optional[float]:
    for k in keys:
        if k in row and row[k] is not None:
            try:
                v = float(row[k])
                if v == v:  # not NaN
                    return v
            except (TypeError, ValueError):
                continue
    return default


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if not a or a <= 0 or b is None:
        return None
    return (b - a) / a * 100.0


def compute_outcome_metrics(
    row_map: Dict[str, Dict[str, Any]],
    entry_date: str,
    horizon_days: int = 3,
    positive_pct: float = 3.0,
) -> Optional[OutcomeMetrics]:
    """Compute entry + MFE/MAE/CloseReturn labels from a date-keyed OHLC map.

    entry is the open on `entry_date`. horizon_days = 1..N (T+1, T+2, ..., T+horizon_days).
    """
    sample = next(iter(row_map.values()), {}) or {}
    open_col = "开盘" if "开盘" in sample else "open"
    close_col = "收盘" if "收盘" in sample else "close"
    high_col = "最高" if "最高" in sample else "high"
    low_col = "最低" if "最低" in sample else "low"

    def _val(d: str, col: str) -> Optional[float]:
        row = row_map.get(d)
        if not row:
            return None
        return _num(row, col)

    entry_open = _val(entry_date, open_col)
    if not entry_open or entry_open <= 0:
        return None

    # T+1..T+N dates
    sorted_dates = sorted(k for k in row_map.keys() if len(str(k)) == 8)
    try:
        idx = sorted_dates.index(str(entry_date))
    except ValueError:
        return None
    future_dates = sorted_dates[idx + 1: idx + 1 + horizon_days]
    if not future_dates:
        return None

    t1_date = future_dates[0]
    t2_date = future_dates[1] if len(future_dates) > 1 else None
    t3_date = future_dates[2] if len(future_dates) > 2 else None

    max_high = entry_open
    min_low = entry_open
    for d in future_dates:
        r = row_map.get(d)
        if not r:
            continue
        hi = _num(r, high_col, default=entry_open) or entry_open
        lo = _num(r, low_col, default=entry_open) or entry_open
        max_high = max(max_high, hi)
        min_low = min(min_low, lo)

    def _close_ret(d: Optional[str]) -> Optional[float]:
        if d is None:
            return None
        c = _val(d, close_col)
        return _pct(entry_open, c)

    def _mfe(include_date: Optional[str]) -> Optional[float]:
        end_idx = None
        if include_date:
            if include_date in future_dates:
                end_idx = future_dates.index(include_date) + 1
        dates = future_dates[:end_idx] if end_idx else future_dates
        high = entry_open
        for d in dates:
            row = row_map.get(d)
            if not row:
                continue
            hi = _num(row, high_col, default=entry_open) or entry_open
            high = max(high, hi)
        return _pct(entry_open, high)

    def _mae(include_date: Optional[str]) -> Optional[float]:
        end_idx = None
        if include_date:
            if include_date in future_dates:
                end_idx = future_dates.index(include_date) + 1
        dates = future_dates[:end_idx] if end_idx else future_dates
        low = entry_open
        for d in dates:
            row = row_map.get(d)
            if not row:
                continue
            lo = _num(row, low_col, default=entry_open) or entry_open
            low = min(low, lo)
        return _pct(entry_open, low)

    close_t1 = _val(t1_date, close_col)
    close_t2 = _val(t2_date, close_col) if t2_date else None
    close_t3 = _val(t3_date, close_col) if t3_date else None
    mfe_t3 = _mfe(t3_date)
    target3 = bool(mfe_t3 is not None and positive_pct is not None and mfe_t3 >= positive_pct)

    m = OutcomeMetrics(
        symbol_code=str(sample.get("symbol_code") or sample.get("代码") or ""),
        entry_date=entry_date,
        entry_price=round(entry_open, 4),
        close_t1=close_t1,
        close_t2=close_t2,
        close_t3=close_t3,
        mfe_t1=_mfe(t1_date),
        mfe_t2=_mfe(t2_date),
        mfe_t3=mfe_t3,
        mae_t1=_mae(t1_date),
        mae_t2=_mae(t2_date),
        mae_t3=_mae(t3_date),
        close_return_t1=_close_ret(t1_date),
        close_return_t2=_close_ret(t2_date),
        close_return_t3=_close_ret(t3_date),
        positive_pct=positive_pct,
        target_3=target3,
    )
    return m
