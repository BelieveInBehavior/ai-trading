#!/usr/bin/env python3
"""Main Trend Following Engine 主升浪趋势跟踪系统独立回测/单日运行入口。

用法:
  # 单日
  .venv/bin/python scripts/main_trend_backtest.py --date 2026-08-18 --output-dir run_main_trend

  # 多日回放（不偷看未来）
  .venv/bin/python scripts/main_trend_backtest.py --start 2026-06-01 --end 2026-08-18 \\
      --symbols-limit 200 --output-dir agents_workspace_main_trend
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from strategies.main_trend.engine import MainTrendConfig, MainTrendEngine
from strategies.main_trend.schemas import Holding, MTFCandidate


def _compact(value: str) -> str:
    return str(value or "").strip().replace("-", "").replace("/", "")


def _resolve_dates(start: str, end: str):
    from utils.market_manager import GLOBAL_MARKET_MANAGER
    dates = [str(d).replace("-", "").replace("/", "") for d in GLOBAL_MARKET_MANAGER.get_trade_date(market_name="CN-Stock")]
    return [d for d in sorted(dates) if _compact(start) <= d <= _compact(end)]


async def run_day(engine, date_compact: str, output_dir: Path, symbols_limit: int, prev_candidates=None) -> dict:
    trigger = f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:8]} 18:00:00"
    day_dir = output_dir / date_compact
    result = await engine.run_day(
        trigger_time=trigger,
        watchlist=prev_candidates,
        max_symbols=symbols_limit,
        output_dir=str(day_dir),
    )
    discovery = result.get("discovery") or {}
    buy_signals = result.get("buy_signals") or []
    return {
        "date": date_compact,
        "output": str(day_dir / "result.json"),
        "eligible": len(discovery.get("eligible") or []),
        "candidates": len(discovery.get("candidates") or []),
        "market_regime": (discovery.get("market_regime") or {}).get("regime"),
        "buy_ready": sum(1 for s in buy_signals if s.get("buy_ready")),
        "_candidates": discovery.get("eligible") or [],
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--output-dir", default="agents_workspace_main_trend")
    parser.add_argument("--symbols-limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    cfg = MainTrendConfig.from_yaml()
    cfg.quantitative_concurrency = max(1, args.concurrency)
    engine = MainTrendEngine(cfg)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.date:
        dates = [_compact(args.date)]
    elif args.start:
        end = args.end or args.start
        dates = _resolve_dates(args.start, end)
    else:
        print("--date or --start required", file=sys.stderr)
        sys.exit(2)

    prev_items = []
    for date in dates:
        print(f"[main_trend] running {date} ...", flush=True)
        old_asof = os.environ.get("CONTEST_TRADE_ASOF_DATE", "")
        os.environ["CONTEST_TRADE_ASOF_DATE"] = date
        try:
            summary = await run_day(engine, date, output_dir, args.symbols_limit, prev_items)
        except Exception as exc:
            print(f"[main_trend] error {date}: {exc}", file=sys.stderr)
            continue
        finally:
            if old_asof:
                os.environ["CONTEST_TRADE_ASOF_DATE"] = old_asof
            else:
                os.environ.pop("CONTEST_TRADE_ASOF_DATE", None)
        prev_items = summary.get("_candidates") or []
        print(json.dumps({k: v for k, v in summary.items() if not k.startswith("_")}, ensure_ascii=False), flush=True)
        (output_dir / "manifest.jsonl").open("a", encoding="utf-8").write(
            json.dumps({k: v for k, v in summary.items() if not k.startswith("_")}, ensure_ascii=False) + "\n"
        )


if __name__ == "__main__":
    asyncio.run(main())
