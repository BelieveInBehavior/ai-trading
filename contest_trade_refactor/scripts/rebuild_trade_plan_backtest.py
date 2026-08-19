#!/usr/bin/env python3
"""Rebuild trade_decision JSON with candidate-level trade_plan and run real backtest.

Steps:
  1. Read existing agents_workspace/results/trade_decisions/*.json
  2. For buy_signals / best_signals / watchlist / consensus_signals (NOT the huge
     research_signals list), attach a trade_plan using utils.trade_plan_builder.
  3. Write rebuilt files to agents_workspace/trade_plan_backtest/*.json
  4. Run scripts/backtest_signal_closed_loop.py --glob <rebuilt>
  5. Run scripts/portfolio_simulator.py --input <signal_performance.csv>

This creates a true historical backtest that uses per-plan stop/take columns.
"""

from __future__ import annotations

import argparse
import json
import glob as pyglob
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.trade_plan_builder import build_trade_plan


PLAN_GROUPS = ("buy_signals", "best_signals", "watchlist", "consensus_signals")


def attach_plan_to_signals(signals: List[Dict[str, Any]], trade_date: str | None, signal_group: str = "") -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        code = str(sig.get("symbol_code") or "").strip()
        name = str(sig.get("symbol_name") or "").strip()
        # normalize code without exchange suffix for loader
        clean = "".join(ch for ch in code if ch.isdigit())
        if len(clean) >= 6:
            plan = build_trade_plan(clean, symbol_name=name, trade_date=trade_date)
            item = dict(sig)
            item["trade_plan"] = plan
            if plan.get("status") == "ok":
                from utils.trade_plan_builder import evaluate_trade_plan_quality
                quality = evaluate_trade_plan_quality(plan, signal_group=signal_group)
                item.update(quality)
            else:
                item["trade_plan_pass"] = False
                item["trade_plan_reject_reasons"] = [plan.get("error", "plan_unavailable")]
                item["trade_plan_notes"] = []
            out.append(item)
        else:
            out.append(sig)
    return out


def rebuild_file(src: Path, dst: Path) -> Path | None:
    try:
        with open(src, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"[skip] {src.name}: {exc}")
        return None
    if not isinstance(payload, dict):
        return None

    trigger_ts = str(payload.get("trigger_time") or "")
    # Use trigger date as trade date (config already caps K-line at trigger-day)
    trade_date = "".join(ch for ch in trigger_ts if ch.isdigit())[:8] or None

    changed = False
    group_alias = {
        "buy_signals": "buy_passed",
        "best_signals": "buy_passed",
        "watchlist": "watch",
        "consensus_signals": "consensus",
    }
    for grp in PLAN_GROUPS:
        arr = payload.get(grp)
        if isinstance(arr, list):
            payload[grp] = attach_plan_to_signals(arr, trade_date, signal_group=group_alias.get(grp, grp))
            changed = True

    # Note: leave research_signals untouched to avoid generating hundreds of plans.
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return dst


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--glob", default=str(PROJECT_ROOT / "agents_workspace/results/trade_decisions/*.json"))
    parser.add_argument("--out-dir", default=str(PROJECT_ROOT / "agents_workspace/trade_plan_backtest"))
    parser.add_argument("--horizons", default="1,3,5")
    parser.add_argument("--no-portfolio", action="store_true")
    args = parser.parse_args()

    # --- rebuild ---
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rebuilt = []
    candidate_paths = sorted(Path(p) for p in pyglob.glob(args.glob))
    for src in candidate_paths:
        if not src.exists():
            continue
        dst = out_dir / src.name
        result = rebuild_file(src, dst)
        if result:
            rebuilt.append(result)
    print(f"[rebuild] wrote {len(rebuilt)} files to {out_dir}")

    if not rebuilt:
        print("[error] no rebuilt files; abort")
        sys.exit(1)

    # --- backtest closed loop ---
    backtest_cmd = [
        sys.executable, str(PROJECT_ROOT / "scripts/backtest_signal_closed_loop.py"),
        "--glob", str(out_dir / "*.json"),
        "--horizons", args.horizons,
        "--workspace", str(out_dir),
        "--parallel", "6",
    ]
    print("[cmd]", " ".join(backtest_cmd))
    rc = subprocess.run(backtest_cmd, cwd=PROJECT_ROOT)
    if rc.returncode != 0:
        print("[error] backtest_signal_closed_loop failed")
        sys.exit(rc.returncode)

    if args.no_portfolio:
        return

    # --- portfolio simulation ---
    signal_csv = out_dir / "backtest_results/signal_performance.csv"
    if not signal_csv.exists():
        print("[warn] signal_performance.csv not found; skip portfolio")
        return
    sim_cmd = [
        sys.executable, str(PROJECT_ROOT / "scripts/portfolio_simulator.py"),
        "--input", str(signal_csv),
        "--output", str(out_dir / "backtest_results"),
        "--holding-days", "3",
        "--include-watch",
        "--include-consensus",
        "--include-research",
        "--stop-loss-pct", "-5.0",
        "--take-profit-pct", "8.0",
    ]
    print("[cmd]", " ".join(sim_cmd))
    rc2 = subprocess.run(sim_cmd, cwd=PROJECT_ROOT)
    if rc2.returncode != 0:
        print("[error] portfolio_simulator failed")
        sys.exit(rc2.returncode)


if __name__ == "__main__":
    main()
