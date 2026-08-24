"""Replay / Event Logger：把 T 日候选与 T+1 决策落成可回放 jsonl。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


def log_event(output_dir: str | Path, event: Dict[str, Any], *, filename: str = "events.jsonl") -> Path:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("logged_at", datetime.now().isoformat(timespec="seconds"))
    dest = path / filename
    with dest.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return dest


def log_tday_pool(output_dir: str | Path, trade_date: str, pool: list, themes: Optional[list] = None) -> Path:
    return log_event(
        output_dir,
        {
            "event": "tday_pool",
            "trade_date": trade_date,
            "count": len(pool),
            "symbols": [r.get("symbol_code") for r in pool],
            "themes": themes or [],
        },
    )
