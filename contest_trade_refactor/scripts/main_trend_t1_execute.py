#!/usr/bin/env python3
"""T+1 Execution：读取手工 6 字段，对 T 日候选打 Execution / Action。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from strategies.main_trend.event_logger import log_event
from strategies.main_trend.execution_manual import grade_execution
from strategies.main_trend.engine import MainTrendConfig
from strategies.main_trend.scoring import compute_final_score, compute_stops


def _num(value, default=None):
    try:
        if value is None or value == "":
            return default
        v = float(value)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tday", default="agents_workspace_main_trend/20260821/tday_pool.json")
    parser.add_argument("--manual", default="config/manual_execution.example.json")
    args = parser.parse_args()

    tday_path = Path(args.tday)
    if not tday_path.is_absolute():
        tday_path = PROJECT_ROOT / tday_path
    manual_path = Path(args.manual)
    if not manual_path.is_absolute():
        manual_path = PROJECT_ROOT / manual_path

    tday = json.loads(tday_path.read_text(encoding="utf-8"))
    manual = json.loads(manual_path.read_text(encoding="utf-8"))
    names = manual.get("names") or {}
    index_pct = manual.get("index_change_pct")
    scoring_cfg = MainTrendConfig.from_yaml().scoring
    pre_weight = float(scoring_cfg.get("pre_weight", 0.60) or 0.60)
    exec_weight = float(scoring_cfg.get("execution_weight", 0.40) or 0.40)
    rows = []
    for item in tday.get("pool") or []:
        code = str(item.get("symbol_code") or "")
        raw = names.get(code) or names.get(code.zfill(6))
        if not raw:
            rows.append({
                **{k: item.get(k) for k in ("symbol_code", "symbol_name", "theme", "pre_score")},
                "execution_grade": "?",
                "action": "WAIT",
                "reason": "未输入T+1字段",
                "entry_price": None,
                "initial_stop": item.get("initial_stop"),
                "initial_stop_pct": item.get("initial_stop_pct"),
                "trailing_stop": item.get("trailing_stop"),
                "current_stop": item.get("current_stop"),
                "target_price_1": item.get("target_price_1"),
                "target_price_2": item.get("target_price_2"),
                "target_method": item.get("target_method"),
                "ma20": item.get("ma20"),
                "atr": item.get("atr"),
                "take_profit_price": None,
                "suggested_position_pct": 0.0,
            })
            continue
        graded = grade_execution(
            open_px=raw.get("open"),
            price_0935=raw.get("price_0935"),
            prev_close=raw.get("prev_close") or item.get("reference_price"),
            auction_amount=raw.get("auction_amount"),
            index_change_pct=raw.get("index_change_pct", index_pct),
            sector_change_pct=raw.get("sector_change_pct"),
            bid_support=str(raw.get("bid_support") or ""),
            vwap=raw.get("vwap"),
        )
        final = compute_final_score(
            float(item.get("pre_score") or 0),
            graded["execution_score"],
            pre_weight=pre_weight,
            exec_weight=exec_weight,
        )
        sized = item.get("suggested_position_pct") if graded["action"] == "BUY" else 0.0
        # 买入价：T+1 执行输入有 price_0935 优先，否则用 open；都没有则不算完整 BUY。
        entry_price = raw.get("price_0935") if raw.get("price_0935") is not None else raw.get("open")
        execution_stops = compute_stops(
            entry_price,
            atr=_num(item.get("atr")),
            atr_pct=_num(item.get("atr_pct")),
            ma20=_num(item.get("ma20")),
        ) if entry_price is not None else {}
        # main_trend 短冲刺默认 no fixed take-profit：只用动态止损/ATR/MA20/5日超期作为退出参考。
        rows.append({
            "symbol_code": code,
            "symbol_name": item.get("symbol_name"),
            "theme": item.get("theme"),
            "pre_score": item.get("pre_score"),
            "final_score": final,
            "gap_pct": graded["gap_pct"],
            "index_change_pct": graded["index_change_pct"],
            "sector_change_pct": graded["sector_change_pct"],
            "vwap_state": graded["vwap_state"],
            "bid_support": graded["bid_support"],
            "execution_grade": graded["execution_grade"],
            "action": graded["action"],
            "entry_price": entry_price,
            "entry_time": raw.get("snapshot_time") or raw.get("pulled_at") or manual.get("pulled_at"),
            "initial_stop": execution_stops.get("initial_stop") or item.get("initial_stop"),
            "initial_stop_pct": execution_stops.get("initial_stop_pct") or item.get("initial_stop_pct"),
            "trailing_stop": execution_stops.get("trailing_stop") or item.get("trailing_stop"),
            "current_stop": execution_stops.get("current_stop") or item.get("current_stop"),
            "target_price_1": execution_stops.get("target_price_1") or item.get("target_price_1"),
            "target_price_2": execution_stops.get("target_price_2") or item.get("target_price_2"),
            "target_method": execution_stops.get("target_method") or item.get("target_method"),
            "ma20": item.get("ma20"),
            "atr": item.get("atr"),
            "take_profit_price": None,
            "stop_method": "MA20/ATR trailing/time-5d",  # main_trend 不使用固定止盈
            "suggested_position_pct": sized,
            "reasons": graded["reasons"],
        })

    dest = tday_path.parent / "t1_execution.json"
    payload = {"phase": "t1", "trade_date": tday.get("trade_date"), "index_change_pct": index_pct, "rows": rows}
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log_event(tday_path.parent, {"event": "t1_execution", "trade_date": tday.get("trade_date"), "count": len(rows)})
    print(f"wrote {dest}")
    print(f"{'股票':<8} {'Gap':>6} {'指数':>6} {'板块':>6} {'VWAP':<6} {'承接':<4} {'Exec':<4} {'Action':<6}")
    for row in rows:
        if row.get("execution_grade") == "?":
            continue
        print(
            f"{str(row.get('symbol_name') or '')[:8]:<8} "
            f"{row.get('gap_pct')!s:>6} "
            f"{row.get('index_change_pct')!s:>6} "
            f"{row.get('sector_change_pct')!s:>6} "
            f"{str(row.get('vwap_state') or ''):<6} "
            f"{str(row.get('bid_support') or ''):<4} "
            f"{str(row.get('execution_grade') or ''):<4} "
            f"{str(row.get('action') or ''):<6}"
        )


if __name__ == "__main__":
    main()
