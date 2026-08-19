#!/usr/bin/env python3
"""Use existing replay signal_performance.csv + trade_decision JSON to compare T+1 / T+3 for current system."""
from __future__ import annotations
import glob,json,sys
from pathlib import Path
import pandas as pd
PROJECT_ROOT=Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from agents.stock_opportunity_ranker import StockOpportunityRanker
from utils.sector_enrichment import build_sector_snapshot_from_factor_store,build_code_sector_snapshot,load_industry_map, enrich_factor_with_sector

def norm(code): return ''.join(ch for ch in str(code).upper() if ch.isdigit())[:6]

def main():
    replay_dirs = [
        'agents_workspace_replays/current_no_future_june17_30',
        'agents_workspace_replays/current_system_0810_0813',
        'agents_workspace_replays/historical_pilot_rescore_short3d_v4',
    ]
    all_rows=[]
    ranker=StockOpportunityRanker()
    im=load_industry_map()
    for rd in replay_dirs:
        p=Path(rd)
        perf=p/'backtest_results'/'signal_performance.csv'
        if not perf.exists():
            continue
        df=pd.read_csv(perf)
        tech={}
        for fp in glob.glob(str(p/'*'/'results'/'trade_decisions'/'*.json')):
            try:
                d=json.loads(Path(fp).read_text(encoding='utf-8'))
            except Exception:
                continue
            date=''.join(ch for ch in str(d.get('trigger_time') or '') if ch.isdigit())[:8]
            for sig in (d.get('research_signals') or d.get('buy_signals') or []):
                tf=sig.get('technical_factor') or {}
                code=norm(sig.get('symbol_code'))
                if code:
                    tech[(code,date)]=tf
        for _,r in df.iterrows():
            date=str(r.get('trigger_date') or '')
            date=(''.join(ch for ch in date if ch.isdigit())[:8]) if date else date
            code=norm(r.get('symbol_code'))
            tf=tech.get((code,date),{})
            try:
                by=build_sector_snapshot_from_factor_store(trade_date=date if date else None)
                snap=build_code_sector_snapshot(im,by,trade_date=date if date else None)
                tf=enrich_factor_with_sector(tf,snap)
            except Exception:
                pass
            synthetic={'technical_factor': tf, 'symbol_code': code, 'symbol_name': r.get('symbol_name_raw')}
            delta=0.0; eq=50.0; crowd=0.0
            try:
                delta, _, report = ranker._score_entry_quality(synthetic, 50.0, 50.0, 50.0, 50.0)
                eq=report.get('entry_quality_score')
                crowd=report.get('crowding_score')
            except Exception:
                pass
            new_score=None
            if r.get('buy_score') is not None and pd.notna(r.get('buy_score')):
                new_score=max(0.0,min(99.5,float(r['buy_score'])+delta))
            all_rows.append({
                'replay': rd,
                'trigger_date': date,
                'symbol_code': code,
                'symbol_name': r.get('symbol_name_raw'),
                'signal_group': r.get('signal_group'),
                'buy_score': r.get('buy_score'),
                'entry_delta': delta,
                'new_buy_score': new_score,
                'entry_quality': eq,
                'crowding': crowd,
                't1': r.get('t1_return_pct'),
                't3': r.get('t3_return_pct'),
                't5': r.get('t5_return_pct'),
            })
    out=pd.DataFrame(all_rows)
    print('rows',len(out))
    if out.empty:
        return
    out.to_csv('agents_workspace/trade_plan_backtest_fix2_0617/current_t1_t3_replay_samples.csv',index=False)
    valid=out[out['buy_score'].notna()].copy()
    print('valid rows',len(valid))
    if valid.empty:
        return
    print('\nOverall by signal_group:')
    print(valid.groupby('signal_group')[['t1','t3']].agg(['count','mean','median']).to_string())
    def bucket(v):
        if pd.isna(v): return 'NA'
        if v<35: return '<35'
        if v<50: return '35~50'
        return '>50'
    valid['eq_b']=valid['entry_quality'].apply(bucket)
    print('\nentry_quality bucket vs t1/t3:')
    print(valid.groupby('eq_b')[['t1','t3']].agg(['count','mean']).to_string())
    def bdelta(v):
        if pd.isna(v): return 'NA'
        if v>=-2: return '>=-2'
        if v>=-8: return '-8~-2'
        return '<-8'
    valid['delta_b']=valid['entry_delta'].apply(bdelta)
    print('\nentry_delta bucket vs t1/t3:')
    print(valid.groupby('delta_b')[['t1','t3']].agg(['count','mean']).to_string())

if __name__=='__main__':
    main()
