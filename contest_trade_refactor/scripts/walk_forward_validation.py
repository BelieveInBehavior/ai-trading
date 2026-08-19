#!/usr/bin/env python3
"""
Walk-forward threshold/factor validation for the closed-loop signal CSV.

Uses time-ordered folds:
  - training fold: signals before a cut-off date
  - test fold: signals on/after cut-off
For each candidate factor, we compute:
  - whether the factor's top/bottom quartile predicts T1/T5 in test fold
  - IC in train vs test, and sign-consistency
  - optionally a simple "top decile by row-wise equal-weight" return

Outputs:
  agents_workspace/backtest_results/walk_forward_results.csv
  agents_workspace/backtest_results/walk_forward_report.md

Usage:
  .venv/bin/python scripts/walk_forward_validation.py \
    --input agents_workspace/backtest_results/signal_performance.csv \
    --folds 2
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, List

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FACTOR_COLS = [
    "buy_score", "forward_opportunity_score", "expected_net_edge_pct",
    "probability_value", "probability", "weekly_trend_score",
    "relative_strength_score", "daily_entry_score", "catalyst_score",
    "capital_flow_score", "market_regime_score", "risk_reward_score",
    "tradeability_score", "data_quality_score", "ma20_deviation_pct",
    "prev_day_gain_pct",
]


def safe_float_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def compute_ic(df: pd.DataFrame, factor: str, target: str = "t1_return_pct") -> float:
    sub = df[[factor, target]].copy()
    sub[factor] = pd.to_numeric(sub[factor], errors="coerce")
    sub[target] = pd.to_numeric(sub[target], errors="coerce")
    sub = sub.dropna()
    if len(sub) < 5 or sub[factor].nunique() <= 1:
        return math.nan
    try:
        return sub[factor].corr(sub[target], method="spearman")
    except Exception:
        return math.nan


def equal_weight_top_quartile(df: pd.DataFrame, factor: str, target: str = "t1_return_pct", q: float = 0.25) -> float:
    sub = df[[factor, target]].copy()
    sub[factor] = pd.to_numeric(sub[factor], errors="coerce")
    sub[target] = pd.to_numeric(sub[target], errors="coerce")
    sub = sub.dropna()
    if len(sub) < 8:
        return math.nan
    cutoff = sub[factor].quantile(1 - q)
    top = sub[sub[factor] >= cutoff]
    if len(top) == 0:
        return math.nan
    return top[target].mean()


def run_walk_forward(df: pd.DataFrame, folds: int = 2, purge_dates: int = 0) -> List[dict]:
    if df.empty or "trigger_date" not in df.columns:
        return []
    df = df.copy()
    if {"trigger_date", "symbol_code"}.issubset(df.columns):
        df = df.drop_duplicates(["trigger_date", "symbol_code"], keep="first")
    df["fold_date"] = pd.to_datetime(df["trigger_date"].astype(str), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["fold_date", "t1_return_pct"]).sort_values("fold_date")
    dates = sorted(df["fold_date"].unique())
    if len(dates) < folds + 1:
        return []

    # Purged expanding-window folds with non-overlapping test windows.
    base_cut = len(dates) // (folds + 1)
    results = []
    for fold_idx in range(1, folds + 1):
        train_end = base_cut * fold_idx
        if train_end >= len(dates):
            continue
        effective_train_end = max(0, train_end - max(0, purge_dates))
        train_dates = set(dates[:effective_train_end])
        test_start = dates[train_end] if train_end < len(dates) else None
        if not test_start:
            continue
        test_end = base_cut * (fold_idx + 1) if fold_idx < folds else len(dates)
        test_dates = dates[train_end:test_end]
        train = df[df["fold_date"].isin(train_dates)]
        test = df[df["fold_date"].isin(test_dates)]
        if train.empty or test.empty:
            continue
        for factor in FACTOR_COLS:
            if factor not in df.columns:
                continue
            train_ic = compute_ic(train, factor)
            test_ic = compute_ic(test, factor)
            train_top = compute_top_quartile(train, factor)
            test_top = compute_top_quartile(test, factor)
            if math.isnan(test_ic):
                continue
            results.append({
                "fold": fold_idx,
                "train_start": min(train_dates).strftime("%Y%m%d") if isinstance(min(train_dates), pd.Timestamp) else str(min(train_dates))[:8],
                "train_end": max(train_dates).strftime("%Y%m%d") if isinstance(max(train_dates), pd.Timestamp) else str(max(train_dates))[:8],
                "test_start": min(test_dates).strftime("%Y%m%d") if isinstance(min(test_dates), pd.Timestamp) else str(min(test_dates))[:8],
                "test_end": max(test_dates).strftime("%Y%m%d") if isinstance(max(test_dates), pd.Timestamp) else str(max(test_dates))[:8],
                "factor": factor,
                "train_n": len(train),
                "test_n": len(test),
                "train_ic": round(train_ic, 4) if not math.isnan(train_ic) else None,
                "test_ic": round(test_ic, 4),
                "train_top_quartile_avg": round(train_top, 4) if not math.isnan(train_top) else None,
                "test_top_quartile_avg": round(test_top, 4) if not math.isnan(test_top) else None,
            })
    return results


def compute_top_quartile(df: pd.DataFrame, factor: str, target: str = "t1_return_pct", q: float = 0.25) -> float:
    return equal_weight_top_quartile(df, factor, target, q)


def write_report(results: List[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not results:
        (output_dir / "walk_forward_report.md").write_text("# Walk-Forward Report\n\nNo results.\n", encoding="utf-8")
        return
    df = pd.DataFrame(results)
    path = output_dir / "walk_forward_results.csv"
    df.to_csv(path, index=False)

    lines = [
        "# Walk-Forward Validation",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Folds: {df['fold'].nunique()}",
        "",
        "## Factors sorted by avg test IC",
        "",
        "| factor | folds | avg_test_ic | min_test_ic | max_test_ic | sign_consistent | avg_test_topQ_ret |",
        "|---|---|---|---|---|---|---|",
    ]
    grouped = df.groupby("factor").agg(
        folds=('test_ic', 'count'),
        avg_test_ic=('test_ic', 'mean'),
        min_test_ic=('test_ic', 'min'),
        max_test_ic=('test_ic', 'max'),
        avg_test_topQ=('test_top_quartile_avg', 'mean'),
    ).reset_index()
    sign_cons = []
    for _, r in grouped.iterrows():
        vals = df[df['factor'] == r['factor']]['test_ic'].tolist()
        same_sign = all(v >= 0 for v in vals) or all(v <= 0 for v in vals)
        sign_cons.append("yes" if same_sign else "no")
    grouped = grouped.copy()
    grouped['sign_consistent'] = sign_cons
    grouped = grouped.sort_values('avg_test_ic', ascending=False)
    for _, r in grouped.iterrows():
        lines.append(
            f"| {r['factor']} | {int(r["folds"]) if pd.notna(r["folds"]) else 0} | "
            f"{r['avg_test_ic']:.4f} | {r['min_test_ic']:.4f} | {r['max_test_ic']:.4f} | "
            f"{r['sign_consistent']} | {r['avg_test_topQ']:.4f} |"
        )
    lines.append("")
    lines.append("## Fold details")
    lines.append("")
    try:
        lines.append(df.to_markdown(index=False))
    except Exception:
        lines.extend(df.to_string(index=False).split("\n"))
    report = output_dir / "walk_forward_report.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"[report] {output_dir / 'walk_forward_results.csv'}")
    print(f"[report] {report}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(PROJECT_ROOT / "agents_workspace" / "backtest_results" / "signal_performance.csv"))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "agents_workspace" / "backtest_results"))
    parser.add_argument("--folds", type=int, default=2, help="number of test folds")
    parser.add_argument("--purge-dates", type=int, default=5, help="trading-date gap between train and test")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[error] input not found: {input_path}")
        sys.exit(1)
    df = pd.read_csv(input_path)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    results = run_walk_forward(df, folds=args.folds, purge_dates=args.purge_dates)
    print(f"[walk] results rows: {len(results)}")
    write_report(results, out)


if __name__ == "__main__":
    main()
