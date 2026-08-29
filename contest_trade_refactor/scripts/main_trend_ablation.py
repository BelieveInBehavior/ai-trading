#!/usr/bin/env python3
"""Run main_trend ablation studies for short-sprint 1~5 day research.

Variants:
  1) baseline_core   : no market sentiment, no hot money
  2) plus_sentiment  : market sentiment on, hot money off
  3) plus_hot_money  : market sentiment off, hot money on
  4) full_stack      : market sentiment on, hot money on
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.main_trend_event_backtest import (
    MainTrendEventBacktest,
    _apply_factor_overrides,
    compact,
    trade_dates_between,
    write_json,
)
from strategies.main_trend.engine import MainTrendConfig, MainTrendEngine


VARIANTS = [
    {"tag": "baseline_core", "sentiment": False, "hot_money": False},
    {"tag": "plus_sentiment", "sentiment": True, "hot_money": False},
    {"tag": "plus_hot_money", "sentiment": False, "hot_money": True},
    {"tag": "full_stack", "sentiment": True, "hot_money": True},
]


def _summary_row(summary: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tag": summary.get("ablation_tag"),
        "ma_mode": summary.get("ma_mode"),
        "market_sentiment_enabled": summary.get("market_sentiment_enabled"),
        "hot_money_enabled": summary.get("hot_money_enabled"),
        "trades_total": summary.get("trades_total"),
        "closed_total": summary.get("closed_total"),
        "avg_return_pct": summary.get("avg_return_pct"),
        "win_rate_pct": summary.get("win_rate_pct"),
        "profit_factor": summary.get("profit_factor"),
        "total_return_pct": summary.get("total_return_pct"),
        "reduce_signals": summary.get("reduce_signals"),
        "buy_limit_rejects": summary.get("v2_buy_limit_rejects"),
    }


async def _run_variant(
    *,
    start: str,
    end: str,
    output_root: Path,
    symbols_limit: int,
    concurrency: int,
    exit_mode: str,
    hold_days: int,
    max_holding_days: int,
    max_opens_per_day: int,
    max_open_positions: int,
    risk_fill_mode: str,
    gap_slippage_bps: float,
    ma_mode: str,
    variant: Dict[str, Any],
) -> Dict[str, Any]:
    cfg = _apply_factor_overrides(
        MainTrendConfig.from_yaml(),
        enable_market_sentiment=bool(variant["sentiment"]),
        enable_hot_money=bool(variant["hot_money"]),
        ablation_tag=str(variant["tag"]),
    )
    engine = MainTrendEngine(cfg)
    engine.config.execution["use_tencent_realtime"] = False
    engine.config.technical = dict(engine.config.technical or {})
    engine.config.technical["ma_mode"] = ma_mode
    dates = trade_dates_between(start, end)
    bt = MainTrendEventBacktest(
        engine=engine,
        dates=dates,
        output_root=output_root / str(variant["tag"]),
        symbols_limit=symbols_limit,
        concurrency=concurrency,
        exit_mode=exit_mode,
        hold_days=hold_days,
        max_holding_days=max_holding_days,
        max_opens_per_day=max_opens_per_day,
        max_open_positions=max_open_positions,
        risk_fill_mode=risk_fill_mode,
        gap_slippage_bps=gap_slippage_bps,
    )
    return await bt.run()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", default="")
    parser.add_argument("--output-dir", default="agents_workspace_main_trend_ablation")
    parser.add_argument("--symbols-limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--exit-mode", default="state_machine", choices=["state_machine", "hold", "forward"])
    parser.add_argument("--hold-days", type=int, default=5)
    parser.add_argument("--max-holding-days", type=int, default=5)
    parser.add_argument("--max-opens-per-day", type=int, default=5)
    parser.add_argument("--max-open-positions", type=int, default=20)
    parser.add_argument("--risk-fill-mode", default="vwap", choices=["vwap", "open", "close"])
    parser.add_argument("--gap-slippage-bps", type=float, default=20.0)
    parser.add_argument("--ma-mode", default="ema", choices=["sma", "ema"])
    return parser


async def _main_async(args: argparse.Namespace) -> Dict[str, Any]:
    start = compact(args.start)
    end = compact(args.end or args.start)
    output_root = Path(args.output_dir).expanduser().resolve()
    rows: List[Dict[str, Any]] = []
    full: Dict[str, Any] = {
        "start": start,
        "end": end,
        "ma_mode": args.ma_mode,
        "variants": [],
    }
    for variant in VARIANTS:
        summary = await _run_variant(
            start=start,
            end=end,
            output_root=output_root,
            symbols_limit=args.symbols_limit,
            concurrency=args.concurrency,
            exit_mode=args.exit_mode,
            hold_days=args.hold_days,
            max_holding_days=args.max_holding_days,
            max_opens_per_day=args.max_opens_per_day,
            max_open_positions=args.max_open_positions,
            risk_fill_mode=args.risk_fill_mode,
            gap_slippage_bps=args.gap_slippage_bps,
            ma_mode=args.ma_mode,
            variant=variant,
        )
        rows.append(_summary_row(summary))
        full["variants"].append(summary)

    full["summary_rows"] = rows
    write_json(output_root / "ablation_summary.json", full)
    return full


def main() -> None:
    args = build_parser().parse_args()
    payload = asyncio.run(_main_async(args))
    print(json.dumps(payload["summary_rows"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
