#!/usr/bin/env python3
"""Strong Diverge 独立策略回测/单日运行入口（不依赖旧 main_loop）。

用法:
  # 单日运行（只输出当日决策和 JSON）
  .venv/bin/python scripts/strong_diverge_backtest.py --date 2026-08-18 --output-dir run_strong_diverge

  # 多日回放（对每天独立运行，不做未来数据）
  .venv/bin/python scripts/strong_diverge_backtest.py --start 2026-08-11 --end 2026-08-18 \
      --symbols-limit 30 --output-dir agents_workspace_strong_diverge
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

from strategies.strong_diverge.engine import StrongDivergeConfig, StrongDivergeEngine
from strategies.strong_diverge.schemas import Holding, WatchlistItem


def _compact(value: str) -> str:
    return str(value or "").strip().replace("-", "").replace("/", "")


def _resolve_dates(start: str, end: str):
    from utils.market_manager import GLOBAL_MARKET_MANAGER
    dates = [str(d).replace("-", "").replace("/", "") for d in GLOBAL_MARKET_MANAGER.get_trade_date(market_name="CN-Stock")]
    return [d for d in sorted(dates) if _compact(start) <= d <= _compact(end)]


async def run_day(
    engine: StrongDivergeEngine,
    date_compact: str,
    output_dir: Path,
    symbols_limit: int,
    prev_watchlist=None,
) -> dict:
    from strategies.strong_diverge.schemas import Holding
    trigger = f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:8]} 18:00:00"
    day_dir = output_dir / date_compact
    result = await engine.run_day(
        trigger_time=trigger,
        watchlist=prev_watchlist,
        max_symbols=symbols_limit,
        output_dir=str(day_dir),
    )
    discovery = result.get('discovery')
    candidate_count = (
        len(discovery.all_candidates)
        if hasattr(discovery, 'all_candidates') else 0
    )
    market_temp = (
        discovery.market_temperature
        if hasattr(discovery, 'market_temperature') else {}
    )
    watch_pool = result.get('watchlist')
    watch_count = (
        len(watch_pool.all_items)
        if hasattr(watch_pool, 'all_items') else (
            len(watch_pool) if isinstance(watch_pool, (list, tuple)) else 0
        )
    )
    return {
        "date": date_compact,
        "candidates": candidate_count,
        "watchlist": watch_count,
        "divergence": sum(1 for s in result.get("divergence_signals", []) if getattr(s, "divergence_event", False)),
        "buy_ready": sum(1 for b in result.get("buy_signals", []) if b.buy_ready),
        "market_temperature": market_temp.get("temperature"),
        "market_passed": market_temp.get("passed"),
        "limit_up_count": market_temp.get("limit_up_count"),
        "max_board": market_temp.get("max_board"),
        "output": str(day_dir / "result.json"),
        "_watch_items": list(result.get("watchlist").all_items) if hasattr(result.get("watchlist"), "all_items") else [],
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="", help="single date YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--output-dir", default="agents_workspace_strong_diverge")
    parser.add_argument("--symbols-limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--disable-market-gate", action="store_true", help="诊断：忽略市场情绪温度闸门，用于验证 T+1 弱转强链路")
    args = parser.parse_args()

    cfg = StrongDivergeConfig.from_yaml()
    cfg.quantitative_concurrency = max(1, args.concurrency)
    if getattr(args, "disable_market_gate", False):
        market_cfg = dict(cfg.market or {})
        market_cfg["enabled"] = False
        cfg.market = market_cfg
    engine = StrongDivergeEngine(cfg)
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
        print(f"[strong_diverge] running {date} ...", flush=True)
        old_asof = os.environ.get("CONTEST_TRADE_ASOF_DATE", "")
        # 防未来数据：每次回放都强制价格/K线在当天结束，不能看到 date 之后的数据。
        os.environ["CONTEST_TRADE_ASOF_DATE"] = date
        try:
            summary = await run_day(engine, date, output_dir, args.symbols_limit, prev_watchlist=prev_items)
        except Exception as exc:
            print(f"[strong_diverge] error {date}: {exc}", file=sys.stderr)
            continue
        finally:
            if old_asof:
                os.environ["CONTEST_TRADE_ASOF_DATE"] = old_asof
            else:
                os.environ.pop("CONTEST_TRADE_ASOF_DATE", None)
        prev_items = summary.get("_watch_items") or []
        print(json.dumps({k:v for k,v in summary.items() if not k.startswith('_')}, ensure_ascii=False), flush=True)
        (output_dir / "manifest.jsonl").open("a", encoding="utf-8").write(
            json.dumps({k:v for k,v in summary.items() if not k.startswith('_')}, ensure_ascii=False) + "\n"
        )


if __name__ == "__main__":
    asyncio.run(main())
