#!/usr/bin/env python3
"""Validate the 'crowding/entry-quality' hypothesis from an existing no-future replay.

Reads:
  - <replay>/backtest_results/signal_performance.csv  (trigger_date, symbol_code, t3, t5)
  - <replay>/<YYYYMMDD>/results/trade_decisions/*.json  (technical_factor / quantitative_candidates)

Builds a fresh sector snapshot (sector_3d/5d/10d) from agents_workspace/factor_store/sector_fund_flow
honoring each trigger_date as as-of date (no future), joins to the signal, then buckets:
  stock_5d x sector_5d x T+5 (and T+3)
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.sector_enrichment import (
    build_code_sector_snapshot,
    build_sector_snapshot_from_factor_store,
    load_industry_map,
)


def _compact(dt: str) -> str:
    return "".join(ch for ch in str(dt) if ch.isdigit())[:8]


def _norm_code(code):
    return "".join(ch for ch in str(code or "").upper() if ch.isdigit())[:6]


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_signal_perf(replay_dir: Path) -> pd.DataFrame:
    p = replay_dir / "backtest_results" / "signal_performance.csv"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def load_technical_lookup(replay_dir: Path) -> dict:
    out = {}
    files = glob.glob(str(replay_dir / "*" / "results" / "trade_decisions" / "*.json"))
    if not files:
        files = glob.glob(str(replay_dir / "*.json"))
    for fp in files:
        try:
            d = json.loads(Path(fp).read_text(encoding="utf-8"))
        except Exception:
            continue
        trigger = str(d.get("trigger_time") or "")
        date = _compact(trigger)
        sigs = (
            d.get("buy_signals")
            or d.get("research_signals")
            or d.get("watch_signals")
            or d.get("consensus_signals")
            or []
        )
        for sig in sigs:
            if not isinstance(sig, dict):
                continue
            tf = sig.get("technical_factor") or {}
            code = str(sig.get("symbol_code") or tf.get("symbol_code") or "").upper()
            if not code:
                continue
            out[(_norm_code(code), date)] = tf
            out[(code, date)] = tf
    return out


def build_panel(replay_dir: Path) -> pd.DataFrame:
    perf = load_signal_perf(replay_dir)
    if perf.empty:
        print("No signal_performance.csv found in", replay_dir)
        return pd.DataFrame()
    tech = load_technical_lookup(replay_dir)
    industry_map = load_industry_map()
    rows = []
    for _, r in perf.iterrows():
        raw_code = str(r.get("symbol_code") or "").strip().upper()
        code = _norm_code(raw_code)
        trigger = str(r.get("trigger_time") or r.get("trigger_date") or "")
        date = _compact(trigger)
        tf = tech.get((code, date)) or tech.get((raw_code, date)) or {}
        snap = {}
        try:
            by_name = build_sector_snapshot_from_factor_store(trade_date=date)
            snap_dict = build_code_sector_snapshot(industry_map, by_name, trade_date=date)
            snap = snap_dict.get(code) or snap_dict.get(raw_code) or {}
        except Exception:
            pass
        stock5 = _float(tf.get("ret_5d_pct"))
        sector5 = _float(tf.get("sector_5d_return") or snap.get("sector_5d_return"))
        sector3 = _float(tf.get("sector_3d_return") or snap.get("sector_3d_return"))
        sector10 = _float(tf.get("sector_10d_return") or snap.get("sector_10d_return"))
        rows.append({
            "trigger_date": date,
            "symbol_code": code,
            "signal_group": r.get("signal_group"),
            "buy_score": r.get("buy_score"),
            "ret_5d_pct": stock5,
            "sector_3d": sector3,
            "sector_5d": sector5,
            "sector_10d": sector10,
            "t1_return_pct": r.get("t1_return_pct"),
            "t3_return_pct": r.get("t3_return_pct"),
            "t5_return_pct": r.get("t5_return_pct"),
        })
    return pd.DataFrame(rows)


def bucket_stock5(v):
    if v is None:
        return "NA"
    if v < 8:
        return "<8"
    if v < 15:
        return "8~15"
    if v < 25:
        return "15~25"
    return ">25"


def bucket_sector5(v):
    if v is None:
        return "NA"
    if v < 3:
        return "<3"
    if v < 8:
        return "3~8"
    if v < 15:
        return "8~15"
    return ">15"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    replay = Path(args.replay_dir)
    df = build_panel(replay)
    if df.empty:
        print("no data")
        return
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print("wrote", out_path, "rows", len(df))

    df["stock_bucket"] = df["ret_5d_pct"].apply(bucket_stock5)
    df["sector_bucket"] = df["sector_5d"].apply(bucket_sector5)
    print("\n=== stock_5d x T5 ===")
    print(df.groupby("stock_bucket")["t5_return_pct"].agg(["count","mean","median"]).to_string())
    print("\n=== sector_5d x T5 ===")
    print(df.groupby("sector_bucket")["t5_return_pct"].agg(["count","mean","median"]).to_string())
    print("\n=== stock x sector x T5 ===")
    print(df.pivot_table(index="stock_bucket", columns="sector_bucket", values="t5_return_pct", aggfunc=["count","mean"]).to_string())


if __name__ == "__main__":
    main()
