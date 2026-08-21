#!/usr/bin/env python3
"""First Board Continue 首板延续独立策略回测/单日运行入口。

用法:
  # 单日
  .venv/bin/python scripts/first_board_continue_backtest.py --date 2026-08-18 --output-dir run_fbc

  # 多日回放
  .venv/bin/python scripts/first_board_continue_backtest.py --start 2026-08-11 --end 2026-08-18 \
      --symbols-limit 200 --output-dir agents_workspace_first_board_continue
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

from strategies.first_board_continue.engine import FirstBoardContinueConfig, FirstBoardContinueEngine


def _compact(value: str) -> str:
    return str(value or "").strip().replace("-", "").replace("/", "")


def _resolve_dates(start: str, end: str):
    from utils.market_manager import GLOBAL_MARKET_MANAGER
    dates = [str(d).replace("-", "").replace("/", "") for d in GLOBAL_MARKET_MANAGER.get_trade_date(market_name="CN-Stock")]
    return [d for d in sorted(dates) if _compact(start) <= d <= _compact(end)]


async def run_day(engine, date_compact: str, output_dir: Path, symbols_limit: int, prev_watchlist=None) -> dict:
    trigger = f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:8]} 18:00:00"
    day_dir = output_dir / date_compact
    result = await engine.run_day(
        trigger_time=trigger,
        watchlist=prev_watchlist,
        max_symbols=symbols_limit,
        output_dir=str(day_dir),
    )
    return {
        "date": date_compact,
        "output": str(day_dir / "result.json"),
        "buy_ready": sum(1 for b in result.get("buy_signals", []) if b["buy_ready"]),
        "_watch_items": result.get("watchlist", []),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--output-dir", default="agents_workspace_first_board_continue")
    parser.add_argument("--symbols-limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    cfg = FirstBoardContinueConfig.from_yaml()
    cfg.quantitative_concurrency = max(1, args.concurrency)
    engine = FirstBoardContinueEngine(cfg)
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
        print(f"[first_board_continue] running {date} ...", flush=True)
        old_asof = os.environ.get("CONTEST_TRADE_ASOF_DATE", "")
        os.environ["CONTEST_TRADE_ASOF_DATE"] = date
        try:
            summary = await run_day(engine, date, output_dir, args.symbols_limit, prev_watchlist=prev_items)
        except Exception as exc:
            print(f"[first_board_continue] error {date}: {exc}", file=sys.stderr)
            continue
        finally:
            if old_asof:
                os.environ["CONTEST_TRADE_ASOF_DATE"] = old_asof
            else:
                os.environ.pop("CONTEST_TRADE_ASOF_DATE", None)
        prev_items = summary.get("_watch_items") or []
        print(json.dumps({k: v for k, v in summary.items() if not k.startswith("_")}, ensure_ascii=False), flush=True)
        (output_dir / "manifest.jsonl").open("a", encoding="utf-8").write(
            json.dumps({k: v for k, v in summary.items() if not k.startswith("_")}, ensure_ascii=False) + "\n"
        )


if __name__ == "__main__":
    asyncio.run(main())
