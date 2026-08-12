"""Validation helpers for market data used by ranking and backtesting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import pandas as pd


@dataclass
class DataQualityReport:
    """Machine-readable validation result."""

    valid: bool
    status: str
    row_count: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    last_date: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "status": self.status,
            "row_count": self.row_count,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "last_date": self.last_date,
        }


def _first_column(frame: pd.DataFrame, names: Iterable[str]) -> str | None:
    return next((name for name in names if name in frame.columns), None)


def validate_market_frame(
    frame: pd.DataFrame | None,
    *,
    as_of_date: str | None = None,
    min_rows: int = 1,
    require_ohlcv: bool = True,
) -> DataQualityReport:
    """Validate a market-history frame without silently repairing core data.

    The caller may decide whether warnings are acceptable, but invalid prices,
    malformed dates, duplicate dates, and future observations are hard errors.
    """

    if frame is None or frame.empty:
        return DataQualityReport(False, "empty", 0, ["empty_frame"])

    date_column = _first_column(frame, ("date", "日期"))
    close_column = _first_column(frame, ("close", "收盘"))
    required = [date_column, close_column]
    if require_ohlcv:
        required.extend(
            [
                _first_column(frame, ("open", "开盘")),
                _first_column(frame, ("high", "最高")),
                _first_column(frame, ("low", "最低")),
                _first_column(frame, ("volume", "成交量")),
            ]
        )

    errors: list[str] = []
    warnings: list[str] = []
    if any(column is None for column in required):
        return DataQualityReport(
            False,
            "schema_error",
            len(frame),
            ["missing_required_columns"],
        )

    dates = pd.to_datetime(frame[date_column], errors="coerce")
    if dates.isna().any():
        errors.append("invalid_dates")

    if dates.duplicated().any():
        errors.append("duplicate_dates")

    if not dates.is_monotonic_increasing:
        warnings.append("dates_not_sorted")

    if as_of_date:
        cutoff = pd.to_datetime(as_of_date, errors="coerce")
        if pd.isna(cutoff):
            errors.append("invalid_as_of_date")
        elif (dates > cutoff).any():
            errors.append("future_data")

    numeric_columns = {
        "close": close_column,
        "open": _first_column(frame, ("open", "开盘")),
        "high": _first_column(frame, ("high", "最高")),
        "low": _first_column(frame, ("low", "最低")),
        "volume": _first_column(frame, ("volume", "成交量")),
    }
    numeric: dict[str, pd.Series] = {}
    for name, column in numeric_columns.items():
        if column is None:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        numeric[name] = values
        if values.isna().any():
            errors.append(f"invalid_{name}")

    if all(name in numeric for name in ("open", "high", "low", "close")):
        open_values = numeric["open"]
        high_values = numeric["high"]
        low_values = numeric["low"]
        close_values = numeric["close"]
        invalid_range = (
            (high_values < open_values)
            | (high_values < close_values)
            | (low_values > open_values)
            | (low_values > close_values)
        )
        if invalid_range.fillna(False).any():
            errors.append("invalid_ohlc_range")

    for name in ("open", "high", "low", "close"):
        if name in numeric and (numeric[name] <= 0).fillna(False).any():
            errors.append(f"non_positive_{name}")
    if "volume" in numeric and (numeric["volume"] < 0).fillna(False).any():
        errors.append("negative_volume")

    if len(frame) < min_rows:
        errors.append(f"insufficient_rows<{min_rows}")

    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))
    last_date = None
    valid_dates = dates.dropna()
    if not valid_dates.empty:
        last_date = valid_dates.max().strftime("%Y-%m-%d")

    return DataQualityReport(
        valid=not errors,
        status="ok" if not errors else "invalid",
        row_count=len(frame),
        errors=errors,
        warnings=warnings,
        last_date=last_date,
    )


def normalize_market_frame(
    frame: pd.DataFrame | None,
    *,
    as_of_date: str | None = None,
    min_rows: int = 1,
    require_ohlcv: bool = True,
) -> tuple[pd.DataFrame, DataQualityReport]:
    """Normalize dates/numbers after validation and return a report."""

    report = validate_market_frame(
        frame,
        as_of_date=as_of_date,
        min_rows=min_rows,
        require_ohlcv=require_ohlcv,
    )
    if frame is None or frame.empty:
        return pd.DataFrame(), report

    normalized = frame.copy()
    date_column = _first_column(normalized, ("date", "日期"))
    if date_column:
        normalized[date_column] = pd.to_datetime(normalized[date_column], errors="coerce")
        normalized = normalized.sort_values(date_column).drop_duplicates(
            date_column,
            keep="last",
        )
    for column in normalized.columns:
        if column in {"date", "日期"}:
            continue
        if column in {"open", "开盘", "high", "最高", "low", "最低", "close", "收盘", "volume", "成交量"}:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    return normalized.reset_index(drop=True), report
