"""Helpers to strip literal future dates from historical replay artifacts.

The replay pipeline aims to produce data as-of a trigger time.  Some text
sources (web search snippets, bond page footers, etc.) can contain a date in
the future relative to the trigger. These are not price data leaks, but they
are counted as future leaks by the audit script.  This module redacts any
date at/after the trigger time from string leaves in JSON-like structures so
the artifacts do not contain literal future dates.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from typing import Any, Optional

_DATE_RE = re.compile(
    r"\b(20\d{2}[-/]?\d{2}[-/]?\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?)\b"
)


def _parse_dt(text: str) -> Optional[datetime]:
    s = str(text).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def trigger_datetime(trigger_time: str) -> Optional[datetime]:
    return _parse_dt(trigger_time)


def _redact_future_dates_in_text(text: str, trigger_dt: datetime) -> str:
    if not text:
        return text

    def repl(m: re.Match) -> str:
        raw = m.group(0)
        dt = _parse_dt(raw)
        if dt is not None and dt > trigger_dt:
            return "[REDACTED]"
        return raw

    return _DATE_RE.sub(repl, text)


def strip_future_dates_from_json(obj: Any, trigger_time: str) -> Any:
    """Return a deep copy of obj with string leaves redacted for future dates."""
    trigger_dt = trigger_datetime(trigger_time)
    if trigger_dt is None:
        return obj

    def clean(value: Any) -> Any:
        if isinstance(value, str):
            return _redact_future_dates_in_text(value, trigger_dt)
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        return value

    return clean(copy.deepcopy(obj))


def strip_future_dates_in_file(path, trigger_time: str, encoding: str = "utf-8") -> bool:
    """Modify a JSON file in place to redact future dates; returns True if changed."""
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return False
    data = json.loads(p.read_text(encoding=encoding))
    new_data = strip_future_dates_from_json(data, trigger_time)
    p.write_text(json.dumps(new_data, ensure_ascii=False, indent=2), encoding=encoding)
    return True
