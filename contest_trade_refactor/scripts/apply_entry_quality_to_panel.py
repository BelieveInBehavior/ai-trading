#!/usr/bin/env python3
"""Approximate new entry_quality score on unified 2400 panel using ranker._score_entry_quality logic."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from agents.stock_opportunity_ranker import StockOpportunityRanker

PANEL=PROJECT_ROOT/"agents_workspace"/"trade_plan_backtest_fix2_0617"/"entry_crowding_panel.csv"
OUT=PROJECT_ROOT/"agents_workspace"/"trade_plan_backtest_fix2_0617"/"entry_crowding_panel_rescored.csv"

def main():
    df=pd.read_csv(PANEL)
    ranker=StockOpportunityRanker()
    rows=[]
    for _,r in df.iterrows():
        # build synthetic signal with fields used by _score_entry_quality
        sig={
            "technical_factor":{
               "ret_3d_pct": r.get("ret_3d_pct"), "ret_5d_pct": r.get("ret_5d_pct"),
               "sector_3d_return": r.get("sector_3d_return"), "sector_5d_return": r.get("sector_5d_return"),
               "sector_10d_return": r.get("sector_10d_return"), "sector_rank": r.get("sector_rank"),
               "ma20_deviation_pct": r.get("ma20_deviation_pct"), "rsi": r.get("rsi"),
               "stock_vs_sector_strength": None,
               "breakout_20d": False, "breakout_60d": False,
               "close_above_ma5": True, "amount_ratio": None, "volume_ratio": r.get("volume_ratio"),
               "change_pct": None, "ret_1d_pct": None,
            },
            "symbol_code": r.get("code"), "symbol_name": r.get("name"),
        }
        try:
            delta, _, report = ranker._score_entry_quality(sig, short_momentum_score=50, volume_amount_score=50, sector_strength_score=50, catalyst_score=50)
            eq=report.get("entry_quality_score")
            crowd=report.get("crowding_score")
            crowd_mean=report.get("crowding_mean")
        except Exception as e:
            delta,eq,crowd,crowd_mean=None,None,None,None
        rows.append({"code": r.get("code"), "date": r.get("date"), "entry_delta": delta, "entry_quality": eq,
                    "crowding": crowd, "crowding_mean": crowd_mean, "t3": r.get("t3"), "t5": r.get("t5"),
                    "ret_5d_pct": r.get("ret_5d_pct"), "sector_5d_return": r.get("sector_5d_return")})
    out=pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    print("wrote",OUT,len(out))
    valid=out[out["t5"].notna()]
    # bucketing new eq score
    def bucket(v):
        if pd.isna(v): return "NA"
        if v < 35: return "<35"
        if v < 50: return "35~50"
        return ">50"
    valid["eq_b"]=valid["entry_quality"].apply(bucket)
    print("\nentry_quality bucket vs t5")
    print(valid.groupby("eq_b")["t5"].agg(["count","mean","median"]).to_string())
    print("\nentry_delta bucket vs t5")
    def bd(v):
        if pd.isna(v): return "NA"
        if v >= -2: return ">=-2"
        if v >= -8: return "-8~-2"
        return "<-8"
    valid["delta_b"]=valid["entry_delta"].apply(bd)
    print(valid.groupby("delta_b")["t5"].agg(["count","mean","median"]).to_string())

if __name__=="__main__":
    main()
