"""Run full trade company pipeline with pragmatic defaults for local rerun."""
from __future__ import annotations

import argparse
import asyncio
import traceback
from datetime import datetime

from config.strategies import get_strategy, STRATEGY_NAMES
from main_loop import SimpleTradeCompany


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=list(STRATEGY_NAMES), default="momentum")
    parser.add_argument("--trigger-time", default="")
    parser.add_argument("--symbols-limit", type=int, default=0,
                        help="If >0, restrict Stage 0 screener to first N symbols (validation only).")
    parser.add_argument("--concurrency", type=int, default=4,
                        help="Stage 0 screener concurrency.")
    args = parser.parse_args()

    company = SimpleTradeCompany(strategy=args.strategy)
    # 全市场预筛：max_symbols=0 扫描全部 A 股（约 5000+），配置见 config.yaml
    company.quantitative_screener.config.enabled = True
    company.quantitative_screener.config.max_symbols = args.symbols_limit
    # 降低并发，避免 AkShare/Yahoo fallback 触发限流
    company.quantitative_screener.config.max_concurrency = args.concurrency
    trigger_time = args.trigger_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    strategy_cfg = get_strategy(args.strategy)
    print(
        f"pipeline_start strategy={strategy_cfg.get('id')} trigger_time={trigger_time} "
        f"quantitative_screen=on max_symbols={company.quantitative_screener.config.max_symbols} "
        f"concurrency={company.quantitative_screener.config.max_concurrency}",
        flush=True,
    )
    try:
        result = await company.run(trigger_time)
    except Exception:
        traceback.print_exc()
        raise
    print("pipeline_done", flush=True)
    print(f"strategy={strategy_cfg.get('id')}", flush=True)
    print(f"data_factors={len(result.get('data_factors') or [])}", flush=True)
    print(f"research_signals={len(result.get('research_signals') or [])}", flush=True)
    print(f"best_signals={len(result.get('best_signals') or [])}", flush=True)
    print(f"research_rounds={result.get('research_rounds')}", flush=True)
    print(f"require_min_buys_met={result.get('require_min_buys_met')}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
