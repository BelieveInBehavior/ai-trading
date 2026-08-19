#!/usr/bin/env python3
"""Join the existing unified 6/7/8 panel with scalable sector crowding factors and bucket T+3/T+5."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from utils.sector_enrichment import build_sector_snapshot_from_factor_store, build_code_sector_snapshot, load_industry_map

PANEL = PROJECT_ROOT / "agents_workspace" / "trade_plan_backtest_fix2_0617" / "daily_enriched_panel.csv"
OUT = PROJECT_ROOT / "agents_workspace" / "trade_plan_backtest_fix2_0617" / "entry_crowding_panel.csv"

def main():
    df = pd.read_csv(PANEL)
    im = load_industry_map()
    rows=[]
    for date, grp in df.groupby("date"):
        date=str(date)
        by = build_sector_snapshot_from_factor_store(trade_date=date)
        snap = build_code_sector_snapshot(im, by, trade_date=date)
        for _, r in grp.iterrows():
            code = str(r.get("code") or "").strip().zfill(6)
            info = snap.get(code) or snap.get(code+".SH") or snap.get(code+".SZ") or {}
            rows.append({
                "date": date,
                "code": code,
                "name": r.get("name"),
                "ret_3d_pct": r.get("mom_3d_pct"),
                "ret_5d_pct": r.get("mom_5d_pct"),
                "ma20_deviation_pct": r.get("ma20_deviation_pct"),
                "rsi": r.get("rsi"),
                "volume_ratio": r.get("volume_ratio"),
                "opportunity_rank_score": r.get("opportunity_rank_score"),
                "short_score": r.get("short_score"),
                "sector_1d_return": info.get("sector_1d_return"),
                "sector_3d_return": info.get("sector_3d_return"),
                "sector_5d_return": info.get("sector_5d_return"),
                "sector_10d_return": info.get("sector_10d_return"),
                "sector_rank": info.get("sector_rank"),
                "t3": r.get("t3"),
                "t5": r.get("t5"),
            })
    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    print("wrote", OUT, "rows", len(out), "dates", out['date'].nunique())

    def b5(v):
        if pd.isna(v): return "NA"
        v=float(v)
        if v<8: return '<8'
        if v<15: return '8~15'
        if v<25: return '15~25'
        return '>25'
    def bs5(v):
        if pd.isna(v): return "NA"
        v=float(v)
        if v<3: return '<3'
        if v<8: return '3~8'
        if v<15: return '8~15'
        return '>15'
    out['stock_b']=out['ret_5d_pct'].apply(b5)
    out['sector_b']=out["sector_5d_return"].apply(bs5)
    print("\n== overall t3/t5 ==")
    print(out[["t3","t5"]].describe().T.to_string())
    print("\n== stock_5d bucket x t5 ==")
    print(out.groupby("stock_b")["t5"].agg(["count","mean","median"]).to_string())
    print("\n== sector_5d bucket x t5 ==")
    print(out.groupby("sector_b")["t5"].agg(["count","mean","median"]).to_string())
    print("\n== stock x sector x t5 ==")
    print(out.pivot_table(index="stock_b", columns="sector_b", values="t5", aggfunc=["count","mean"]).to_string())

def upper(): return None
if __name__ == "__main__":
    main()
