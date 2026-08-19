#!/usr/bin/env python3
"""Backtest 短线保守组合 on unified_month_panel.

Default rule (module defaults):
  - RSI <= 65
  - 距52周高点 <= -8%
  - MA20偏离 <= 12%
  - MA50偏离 <= 25%

Outputs:
  - *_with_rule.csv: panel + rule_pass per row
  - *_monthly.csv: all vs rule monthly T3/T5 avg & win-rate
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from utils.conservative_short_rule import (
    DEFAULT_RSI_MAX,
    DEFAULT_DIST52_MAX,
    DEFAULT_MA20_DEV_MAX,
    DEFAULT_MA50_DEV_MAX,
    eval_conservative_rule,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(PROJECT_ROOT / "agents_workspace/trade_plan_backtest_fix2_0617/unified_month_panel.csv"))
    parser.add_argument("--rsi-max", type=float, default=DEFAULT_RSI_MAX)
    parser.add_argument("--dist52-max", type=float, default=DEFAULT_DIST52_MAX)
    parser.add_argument("--ma20-dev-max", type=float, default=DEFAULT_MA20_DEV_MAX)
    parser.add_argument("--ma50-dev-max", type=float, default=DEFAULT_MA50_DEV_MAX)
    parser.add_argument("--out", default=str(PROJECT_ROOT / "agents_workspace/trade_plan_backtest_fix2_0617/conservative_rule_monthly.csv"))
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    df["month"] = df["date"].astype(str).str[:6]

    evals = []
    for _, row in df.iterrows():
        evals.append(eval_conservative_rule(
            row.to_dict(),
            rsi_max=args.rsi_max,
            dist52_max=args.dist52_max,
            ma20_dev_max=args.ma20_dev_max,
            ma50_dev_max=args.ma50_dev_max,
        ))
    rule_df = pd.DataFrame(evals)
    df["rule_pass"] = rule_df["pass"].astype(bool)
    df["rule_reasons"] = rule_df["reasons"].apply(lambda r: "|".join(r))

    rule_name = f"conservative_rsi<={args.rsi_max}_dist52<={args.dist52_max}_ma20<={args.ma20_dev_max}_ma50<={args.ma50_dev_max}"
    out_panel = args.out.replace("_monthly.csv", "_with_rule.csv")
    df.to_csv(out_panel, index=False)

    baseline, pass_rows = [], []
    for m, g in df.groupby("month"):
        t3, t5 = g["t3"].dropna(), g["t5"].dropna()
        baseline.append({"month": m, "bucket": "all", "n_t3": len(t3), "avg_t3": t3.mean(),
                         "wr_t3": (t3 > 0).mean() * 100, "n_t5": len(t5), "avg_t5": t5.mean(), "wr_t5": (t5 > 0).mean() * 100})
        sub = g[g["rule_pass"]]
        st3, st5 = sub["t3"].dropna(), sub["t5"].dropna()
        pass_rows.append({"month": m, "bucket": rule_name, "n_t3": len(st3), "avg_t3": st3.mean(),
                          "wr_t3": (st3 > 0).mean() * 100, "n_t5": len(st5), "avg_t5": st5.mean(), "wr_t5": (st5 > 0).mean() * 100})

    out_df = pd.DataFrame(baseline + pass_rows)
    print(f"\nRule: {rule_name}  pass_count={int(df['rule_pass'].sum())}")
    print(out_df.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    out_df.to_csv(args.out, index=False)
    print(f"\n[wrote] {args.out}")
    print(f"[wrote] {out_panel}")


if __name__ == "__main__":
    main()
