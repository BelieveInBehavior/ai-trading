#!/usr/bin/env python3
"""CLI: generate candidate-level 1-5 day trade plans for a list of symbols.

Examples:
  .venv/bin/python scripts/build_trade_plan.py 600519 300502 000001
  .venv/bin/python scripts/build_trade_plan.py --date 20260814 --risk-budget 1.0 600519
  printf '600519\n300502\n' | .venv/bin/python scripts/build_trade_plan.py --stdin
  .venv/bin/python scripts/build_trade_plan.py --file candidates.csv

Outputs:
  - stdout text summary
  - if --out JSON path, structured JSON with per-symbol plans
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.trade_plan_builder import build_trade_plan, format_trade_plan_markdown
from utils.date_utils import get_latest_completed_trading_date


def parse_symbols(args) -> list[str]:
    symbols: list[str] = []
    if args.codes:
        for code in args.codes:
            symbols.extend(code.replace(",", " ").split())
    if args.stdin:
        for line in sys.stdin:
            code = line.strip()
            if code:
                symbols.append(code)
    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"[error] file not found: {path}", file=sys.stderr)
            sys.exit(2)
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                code = line.strip()
                if code:
                    symbols.append(code)
    return symbols


def main() -> None:
    parser = argparse.ArgumentParser(description="Build 1-5 day trade plans for candidate symbols")
    parser.add_argument("codes", nargs="*", help="Stock codes, e.g. 600519 300502")
    parser.add_argument("--date", default=None, help="Analysis/trade date YYYYMMDD; default latest completed trading day")
    parser.add_argument("--risk-budget", type=float, default=1.0, help="Per-trade risk budget in %% of capital")
    parser.add_argument("--stdin", action="store_true", help="Read codes from stdin, one per line")
    parser.add_argument("--file", default=None, help="Read codes from a text/CSV file")
    parser.add_argument("--out", default=None, help="Optional JSON output path")
    args = parser.parse_args()

    symbols = parse_symbols(args)
    if not symbols:
        print("[error] no symbols provided", file=sys.stderr)
        parser.print_help(sys.stderr)
        sys.exit(2)

    trade_date = args.date or get_latest_completed_trading_date()
    print(f"Trade date: {trade_date}")
    plans = []
    for code in symbols:
        plan = build_trade_plan(code, trade_date=trade_date, risk_budget_pct=args.risk_budget)
        from utils.trade_plan_builder import evaluate_trade_plan_quality
        quality = evaluate_trade_plan_quality(plan)
        plan.update(quality)
        plans.append(plan)
        verdict = "PASS" if quality.get("trade_plan_pass") else "FAIL"
        print(f"{code}: [{verdict}] {quality.get('trade_plan_reject_reasons') or quality.get('trade_plan_notes') or 'ok'}")
        print(f"      {format_trade_plan_markdown(plan)}")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"trade_date": trade_date, "plans": plans}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[wrote] {out_path}")


if __name__ == "__main__":
    main()
