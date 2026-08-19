#!/usr/bin/env python3
"""Offline rescore replay signals with the new entry-quality/crowding penalty.

Reads existing no-future replay trade_decision JSONs, refreshes sector multi-day
snapshots with as-of dates, then invokes StockOpportunityRanker._score_entry_quality
on each signal and reports old buy_score, new buy_score, delta.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from agents.stock_opportunity_ranker import StockOpportunityRanker
from utils.sector_enrichment import (
    build_code_sector_snapshot,
    build_sector_snapshot_from_factor_store,
    enrich_factor_with_sector,
    load_industry_map,
)


def _compact(dt: str) -> str:
    return "".join(ch for ch in str(dt) if ch.isdigit())[:8]


def _tech_with_refreshed_sector(sig: dict, date: str) -> dict:
    tf = dict(sig.get("technical_factor") or {})
    industry_map = load_industry_map()
    try:
        by_name = build_sector_snapshot_from_factor_store(trade_date=date)
        code_snap = build_code_sector_snapshot(industry_map, by_name, trade_date=date)
        tf = enrich_factor_with_sector(tf, code_snap or {})
    except Exception:
        pass
    return tf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    replay = Path(args.replay_dir)
    files = glob.glob(str(replay / "*" / "results" / "trade_decisions" / "*.json"))
    if not files:
        files = glob.glob(str(replay / "*.json"))
    ranker = StockOpportunityRanker()
    rows = []
    for fp in files:
        d = json.loads(Path(fp).read_text(encoding="utf-8"))
        trigger = d.get("trigger_time") or ""
        date = _compact(trigger)
        sigs = d.get("buy_signals") or d.get("research_signals") or []
        lookup = {}
        for s2 in (d.get("buy_signals") or []):
            lookup[s2.get("symbol_code")] = s2
        for sig in sigs:
            sig = lookup.get(sig.get("symbol_code"), sig)
            sig = _tech_normed_signal(sig, date)
            old = float(sig.get("buy_score") or 0)
            # entry score new
            sm = ranker._score_short_setup(sig)[0]
            vm = ranker._score_volume_amount(sig)[0]
            ss = ranker._score_sector_strength(sig)[0]
            cat = ranker._score_catalyst_strength(sig.get("evidence_list") or [], trigger)[0]
            delta, reason, report = ranker._score_entry_quality(sig, sm, vm, ss, cat)
            new = max(0.0, min(99.5, old + delta))
            rows.append({
                "trigger_time": trigger,
                "symbol_code": sig.get("symbol_code"),
                "symbol_name": sig.get("symbol_name"),
                "old_buy_score": old,
                "entry_delta": round(delta,2),
                "new_buy_score": round(new,2),
                "entry_quality_score": report.get("entry_quality_score"),
                "crowding_score": report.get("crowding_score"),
                "reason": reason,
            })
    df = pd.DataFrame(rows)
    if df.empty:
        print("no rows")
        return
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print("wrote", out, "rows", len(df))
    print(df.sort_values("entry_delta").head(15).to_string(index=False))


def _tech_normed_signal(sig, date):
    """Return a shallow signal copy with technical_factor refreshed sector fields."""
    tf = dict(sig.get("technical_factor") or {})
    industry_map = load_industry_map()
    try:
        by_name = build_sector_snapshot_from_factor_store(trade_date=date)
        code_snap = build_code_sector_snapshot(industry_map, by_name, trade_date=date)
        tf = enrich_factor_with_sector(tf, code_snap or {})
    except Exception:
        pass
    sig2 = dict(sig)
    sig2["technical_factor"] = tf
    return sig2


if __name__ == "__main__":
    main()
