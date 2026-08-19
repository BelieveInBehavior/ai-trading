#!/usr/bin/env python3
"""Focused search for a better trade_plan rule on existing historical signals.

Small sample - this is exploratory. It reports candidate rules along with
sample size / avg return / win rate so you can judge overfitting risk.
"""
from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(PROJECT_ROOT / "agents_workspace/trade_plan_backtest/backtest_results/signal_performance.csv"))
    parser.add_argument("--min-n", type=int, default=3)
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    t1 = pd.to_numeric(df["t1_return_pct"], errors="coerce")
    rr = pd.to_numeric(df.get("trade_plan_rr_1"), errors="coerce")
    vol = pd.to_numeric(df.get("trade_plan_volume_ratio"), errors="coerce")
    rsi = pd.to_numeric(df.get("trade_plan_rsi"), errors="coerce")
    stop_pct = pd.to_numeric(df.get("trade_plan_stop_loss_pct"), errors="coerce")
    actionable = df["signal_group"].isin(["buy_passed", "consensus"])

    rules = []

    # Candidate conditions. Each is a pandas boolean Series (nullable).
    conds = {
        "buy+cons": actionable,
        "RR>=0.6": rr >= 0.6,
        "RR>=0.8": rr >= 0.8,
        "RR>=1.0": rr >= 1.0,
        "VR>=1.0": vol >= 1.0,
        "VR>=1.1": vol >= 1.1,
        "VR>=1.2": vol >= 1.2,
        "RSI<=65": rsi <= 65,
        "RSI<=70": rsi <= 70,
        "RSI<=75": rsi <= 75,
        "stop>=-5": stop_pct >= -5,
        "stop>=-8": stop_pct >= -8,
    }

    # Simple rules
    for k, mask in conds.items():
        rules.append((k, mask.fillna(False) if hasattr(mask, "fillna") else mask))

    # Conjunctions of 2 or 3 conditions
    keys = list(conds.keys())
    for comb in itertools.combinations(keys, 2):
        label = "&".join(comb)
        mask = True
        for k in comb:
            m = conds[k]
            mask = mask & (m.fillna(False) if hasattr(m, "fillna") else m)
        rules.append((label, mask))

    seen = set()
    results = []
    for label, mask in rules:
        if hasattr(mask, "fillna"):
            mask = mask.fillna(False)
        if label in seen:
            continue
        seen.add(label)
        sub = df[mask]
        if len(sub) < args.min_n:
            continue
        t1s = pd.to_numeric(sub["t1_return_pct"], errors="coerce").dropna()
        if len(t1s) == 0:
            continue
        win_rate = (t1s > 0).mean() * 100
        avg = t1s.mean()
        median = t1s.median()
        summed = t1s.sum()
        max_loss_mean = pd.to_numeric(sub.get("max_drawdown_pct"), errors="coerce").dropna().mean() if "max_drawdown_pct" in sub.columns else None
        results.append({
            "rule": label,
            "n": len(t1s),
            "win_rate": round(win_rate, 1),
            "avg_t1": round(avg, 3),
            "median_t1": round(median, 3),
            "sum_t1": round(summed, 2),
            "avg_max_loss": round(max_loss_mean, 3) if max_loss_mean is not None and max_loss_mean == max_loss_mean else None,
        })

    # Keep only rules with at least 4 samples for more stable
    results.sort(key=lambda x: (x["avg_t1"], x["win_rate"]), reverse=True)
    print(f"\nTop {args.top} rules by avg T1 (>= {args.min_n} samples):")
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 200)
    print(pd.DataFrame(results).head(args.top).to_string(index=False))
    out = PROJECT_ROOT / "agents_workspace/trade_plan_backtest/rule_scan2_results.csv"
    pd.DataFrame(results).to_csv(out, index=False)
    print(f"\n[wrote] {out}")


if __name__ == "__main__":
    main()
