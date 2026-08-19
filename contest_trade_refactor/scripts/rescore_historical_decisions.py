#!/usr/bin/env python3
"""Re-score historical decision JSON files with the current ranking stack.

This script is intentionally deterministic: it reuses the original
research_signals, market_context and system_health from each historical run,
then applies the current StockOpportunityRanker, SignalTierClassifier and
MarketRegimeDetector. It writes a new replay-like directory and never mutates
the source decisions.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]

import sys

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.market_regime_detector import MarketRegimeDetector
from config.strategies import get_strategy
from agents.signal_tier_classifier import SignalTierClassifier
from agents.stock_opportunity_ranker import RankerConfig, StockOpportunityRanker


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _index_df(market_context: Dict[str, Any]) -> pd.DataFrame | None:
    snapshot = (market_context or {}).get("index_snapshot") or {}
    rows = snapshot.get("market_index_df") or []
    if not rows:
        return None
    return pd.DataFrame(rows)


def _signal_key(signal: Dict[str, Any]) -> str:
    return str(signal.get("symbol_code") or signal.get("symbol") or signal.get("symbol_name") or "").strip()


def rescore_payload(
    payload: Dict[str, Any],
    source_path: Path,
    ranker: StockOpportunityRanker,
    tier_classifier: SignalTierClassifier,
    regime_detector: MarketRegimeDetector,
    watchlist_size: int,
) -> Dict[str, Any]:
    trigger_time = str(payload.get("trigger_time") or "")
    research_signals: List[Dict[str, Any]] = list(payload.get("research_signals") or [])
    market_context = payload.get("market_context") or {}
    system_health = payload.get("system_health") or {}

    regime, regime_confidence, regime_reasons = regime_detector.detect(
        market_context=market_context,
        index_data=_index_df(market_context),
    )

    ranked = ranker.rank_signals(
        research_signals=research_signals,
        trigger_time=trigger_time,
        market_context=market_context,
        system_health=system_health,
    )
    signal_tiers = tier_classifier.classify(ranked, market_regime=regime)
    buy_signals = signal_tiers.get("tier_A", []) + signal_tiers.get("tier_B", [])

    watchlist = ranker.build_watchlist(
        research_signals=research_signals,
        trigger_time=trigger_time,
        market_context=market_context,
        system_health=system_health,
        top_k=watchlist_size,
    )
    buy_keys = {_signal_key(signal) for signal in buy_signals}
    watchlist = [
        signal for signal in watchlist
        if _signal_key(signal) not in buy_keys and str(signal.get("buy_decision") or "").lower() != "buy"
    ]
    seen_watch = {_signal_key(signal) for signal in watchlist}
    for signal in signal_tiers.get("tier_C", []):
        key = _signal_key(signal)
        if key and key not in buy_keys and key not in seen_watch:
            watchlist.append(signal)
            seen_watch.add(key)

    original_logic_version = payload.get("logic_version")
    if isinstance(original_logic_version, dict):
        logic_version = dict(original_logic_version)
        logic_version["rescore"] = "forward_opportunity_rescore_v1"
    else:
        logic_version = original_logic_version

    rescored = dict(payload)
    rescored.update(
        {
            "buy_signals": buy_signals,
            "best_signals": buy_signals,
            "watchlist": watchlist[:watchlist_size],
            "consensus_signals": research_signals,
            "market_regime": regime,
            "regime_confidence": regime_confidence,
            "regime_reasons": regime_reasons,
            "signal_tiers": signal_tiers,
            "logic_version": logic_version,
            "rescore_logic_version": "forward_opportunity_rescore_v1",
            "require_min_buys_met": True,
            "rescore_metadata": {
                "source_file": str(source_path),
                "rescored_at": datetime.now().isoformat(timespec="seconds"),
                "ranker": "StockOpportunityRanker",
                "tier_classifier": "SignalTierClassifier",
                "market_regime_detector": "MarketRegimeDetector",
                "original_counts": {
                    "research_signals": len(research_signals),
                    "buy_signals": len(payload.get("buy_signals") or []),
                    "watchlist": len(payload.get("watchlist") or []),
                },
                "rescored_counts": {
                    "research_signals": len(research_signals),
                    "buy_signals": len(buy_signals),
                    "watchlist": len(watchlist[:watchlist_size]),
                    "tier_A": len(signal_tiers.get("tier_A", [])),
                    "tier_B": len(signal_tiers.get("tier_B", [])),
                    "tier_C": len(signal_tiers.get("tier_C", [])),
                    "tier_reject": len(signal_tiers.get("tier_reject", [])),
                },
            },
        }
    )
    return rescored


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-root",
        default=str(PROJECT_ROOT / "agents_workspace_replays" / "historical_pilot_clean"),
    )
    parser.add_argument("--decision-glob", default="*/results/trade_decisions/*.json")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--watchlist-size", type=int, default=8)
    parser.add_argument("--strategy", default="momentum", choices=["momentum", "swing"])
    args = parser.parse_args()

    strategy_cfg = get_strategy(args.strategy)
    over = strategy_cfg.get("ranker_overrides") or {}
    def _f(key, default):
        v = over.get(key)
        return default if v is None else float(v)
    def _b(key, default):
        v = over.get(key)
        return default if v is None else bool(v)

    _ranker_config = RankerConfig(
        min_buy_score=_f("min_buy_score", 60.0),
        min_probability=_f("min_probability", 0.55),
        min_tradeability_score=_f("min_tradeability_score", 55.0),
        min_risk_reward_score=_f("min_risk_reward_score", 50.0),
        min_data_quality_score=_f("min_data_quality_score", 45.0),
        min_technical_score=_f("min_technical_score", 45.0),
        max_prev_day_gain_pct=_f("max_prev_day_gain_pct", 6.0),
        max_ma20_deviation_pct=_f("max_ma20_deviation_pct", 8.0),
        min_flow_confirmation_score=_f("min_flow_confirmation_score", 55.0),
        min_regime_confirmation_score=_f("min_regime_confirmation_score", 52.0),
        enforce_flow_confirmation_if_available=_b("enforce_flow_confirmation_if_available", True),
        enforce_multi_timeframe=_b("enforce_multi_timeframe", False),
        expected_return_floor_pct=_f("expected_return_floor_pct", 0.3),
        strong_trend_penalty_bias=_f("strong_trend_penalty_bias", 0.0),
        reject_future_evidence=True,
        risk_veto_enabled=True,
    )

    input_root = Path(args.input_root)
    if args.output_root:
        output_root = Path(args.output_root)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_root = PROJECT_ROOT / "agents_workspace_replays" / f"historical_pilot_clean_rescored_{stamp}"

    decision_paths = sorted(input_root.glob(args.decision_glob))
    ranker = StockOpportunityRanker(_ranker_config)
    tier_classifier = SignalTierClassifier()
    regime_detector = MarketRegimeDetector()

    summary_rows = []
    for source_path in decision_paths:
        payload = _load_json(source_path)
        rescored = rescore_payload(
            payload=payload,
            source_path=source_path,
            ranker=ranker,
            tier_classifier=tier_classifier,
            regime_detector=regime_detector,
            watchlist_size=args.watchlist_size,
        )
        rel_path = source_path.relative_to(input_root)
        output_path = output_root / rel_path
        _write_json(output_path, rescored)

        meta = rescored["rescore_metadata"]
        summary_rows.append(
            {
                "date": rel_path.parts[0] if rel_path.parts else "",
                "source_file": str(source_path),
                "output_file": str(output_path),
                "market_regime": rescored.get("market_regime"),
                **{f"original_{k}": v for k, v in meta["original_counts"].items()},
                **{f"rescored_{k}": v for k, v in meta["rescored_counts"].items()},
            }
        )

    output_root.mkdir(parents=True, exist_ok=True)
    summary_path = output_root / "rescore_summary.csv"
    pd.DataFrame(summary_rows).to_csv(summary_path, index=False)

    print(json.dumps({
        "input_root": str(input_root),
        "output_root": str(output_root),
        "decision_files": len(decision_paths),
        "summary": str(summary_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
