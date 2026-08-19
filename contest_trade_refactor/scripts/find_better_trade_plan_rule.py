#!/usr/bin/env python3
"""Scan candidate trade_plan rules against historical signals.

Reads agents_workspace/trade_plan_backtest/backtest_results/signal_performance.csv
and tries a grid of easy-to-interpret rules. Reports win rate / avg return for each.

WARNING: this is exploratory and tiny-sample. Do not over-fit.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def safe_float(v):
    try:
        if pd.isna(v):
            return None
        return float(v)
    except Exception:
        return None


def parse_boolish(v):
    return str(v).strip().lower() in {"true", "1", "yes"}


def evaluate(df, pred, label, min_n=3):
    mask = pred
    sub = df[mask]
    if len(sub) < min_n:
        return None
    t1 = pd.to_numeric(sub["t1_return_pct"], errors="coerce").dropna()
    if len(t1) == 0:
        return None
    return {
        "rule": label,
        "n": len(t1),
        "winrate": round((t1 > 0).mean() * 100, 1),
        "avg_t1": round(t1.mean(), 3),
        "median_t1": round(t1.median(), 3),
        "sum_t1": round(t1.sum(), 2),
        "avg_max_loss": round(pd.to_numeric(sub["max_drawdown_pct"], errors="coerce").mean(), 3) if "max_drawdown_pct" in sub.columns else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(PROJECT_ROOT / "agents_workspace/trade_plan_backtest/backtest_results/signal_performance.csv"))
    parser.add_argument("--min-n", type=int, default=3)
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    print(f"Loaded {len(df)} rows from {args.input}")
    print(f"Columns with trade_plan: {[c for c in df.columns if 'trade_plan' in c.lower()]}")

    t1 = pd.to_numeric(df["t1_return_pct"], errors="coerce")
    print(f"T1 valid rows: {t1.notna().sum()}")

    results = []

    def add(pred, label):
        r = safe_float_rule(df, pred, label, args.min_n)
        if r:
            results.append(r)

    def safe_float_rule(df, pred, label, min_n):
        sub = df[pred]
        if len(sub) < min_n:
            return None
        t1 = pd.to_numeric(sub["t1_return_pct"], errors="coerce")
        t1 = t1.dropna()
        if len(t1) == 0:
            return None
        max_loss = pd.to_numeric(sub.get("max_drawdown_pct"), errors="coerce").dropna().mean() if "max_drawdown_pct" in sub.columns else None
        return {
            "rule": label,
            "n": int(len(t1)),
            "win_rate": round(float((t1 > 0).mean() * 100), 1),
            "avg_t1": round(float(t1.mean()), 3),
            "median_t1": round(float(t1.median()), 3),
            "sum_t1": round(float(t1.sum()), 3),
            "avg_max_loss": None if max_loss is None or math.isnan(max_loss) else round(float(max_loss), 3),
        }

    rr = pd.to_numeric(df.get("trade_plan_rr_1"), errors="coerce")
    vol = pd.to_numeric(df.get("trade_plan_volume_ratio"), errors="coerce")
    rsi = pd.to_numeric(df.get("trade_plan_rsi"), errors="coerce")
    stop_pct = pd.to_numeric(df.get("trade_plan_stop_loss_pct"), errors="coerce")
    vwap = pd.to_numeric(df.get("trade_plan_vwap20"), errors="coerce")
    close = pd.to_numeric(df.get("entry_price"), errors="coerce")

    # baseline
    add(pd.Series([True] * len(df)), "ALL")

    # RR thresholds
    for thr in [0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0]:
        add(rr >= thr, f"RR>={thr}")

    # Volume ratio
    for lo in [None, 0.8, 1.0, 1.2]:
        if lo is None:
            add(vol.notna(), "VR has value")
        else:
            add(vol >= lo, f"VR>={lo}")

    # RSI range
    add(rsi.between(30, 75), "RSI 30-75")
    add(rsi <= 70, "RSI<=70")
    add(rsi <= 65, "RSI<=65")

    # stop depth
    add(stop_pct >= -5, "stop>=-5%")
    add(stop_pct >= -8, "stop>=-8%")

    # Combined
    add((rr >= 0.8) & (vol >= 0.9), "RR>=0.8 & VR>=0.9")
    add((rr >= 1.0) & (vol >= 1.0), "RR>=1.0 & VR>=1.0")
    add((rr >= 1.0) & (vol >= 1.0) & (rsi <= 75), "RR>=1 & VR>=1 & RSI<=75")
    add((rr >= 1.0) & (vol >= 1.2), "RR>=1 & VR>=1.2")
    add((rr >= 1.2) & (vol >= 1.0), "RR>=1.2 & VR>=1.0")
    add((rr >= 1.5) & (vol >= 1.0), "RR>=1.5 & VR>=1.0")
    add((rr >= 1.0) & (rsi <= 70), "RR>=1 & RSI<=70")

    # buy/watch only subset commonly actionable
    actionable = df["signal_group"].isin(["buy_passed", "consensus"])
    add((actionable), "buy+consensus")
    add((actionable) & (rr >= 0.8), "buy+cons & RR>=0.8")
    add((actionable) & (rr >= 1.0), "buy+cons & RR>=1.0")
    add((actionable) & (rr >= 1.0) & (vol >= 1.0), "buy+cons & RR>=1 & VR>=1")

    results.sort(key=lambda x: (x["avg_t1"] if x["avg_t1"] is not None else -999), reverse=True)
    print("\nTop rules by avg T1:")
    print(pd.DataFrame(results).to_string(index=False))

    out_path = PROJECT_ROOT / "agents_workspace/trade_plan_backtest/rule_scan_results.csv"
    if results:
        pd.DataFrame(results).to_csv(out_path, index=False)
        print(f"\n[wrote] {out_path}")


if __name__ == "__main__":
    main()
