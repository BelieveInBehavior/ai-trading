#!/usr/bin/env python3
"""
Future-evidence audit for trade decision JSONs.

Scans every signal's `analysis_as_of_date`, `trigger_time`, `evidence_list[*].time`,
and technical factor `report_date`; flags any timestamp strictly after the analysis
date.

Outputs:
  <output>/future_leak_audit.csv
  <output>/future_leak_audit.md

Usage:
  .venv/bin/python scripts/audit_future_leak.py \\
      --glob 'agents_workspace_res/replays/.../results/trade_decisions/*.json' \\
      --output agents_workspace/backtest_results/audit
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


def parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def collect_fields(obj) -> List[tuple]:
    """Return list of (path, value) from dict/list with shallow recursion."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _is_date_like_field(k, v):
                out.append((k, v))
            if isinstance(v, (dict, list)):
                out.extend(collect_fields(v))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, (dict, list)):
                out.extend(collect_fields(v))
    return out


def _is_date_like_field(field: str, value: Any) -> bool:
    """Heuristic: field name suggests date/time, or value is an ISO-ish timestamp string."""
    field_l = str(field).lower()
    value_s = str(value).strip()
    # Heuristic to avoid false positives on symbols/numbers.
    if value_s.isdigit():
        # Accept only compact date-looking patterns like 20260810 / 2026-08-10
        if len(value_s) == 8 and value_s[:4].isdigit() and field_l in {
            "report_date", "analysis_as_of_date", "trigger_date", "factor_date",
            "trade_date", "date", "asof", "as_of", "ann_date", "end_date", "pub_date",
        }:
            return True
        if field_l in {"time", "pub_time", "signal_time", "trigger_time", "updated_at", "created_at"}:
            return True
        return False
    if "-" not in value_s and ":" not in value_s and "/" not in value_s:
        return False
    return any(k in field_l for k in ["date", "time", "pub", "timestamp", "asof", "as_of"])





def _iter_text_paths(obj, path=''):
    """Yield (path, text) for all string leaves in JSON-like structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            if isinstance(v, (dict, list)):
                yield from _iter_text_paths(v, p)
            elif isinstance(v, str):
                yield (p, v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, (dict, list)):
                yield from _iter_text_paths(v, f"{path}[{i}]")
            elif isinstance(v, str):
                yield (f"{path}[{i}]", v)


def audit(glob_pattern: str) -> pd.DataFrame:
    files = sorted(Path(p) for p in glob.glob(glob_pattern))
    rows = []
    if not files:
        return pd.DataFrame()
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            rows.append({
                "file": str(path),
                "trigger_time": "",
                "analysis_as_of": "",
                "field": "",
                "value": "",
                "parsed": "",
                "leak": "error",
                "note": str(exc),
            })
            continue
        trigger = str(payload.get("trigger_time") or "")
        trigger_dt = parse_dt(trigger)
        analysis_dt = trigger_dt
        # 1) Half-structured date fields.
        candidates = collect_fields(payload)
        for field, value in candidates:
            if field in {"trigger_time", "source_file", "source_path", "content", "thinking", "final_result"}:
                continue
            dt = parse_dt(value)
            if dt is None or trigger_dt is None:
                continue
            if dt > trigger_dt:
                rows.append({
                    "file": path.name,
                    "trigger_time": trigger,
                    "analysis_as_of": trigger_dt.strftime("%Y-%m-%d %H:%M:%S") if trigger_dt else "",
                    "symbol": value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)[:120],
                    "field": field,
                    "field_value": str(value)[:200],
                    "parsed": dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "leak": "YES",
                    "note": "future timestamp (structured field)",
                })

        # 2) Also scan natural-language text fields for any ISO/8-digit date > trigger,
        #    which catches future dates embedded in agent context/summaries.
        if trigger_dt is not None:
            for field, text in _iter_text_paths(payload):
                for m in re.finditer(r"\b(20\d{2}[-/]?\d{2}[-/]?\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?)\b", text):
                    raw = m.group(1)
                    dt = parse_dt(raw)
                    if dt is None or dt <= trigger_dt:
                        continue
                    rows.append({
                        "file": path.name,
                        "trigger_time": trigger,
                        "analysis_as_of": trigger_dt.strftime("%Y-%m-%d %H:%M:%S") if trigger_dt else "",
                        "symbol": raw,
                        "field": field,
                        "field_value": text[max(0, m.start()-60):m.end()+60],
                        "parsed": dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "leak": "YES",
                        "note": "future date in text field",
                    })

    df = pd.DataFrame(rows)
    if not df.empty:
        # dedupe near-identical rows from many duplicate strings (batch_summaries vs context_string)
        df = df.drop_duplicates(subset=["file", "field", "field_value", "parsed", "leak"])
        # Only expose actual future leaks to the report; keep NO rows out.
        df = df[df["leak"] == "YES"]
    return df


def write_audit(df: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "future_leak_audit.csv"
    md_path = output_dir / "future_leak_audit.md"
    if df.empty:
        csv_path.write_text("", encoding="utf-8")
        md_path.write_text("# Future Leak Audit\n\nNo files / no findings.\n", encoding="utf-8")
        print(f"[audit] {output_dir / 'future_leak_audit.csv'}")
        print(f"[audit] {output_dir / 'future_leak_audit.md'}")
        return
    df.to_csv(csv_path, index=False)
    leaks = df[df["leak"] == "YES"]
    lines = [
        "# Future Leak Audit",
        "",
        f"Files scanned: {df['file'].nunique()}",
        f"Rows checked: {len(df)}",
        f"Future leaks: {len(leaks)}",
        "",
        "## Findings",
        "",
    ]
    if not leaks.empty:
        lines.append(leaks.head(100).to_markdown(index=False))
    else:
        lines.append("No future timestamp leaks found.")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[audit] {md_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--glob", required=True)
    parser.add_argument("--output", default="agents_workspace/backtest_results/audit")
    args = parser.parse_args()
    df = audit(args.glob)
    write_audit(df, Path(args.output))


if __name__ == "__main__":
    main()
