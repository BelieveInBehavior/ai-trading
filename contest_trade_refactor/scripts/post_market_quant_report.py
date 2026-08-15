#!/usr/bin/env python3
"""
Post-market quantitative report runner.

1. Optionally runs the full pipeline to generate new trade_decision output.
2. Runs the signal closed-loop evaluator.
3. Writes a daily/weekly aggregated performance report (markdown + csv summary).

Usage:
  .venv/bin/python scripts/post_market_quant_report.py --date 2026-08-14
  .venv/bin/python scripts/post_market_quant_report.py --date 2026-08-14 --run-pipeline

Outputs:
  agents_workspace/backtest_results/daily_report_YYYYMMDD.md
  agents_workspace/backtest_results/performance_dashboard.csv
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def run_cmd(cmd: List[str]) -> int:
    print(f"[cmd] {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return proc.returncode


def load_signal_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def build_dashboard(signal_csv: Path, output_dir: Path) -> pd.DataFrame:
    df = load_signal_csv(signal_csv)
    if df.empty:
        return pd.DataFrame()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Basic per-day dashboard with available horizons
    rows = []
    if "trigger_date" in df.columns and "t1_return_pct" in df.columns:
        for trigger_date, g in df.groupby("trigger_date"):
            t1 = g["t1_return_pct"].dropna()
            t3 = g.get("t3_return_pct", pd.Series(dtype=float)).dropna() if "t3_return_pct" in g.columns else pd.Series(dtype=float)
            t5 = g.get("t5_return_pct", pd.Series(dtype=float)).dropna() if "t5_return_pct" in g.columns else pd.Series(dtype=float)
            rows.append({
                "trigger_date": trigger_date,
                "signals_total": len(g),
                "t1_count": len(t1),
                "t1_winrate": round((t1 > 0).mean() * 100, 1) if len(t1) else None,
                "t1_avg": round(t1.mean(), 3) if len(t1) else None,
                "t3_count": len(t3),
                "t3_winrate": round((t3 > 0).mean() * 100, 1) if len(t3) else None,
                "t3_avg": round(t3.mean(), 3) if len(t3) else None,
                "t5_count": len(t5),
                "t5_winrate": round((t5 > 0).mean() * 100, 1) if len(t5) else None,
                "t5_avg": round(t5.mean(), 3) if len(t5) else None,
            })
    dashboard = pd.DataFrame(rows).sort_values("trigger_date")
    dashboard.to_csv(output_dir / "performance_dashboard.csv", index=False)
    return dashboard


def write_report(dashboard: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Post-Market Quant Report",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"Dashboard rows: {len(dashboard)}",
        "",
        "## Per-day performance",
        "",
    ]
    if not dashboard.empty:
        try:
            lines.append(dashboard.to_markdown(index=False))
        except Exception:
            lines.extend(dashboard.to_string(index=False).split("\n"))
    today_str = datetime.now().strftime("%Y%m%d")
    (output_dir / f"daily_report_{today_str}.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[report] {output_dir / f'daily_report_{today_str}.md'}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                        help="analysis/trigger date, YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--run-pipeline", action="store_true", help="run run_pipeline_rerun.py first")
    parser.add_argument("--strategy", default="momentum", choices=["momentum", "swing"])
    parser.add_argument("--glob", default="agents_workspace/results/trade_decisions/*.json")
    args = parser.parse_args()

    if args.run_pipeline:
        rc = run_cmd([
            sys.executable, "scripts/run_pipeline_rerun.py",
            "--strategy", args.strategy,
            "--trigger-time", f"{args.date} 20:00:00",
            "--concurrency", "4",
        ])
        if rc != 0:
            print("[error] pipeline failed")
        return

    # Run closed-loop evaluator
    rc = run_cmd([
        sys.executable, "scripts/backtest_signal_closed_loop.py",
        "--glob", args.glob, "--parallel", "4",
    ])
    if rc != 0:
        print("[error] closed-loop evaluator failed")
        return

    signal_csv = PROJECT_ROOT / "agents_workspace" / "backtest_results" / "signal_performance.csv"
    output_dir = PROJECT_ROOT / "agents_workspace" / "backtest_results"
    dashboard = build_dashboard(signal_csv, output_dir)
    write_report(dashboard, output_dir)
    print(f"[done] dashboard rows={len(dashboard)}")



if __name__ == "__main__":
    asyncio.run(main())
