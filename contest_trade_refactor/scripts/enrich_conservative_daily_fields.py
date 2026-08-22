#!/usr/bin/env python3
"""Enrich unified_month_panel with daily fields needed for the conservative rule.

Adds (trigger-day, future-leak-safe) columns:
  turnover_pct        : 换手率 on trigger date (percent)
  turnover_5d_avg_pct : mean 换手率 over the 5 sessions ending trigger date
  turnover_20d_avg_pct: mean 换手率 over the 20 sessions ending trigger date
  turnover_ratio_5_20 : 5-day / 20-day turnover ratio
  mom_3d_pct          : close return across 3 sessions ending trigger date
  mom_5d_pct          : close return across 5 sessions ending trigger date
  dist_20d_high_pct   : 20-day high distance percent (<=0 means below 20d high)
  dist_60d_high_pct   : 60-day high distance percent
  boll_pct_b          : (close - lower) / (upper - lower), 0-1
  boll_above_upper    : 1 if close above upper band

This intentionally only uses bars on/before the trigger date.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from utils.cn_price_provider import get_stock_zh_a_hist


def std_hist(symbol, start, end):
    df = get_stock_zh_a_hist(symbol=symbol, start_date=start, end_date=end, adjust="qfq", verbose=False)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["date"] = pd.to_datetime(df.get("日期", df.get("date")), errors="coerce").dt.strftime("%Y%m%d")
    if "date" not in df:
        return pd.DataFrame()
    for col in ["开盘", "收盘", "最高", "最低", "成交量", "换手率"]:
        if col not in df:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["date", "收盘"]).sort_values("date").reset_index(drop=True)


def compute_day_features(frame, date_str):
    if frame.empty:
        return {}
    idx = frame.index[frame["date"].astype(str) == str(date_str)]
    if len(idx) == 0:
        return {}
    i = idx[0]
    if i < 0:
        return {}
    # Use only bars <= trigger date
    hist = frame.iloc[: i + 1].copy()
    close = hist["收盘"].astype(float)
    turnover = hist["换手率"].astype(float)
    vol = hist.get("成交量").astype(float) if "成交量" in hist else pd.Series(dtype=float)
    latest_close = float(close.iloc[-1])
    ret = {}
    ret["turnover_pct"] = float(turnover.iloc[-1]) if len(turnover) else None
    for n, key in [(5, "turnover_5d_avg_pct"), (20, "turnover_20d_avg_pct")]:
        avg = float(turnover.tail(n).mean()) if len(turnover) >= n and turnover.tail(n).notna().any() else None
        ret[key] = avg
    if ret.get("turnover_20d_avg_pct"):
        ret["turnover_ratio_5_20"] = round(float(ret["turnover_5d_avg_pct"] or 0) / ret["turnover_20d_avg_pct"], 3) if ret["turnover_20d_avg_pct"] else None
    else:
        ret["turnover_ratio_5_20"] = None
    for n, key in [(3, "mom_3d_pct"), (5, "mom_5d_pct")]:
        if len(close) >= n + 1:
            prev = float(close.iloc[-1 - n])
            ret[key] = round((latest_close / prev - 1.0) * 100.0, 3) if prev > 0 else None
        else:
            ret[key] = None
    if len(close) >= 20:
        h20 = float(hist["最高"].iloc[-20:].max())
        ret["dist_20d_high_pct"] = round((latest_close / h20 - 1.0) * 100.0, 3) if h20 > 0 else None
    else:
        ret["dist_20d_high_pct"] = None
    if len(close) >= 60:
        h60 = float(hist["最高"].iloc[-60:].max())
        ret["dist_60d_high_pct"] = round((latest_close / h60 - 1.0) * 100.0, 3) if h60 > 0 else None
    else:
        ret["dist_60d_high_pct"] = None
    if len(close) >= 20:
        sma = float(close.iloc[-20:].mean())
        std = float(close.iloc[-20:].std(ddof=1))
        if std > 0:
            upper = sma + 2 * std
            lower = sma - 2 * std
            ret["boll_pct_b"] = round((latest_close - lower) / (upper - lower), 3) if (upper - lower) else None
            ret["boll_above_pct"] = bool(latest_close > upper)
        else:
            ret["boll_pct_b"], ret["boll_above_pct"] = None, False
    else:
        ret["boll_pct_b"], ret["boll_above_pct"] = None, False
    return ret


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(PROJECT_ROOT / "agents_workspace/trade_plan_backtest_fix2_0617/unified_month_panel.csv"))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "agents_workspace/trade_plan_backtest_fix2_0617/daily_enriched_panel.csv"))
    parser.add_argument("--start", default="20260101")
    parser.add_argument("--end", default="20260831")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    df["date"] = df["date"].astype(str).str.slice(0, 8)
    uniq = df.drop_duplicates("code")[["code", "name"]].copy()
    if args.limit > 0:
        uniq = uniq.head(args.limit)
    print(f"[enrich] {len(uniq)} unique codes, {len(df)} rows")

    rows = []
    for idx, (code, name) in enumerate(uniq[["code", "name"]].itertuples(index=False), 1):
        try:
            hist = std_hist(code, args.start, args.end)
        except Exception as exc:
            print(f"[warn] {code} fetch failed: {exc}")
            hist = pd.DataFrame()
        for _, row in df[df["code"] == code].iterrows():
            feats = compute_day_features(hist, row["date"])
            out = row.to_dict()
            out.update(feats)
            rows.append(out)
        if idx % 25 == 0 or idx == len(uniq):
            print(f"[enrich] {idx}/{len(uniq)} codes done")
    print(f"[enrich] wrote {len(rows)} rows")
    out = pd.DataFrame(rows)
    out.to_csv(args.output, index=False)
    print(f"[wrote] {args.output}")


if __name__ == "__main__":
    main()
