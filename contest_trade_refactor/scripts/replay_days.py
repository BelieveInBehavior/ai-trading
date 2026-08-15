#!/usr/bin/env python3
"""Replay the current pipeline over a range of trading days using isolated outputs.

This is an operational helper. It does NOT modify backend gating/scoring logic.
It only runs the existing pipeline for several trigger dates, each in its own
subprocess with a separate CONTEST_TRADE_WORKSPACE, so the results are easy to
tell apart from the legacy agents_workspace data.

Usage examples:
  python scripts/replay_days.py --start-date 2026-08-11 --end-date 2026-08-13 \
      --strategy momentum --output-dir agents_workspace_replays/momentum
  python scripts/replay_days.py --start-date 2026-08-13 --symbols-limit 20 \
      --strategy momentum --output-dir agents_workspace_replays/validate13

With --symbols-limit > 0 the script still feeds candidates to the normal ranking
pipeline, but only scans the first N symbols in Stage 0. This is meant for a
quick smoke test; the default (0) scans the full market.
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
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
RUN_PIPELINE = PROJECT_ROOT / "scripts" / "run_pipeline_rerun.py"


def _compact(date: str) -> str:
    return str(date).strip().replace("-", "")


def resolve_trading_dates(start: str, end: str, market: str = "CN-Stock") -> List[str]:
    """Return trading dates between start/end (inclusive), as YYYY-MM-DD."""
    # We need the market calendar; import inside to avoid cfg import at module top.
    import config.config  # noqa: F401  (loads .env / cfg)
    from utils.market_manager import GLOBAL_MARKET_MANAGER
    try:
        trade_dates = GLOBAL_MARKET_MANAGER.get_trade_date(market_name=market)
    except Exception as exc:
        print(f"[replay] could not load trade dates ({exc}); using calendar days", flush=True)
        trade_dates = []

    if not trade_dates:
        return []

    start_d = _compact(start)
    end_d = _compact(end)
    matching = [d for d in trade_dates if start_d <= d <= end_d]
    matching = [
        f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else d
        for d in sorted(matching)
    ]
    return matching


def build_trigger(start_date: str, hour: int = 18, minute: int = 0) -> str:
    d = _compact(start_date)
    if len(d) != 8 or not d.isdigit():
        raise ValueError(f"invalid date: {start_date!r}")
    return f"{d[:4]}-{d[4:6]}-{d[6:8]} {hour:02d}:{minute:02d}:00"


def run_pipeline_one_day(
    strategy: str,
    trigger_time: str,
    workspace: Path,
    symbols_limit: int,
    concurrency: int,
) -> dict:
    """Launch run_pipeline_rerun.py in a subprocess with isolated workspace env."""
    workspace.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(VENV_PYTHON if VENV_PYTHON.exists() else sys.executable),
        "-u",
        str(RUN_PIPELINE),
        "--strategy", strategy,
        "--trigger-time", trigger_time,
        "--symbols-limit", str(symbols_limit),
        "--concurrency", str(concurrency),
    ]
    env = dict(os.environ)
    env["CONTEST_TRADE_WORKSPACE"] = str(workspace)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")

    print(f"\n[replay] launching: {' '.join(cmd)}", flush=True)
    print(f"[replay] workspace={workspace}", flush=True)
    proc = subprocess.run(cmd, env=env, cwd=PROJECT_ROOT)

    stats = {
        "date": _compact(trigger_time)[:8],
        "trigger_time": trigger_time,
        "strategy": strategy,
        "workspace": str(workspace),
        "exit_code": proc.returncode,
        "status": "ok" if proc.returncode == 0 else "error",
    }
    manifest = workspace / "replay_manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest, "a", encoding="utf-8") as f:
        f.write(json.dumps(stats, ensure_ascii=False) + "\n")
    print(f"[replay] done date={stats['date']} status={stats['status']} exit={proc.returncode}", flush=True)
    return status_to_returncode(proc.returncode)


def status_to_returncode(code: int) -> int:
    return 0 if code == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay current pipeline over several trading days with isolated output."
    )
    parser.add_argument("--strategy", default="momentum", help="swing or momentum")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--end-date", default=None, help="default = start-date")
    parser.add_argument("--output-dir", default=None,
                        help="relative/absolute directory to write isolated workspace; "
                             "default = agents_workspace_replays/<strategy>")
    parser.add_argument("--hour", type=int, default=18, help="hour used for trigger_time")
    parser.add_argument("--symbols-limit", type=int, default=0,
                        help="if >0, only scan first N symbols during Stage 0 (smoke test)")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    end_date = args.end_date or args.start_date
    dates = resolve_trading_dates(args.start_date, end_date)
    if not dates:
        print(f"[replay] no trading days between {args.start_date} and {end_date}", flush=True)
        sys.exit(1)

    if args.output_dir:
        base = Path(args.output_dir).expanduser().resolve()
    else:
        base = PROJECT_ROOT / "agents_workspace_replays" / args.strategy

    print(f"[replay] plan dates={dates} strategy={args.strategy} output={base}", flush=True)
    any_error = False
    for date in dates:
        trigger = build_trigger(date, hour=args.hour)
        workspace = base / _compact(date)
        rc = run_pipeline_one_day(
            strategy=args.strategy,
            trigger_time=trigger,
            workspace=workspace,
            symbols_limit=args.symbols_limit,
            concurrency=args.concurrency,
        )
        any_error = any_error or rc != 0

    print("[replay] all done", flush=True)
    sys.exit(1 if any_error else 0)


if __name__ == "__main__":
    main()
