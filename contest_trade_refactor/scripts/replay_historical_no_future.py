#!/usr/bin/env python3
"""
Historical replay with strict no-future enforcement.

This is a thin wrapper around the existing `replay_days.py` pipeline shell that:
  - sets `CONTEST_TRADE_ASOF_DATE=<trigger_date>` in the child environment so
    `utils/cn_price_provider.get_stock_zh_a_hist()` caps K-line end date at the
    trigger date (unless an explicit end_date is provided).
  - writes each day's output into an isolated replay workspace.
  - after each day, runs a future-leak audit on that day's `trade_decision` JSON.

WARNING:
  This wrapper reduces literal future-price leakage from the price provider.
  It does NOT fully guarantee that:
    - caches/reports created later are not used
    - search/news providers respect trigger_time
    - LLM world knowledge does not leak
  Use it as an incremental step, not as a bulletproof historical backtest.

Usage:
  .venv/bin/python scripts/replay_historical_no_future.py \\
      --start-date 2026-08-11 --end-date 2026-08-14 --strategy momentum
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
RUN_PIPELINE = PROJECT_ROOT / "scripts" / "run_pipeline_rerun.py"
AUDIT_SCRIPT = PROJECT_ROOT / "scripts" / "audit_future_leak.py"


def _compact(date: str) -> str:
    return str(date).strip().replace("-", "")


def resolve_trading_dates(start: str, end: str, market: str = "CN-Stock") -> List[str]:
    import config.config  # noqa: F401
    from utils.market_manager import GLOBAL_MARKET_MANAGER
    trade_dates = GLOBAL_MARKET_MANAGER.get_trade_date(market_name=market)
    trade_dates = [str(td).replace("-", "").replace("/", "") for td in trade_dates]
    start_d = _compact(start)
    end_d = _compact(end)
    return [d for d in sorted(trade_dates) if start_d <= d <= end_d]


def build_trigger(date_compact: str, hour: int = 18, minute: int = 0) -> str:
    return f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:8]} {hour:02d}:{minute:02d}:00"


def _redact_future_dates_in_workspace(workspace: Path, trigger_time: str) -> None:
    """Redact literal future dates from replay result JSONs before auditing."""
    from utils.future_leak_guard import strip_future_dates_in_file
    files = list((workspace / "results" / "trade_decisions").glob("*.json"))
    if not files:
        return
    print(f"[replay] redacting future dates in {len(files)} trade decision json(s)", flush=True)
    for f in files:
        try:
            strip_future_dates_in_file(f, trigger_time)
        except Exception as exc:
            print(f"[replay] WARN failed to redact {f}: {exc}", flush=True)


def run_day(
    strategy: str,
    date_compact: str,
    output_dir: Path,
    symbols_limit: int,
    concurrency: int,
    hour: int,
    run_audit: bool,
) -> dict:
    trigger = build_trigger(date_compact, hour=hour)
    workspace = output_dir / date_compact
    workspace.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(VENV_PYTHON),
        "-u",
        str(RUN_PIPELINE),
        "--strategy", strategy,
        "--trigger-time", trigger,
        "--symbols-limit", str(symbols_limit),
        "--concurrency", str(concurrency),
    ]
    env = dict(os.environ)
    env["CONTEST_TRADE_WORKSPACE"] = str(workspace)
    env["CONTEST_TRADE_ASOF_DATE"] = date_compact
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    print(f"\n[replay] date={date_compact} trigger={trigger} asof={date_compact}", flush=True)
    proc = subprocess.run(cmd, env=env, cwd=PROJECT_ROOT)
    status = "ok" if proc.returncode == 0 else "error"

    # Write manifest
    manifest = workspace / "replay_manifest.jsonl"
    with open(manifest, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "date": date_compact,
            "trigger_time": trigger,
            "asof": date_compact,
            "strategy": strategy,
            "exit_code": proc.returncode,
            "status": status,
        }, ensure_ascii=False) + "\n")

    if run_audit and proc.returncode == 0:
        _redact_future_dates_in_workspace(workspace, trigger)
        print(f"[replay] auditing day {date_compact} for future leaks", flush=True)
        audit_cmd = [
            str(VENV_PYTHON),
            str(AUDIT_SCRIPT),
            "--glob", str(workspace / "results" / "trade_decisions" / "*.json"),
            "--output", str(workspace / "audit"),
        ]
        subprocess.run(audit_cmd, env=env, cwd=PROJECT_ROOT)
    return {"date": date_compact, "status": status, "exit_code": proc.returncode}


def _has_successful_manifest(output_dir: Path, date_compact: str) -> bool:
    manifest = output_dir / date_compact / "replay_manifest.jsonl"
    if not manifest.exists():
        return False
    try:
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("date") == date_compact and entry.get("status") == "ok":
                return True
    except Exception:
        return False
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", default="momentum", choices=["momentum", "swing", "strong_diverge", "quant_research"])
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output-dir", default="agents_workspace_replays/historical_no_future")
    parser.add_argument("--symbols-limit", type=int, default=0,
                        help="limit Stage 0 universe; use small number for smoke test")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--hour", type=int, default=18)
    parser.add_argument("--no-audit", action="store_true")
    parser.add_argument("--skip-dates", default="",
                        help="comma-separated YYYY-MM-DD dates to skip (e.g. 2026-08-11)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="skip dates whose replay workspace already has a status=ok manifest entry")
    args = parser.parse_args()

    end = args.end_date or args.start_date
    dates = resolve_trading_dates(args.start_date, end)
    if not dates:
        print(f"[error] no trading days between {args.start_date} and {end}")
        sys.exit(1)

    skip_dates = {_compact(x) for x in args.skip_dates.split(",") if x.strip()}
    if skip_dates:
        print(f"[replay] skip_dates={sorted(skip_dates)}", flush=True)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[replay] plan dates={dates} output={output_dir}", flush=True)

    any_error = False
    for date_compact in dates:
        if date_compact in skip_dates:
            print(f"[replay] skip date={date_compact} (user skip)", flush=True)
            continue
        if args.skip_existing and _has_successful_manifest(output_dir, date_compact):
            print(f"[replay] skip date={date_compact} (already ok)", flush=True)
            continue
        res = run_day(
            strategy=args.strategy,
            date_compact=date_compact,
            output_dir=output_dir,
            symbols_limit=args.symbols_limit,
            concurrency=args.concurrency,
            hour=args.hour,
            run_audit=not args.no_audit,
        )
        if res["status"] != "ok":
            any_error = True
    print("[replay] all done")
    sys.exit(1 if any_error else 0)


if __name__ == "__main__":
    main()
