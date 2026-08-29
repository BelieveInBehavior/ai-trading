"""主升浪持仓库：把 T+1 BUY 固化为持仓 JSON，并按退出状态机每日更新。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        v = float(value)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def compute_display_status(row: Dict[str, Any]) -> str:
    """统一 HOLD/WATCH/DECAY/ADD/REDUCE/SELL 展示状态。"""
    action = str(row.get("exit_action") or row.get("action") or "").lower()
    exit_class = str(row.get("exit_class") or "").upper()
    pos = str(row.get("position_state") or row.get("state") or "").upper()
    if exit_class.startswith("SELL") or action in ("sell", "exit") or pos == "EXIT":
        return "SELL"
    if exit_class == "REDUCE" or action == "reduce" or pos == "REDUCE":
        return "REDUCE"
    if pos == "ADD" or action == "add":
        return "ADD"
    if pos == "DECAY" or action == "decay":
        return "DECAY"
    if pos == "WATCH":
        return "WATCH"
    return "HOLD"


def build_from_t1(
    tday: Dict[str, Any],
    t1: Dict[str, Any],
    *,
    date: str = "",
    only_buy: bool = True,
) -> Dict[str, Any]:
    """从 T 日候选池 + T+1 执行结果生成初始持仓。

    - only_buy=Ture：只把 action == BUY 的行纳入持仓
    - 若需要把 WAIT 也展示，前端会从 t1_execution 里展示
    """
    tday_rows = {str(r.get("symbol_code") or ""): r for r in (tday.get("pool") or [])}
    holdings_rows = []
    for r in (t1.get("rows") or []):
        code = str(r.get("symbol_code") or "")
        if not code:
            continue
        action = str(r.get("action") or "")
        if only_buy and action.upper() != "BUY":
            continue
        cand = tday_rows.get(code) or {}
        entry_price = _num(r.get("entry_price")) or _num(cand.get("reference_price"))
        if not entry_price:
            continue
        holdings_rows.append({
            "symbol_code": code,
            "symbol_name": r.get("symbol_name") or cand.get("symbol_name") or "",
            "entry_date": date or t1.get("trade_date") or cand.get("trade_date") or "",
            "entry_price": round(entry_price, 4),
            "quantity": int(r.get("quantity") or 0),
            "suggested_position_pct": _num(r.get("suggested_position_pct")) or _num(cand.get("suggested_position_pct")),
            "raw_position_pct": _num(r.get("suggested_position_pct")) or _num(cand.get("raw_position_pct")),
            "holding_days": 0,
            "highest_price": round(entry_price, 4),
            "highest_close": _num(r.get("entry_price")) or _num(cand.get("highest_close")),
            "current_price": _num(r.get("current_price")) or entry_price,
            "buy_score": _num(r.get("final_score")) or _num(r.get("pre_score")) or 0.0,
            "signal_tier": str(r.get("execution_grade") or r.get("execution_grade") or "A"),
            "trade_plan": {
                "atr": _num(r.get("atr")) or _num(cand.get("atr")),
                "atr_pct": _num(r.get("atr_pct")) or _num(cand.get("atr_pct")),
                "target_price_1": _num(r.get("target_price_1")) or _num(cand.get("target_price_1")),
                "target_price_2": _num(r.get("target_price_2")) or _num(cand.get("target_price_2")),
                "target_method": r.get("target_method") or cand.get("target_method"),
                "ma10": _num(r.get("ma10")) or _num(cand.get("ma10")),
                "ma20": _num(r.get("ma20")) or _num(cand.get("ma20")),
                "volume_ratio": _num(r.get("volume_ratio")),
                "relative_strength_20d_pct": _num(r.get("rs_20d")) or _num(cand.get("rs_20d")) or _num(r.get("relative_strength_20d_pct")),
                "relative_strength_60d_pct": _num(r.get("rs_60d")) or _num(cand.get("rs_60d")) or _num(r.get("relative_strength_60d_pct")),
                "relative_strength_cross_section_pct": _num(r.get("relative_strength_cross_section_pct")) or _num(cand.get("relative_strength_cross_section_pct")),
                "relative_strength_score": _num(r.get("relative_strength_score")) or _num(cand.get("relative_strength_score")),
                "sector_rank": _num(r.get("sector_rank")) or _num(cand.get("sector_rank")) or _num(r.get("sector_rank_pct")),
                "sector_1d_return": _num(r.get("sector_change_pct")) or _num(cand.get("sector_change_pct")) or _num(r.get("sector_1d_return")),
                "sector_strength_pct": _num(r.get("sector_strength_pct")) or _num(cand.get("sector_strength_pct")),
                "ret_5d_pct": _num(r.get("ret_5d_pct")),
                "ret_20d_pct": _num(r.get("ret_20d_pct")),
                "entry_grade": str(r.get("execution_grade") or ""),
            },
            "stop_loss_price": _num(r.get("initial_stop")) or _num(cand.get("initial_stop")),
            "atr_trailing_stop": _num(r.get("trailing_stop")) or _num(cand.get("trailing_stop")),
            "prev_close": _num(r.get("prev_close")),
            "ma10": _num(r.get("ma10")) or _num(cand.get("ma10")),
            "ma20": _num(r.get("ma20")) or _num(cand.get("ma20")),
            "prev_ma20": _num(r.get("prev_ma20")) or _num(cand.get("prev_ma20")),
            "event_catalyst": r.get("event_catalyst") or {},
            "realtime_quote": {
                "atr": _num(r.get("atr")) or _num(cand.get("atr")),
                "atr_pct": _num(r.get("atr_pct")) or _num(cand.get("atr_pct")),
                "vwap_state": str(r.get("vwap_state") or ""),
                "bid_support": str(r.get("bid_support") or ""),
                "order_flow_score": _num(r.get("order_flow_score")) or 50.0,
                "intraday_structure_score": _num(r.get("intraday_structure_score")),
            },
            "order_flow_score": _num(r.get("order_flow_score"), 50.0) or 50.0,
            "trend_state": str(r.get("trend_state") or cand.get("trend_state") or ""),
            "previous_trend_state": "",
            "trend_state_streak": 1 if (r.get("trend_state") or cand.get("trend_state")) else 0,
            "trend_state_as_of": date or t1.get("trade_date") or cand.get("trade_date") or "",
            "trend_state_changed_at": date or t1.get("trade_date") or cand.get("trade_date") or "",
        })
    return {
        "phase": "holdings",
        "as_of_date": date or t1.get("trade_date") or tday.get("trade_date") or "",
        "count": len(holdings_rows),
        "holdings": holdings_rows,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def update_holdings(holdings: Dict[str, Any], exits: List[Dict[str, Any]], date: str = "") -> Dict[str, Any]:
    """用退出决策更新持仓状态：SELL/REDUCE/HOLD 标记。

    不会真的删除持仓，只是打状态标记，便于 User 确认后手动调仓。
    """
    mapping = {}
    for d in exits:
        mapping[d.get("symbol_code") or ""] = d

    rows = []
    for h in holdings.get("holdings") or []:
        code = str(h.get("symbol_code") or "")
        d = mapping.get(code) or {}
        updated = dict(h)
        updated["position_state"] = d.get("state") or d.get("position_state") or "HOLD"
        updated["exit_action"] = d.get("action") or "hold"
        updated["exit_class"] = d.get("exit_class") or ""
        updated["exit_level"] = d.get("exit_level") or ""
        updated["current_return_pct"] = d.get("current_return_pct") or 0.0
        updated["reduce_pct"] = d.get("reduce_pct") or 0.0
        updated["trailing_stop_price"] = d.get("trailing_stop_price")
        updated["exit_reason"] = d.get("reason") or ""
        updated["exit_reasons"] = d.get("reasons") or []
        updated["trailing_stop_price"] = _num(d.get("trailing_stop_price"), updated.get("trailing_stop_price"))
        updated["high_volume_class"] = d.get("high_volume_class") or updated.get("high_volume_class") or ""
        updated["high_volume_reason"] = d.get("high_volume_reason") or updated.get("high_volume_reason") or ""
        updated["trend_state"] = d.get("trend_state") or updated.get("trend_state") or ""
        updated["trend_state_reason"] = d.get("trend_state_reason") or updated.get("trend_state_reason") or ""
        for key in (
            "previous_trend_state", "trend_state_streak", "trend_reason_code", "trend_confidence",
            "trend_state_as_of", "trend_state_changed_at", "trend_state_info",
        ):
            if d.get(key) is not None:
                updated[key] = d.get(key)
        updated["add_setup"] = d.get("add_setup") or False
        updated["add_confirmation"] = d.get("add_confirmation") or False
        updated["add_setup_class"] = d.get("add_setup_class") or ""
        updated["sector_source"] = d.get("sector_source") or ""
        updated["rs_source"] = d.get("rs_source") or ""
        updated["next_day_guard_break_vwap"] = d.get("next_day_guard_break_vwap") or False
        if d.get("next_day_guard_vwap") is not None:
            updated.setdefault("trade_plan", {})["next_day_guard_vwap"] = d["next_day_guard_vwap"]
        if d.get("next_day_guard_high") is not None:
            updated.setdefault("trade_plan", {})["next_day_guard_high"] = d["next_day_guard_high"]
        updated["display_status"] = compute_display_status(updated)
        rows.append(updated)
    return {
        "phase": "holdings",
        "as_of_date": date or holdings.get("as_of_date") or "",
        "count": len(rows),
        "holdings": rows,
        "last_run": datetime.now().isoformat(timespec="seconds"),
        "decisions": exits,
    }



def build_from_result_rows(rows: List[Dict[str, Any]], *, date: str = "", only_buy_ready: bool = True) -> Dict[str, Any]:
    """从 result.json 的 candidate_pool_t1 / buy_signals 构建持仓。

    每行的 gates.execution 已含 T+1 实时价格；buy_ready=True 表示确认买入。
    """
    out = []
    for r in rows or []:
        code = str(r.get("symbol_code") or "")
        if not code:
            continue
        buy_ready = bool(r.get('buy_ready'))
        if only_buy_ready and not buy_ready:
            continue
        intraday = _extract_intraday_detail(r)
        price = intraday["price"] or _num(r.get("reference_price"))
        if not price:
            continue
        exec_gate = (r.get("gates") or {}).get("execution") or {}
        risk = (r.get("gates") or {}).get("risk") or {}
        risk_detail = risk.get("detail") or {}
        stop_distance_abs = _num(risk_detail.get("stop_distance_abs"))
        stop_price = _num(r.get("entry_price"))
        if stop_price is None and stop_distance_abs:
            stop_price = price - abs(stop_distance_abs)
        technical = r.get("technical_factor") or {}
        ma10 = _num(exec_gate.get("detail", {}).get("ma10")) or _num(r.get("ma10")) or _num(technical.get("ma10"))
        ma20 = _num(exec_gate.get("detail", {}).get("ma20")) or _num(r.get("ma20")) or _num(technical.get("ma20"))
        atr = intraday["atr"] or _num(r.get("atr"))
        atr_pct = None
        if atr and stop_distance_abs:
            atr_pct = atr / abs(stop_distance_abs) * 100.0 if atr and stop_distance_abs else None
        out.append({
            "symbol_code": code,
            "symbol_name": r.get("symbol_name") or "",
            "entry_date": r.get("trade_date") or date,
            "entry_price": round(price, 4),
            "quantity": 0,
            "suggested_position_pct": _num(r.get("suggested_position_pct")) or _num(r.get("raw_position_pct")),
            "raw_position_pct": _num(r.get("raw_position_pct")) or _num(r.get("suggested_position_pct")),
            "holding_days": 0,
            "highest_price": round(_num(intraday.get("high")) or price, 4),
            "highest_close": round(price, 4),
            "current_price": round(price, 4),
            "buy_score": _num(r.get("t1_buy_score")) or _num(r.get("entry_quality_score")) or _num(r.get("divergence_score")) or 0.0,
            "signal_tier": str(r.get("trend_quality") or r.get("execution_grade") or "A"),
            "trade_plan": {
                "atr": atr,
                "atr_pct": atr_pct,
                "ma10": ma10,
                "ma20": ma20,
                "volume_ratio": _num(intraday.get("volume_ratio")),
                "relative_strength_20d_pct": _num(r.get("relative_strength_20d_pct")) or _num(r.get("rs_20d")),
                "relative_strength_60d_pct": _num(r.get("relative_strength_60d_pct")) or _num(r.get("rs_60d")),
                "relative_strength_cross_section_pct": _num(r.get("relative_strength_cross_section_pct")),
                "relative_strength_score": _num(r.get("relative_strength_score")),
                "sector_rank": _num(r.get("sector_rank")) or _num(r.get("sector_rank_pct")),
                "sector_1d_return": _num(r.get("sector_1d_return")) or _num(r.get("sector_change_pct")),
                "sector_strength_pct": _num(r.get("sector_strength_pct")),
                "ret_5d_pct": _num(r.get("ret_5d_pct")),
                "ret_20d_pct": _num(r.get("ret_20d_pct")),
                "entry_grade": str(r.get("trend_quality") or ""),
            },
            "stop_loss_price": stop_price,
            "atr_trailing_stop": _num(r.get("trailing_stop")) or stop_price,
            "prev_close": _num(intraday.get("prev_close")),
            "ma10": ma10,
            "ma20": ma20,
            "prev_ma20": _num(r.get("prev_ma20")),
            "event_catalyst": r.get("event_catalyst") or {},
            "realtime_quote": {
                "atr": atr,
                "atr_pct": atr_pct,
                "vwap": _num(intraday.get("vwap")),
                "open": _num(intraday.get("open")),
                "high": _num(intraday.get("high")),
                "vwap_state": "Above" if intraday.get("price") and intraday.get("vwap") and intraday["price"] >= intraday["vwap"] else "Below",
                "bid_support": str(exec_gate.get("reason") or ""),
                "order_flow_score": _num(exec_gate.get('detail', {}).get('order_flow_score')) if isinstance(exec_gate.get('detail'), dict) else _num(exec_gate.get('order_flow_score')) or 50.0,
                "intraday_structure_score": _num(exec_gate.get("detail", {}).get("intraday_structure_score")) if isinstance(exec_gate.get('detail'), dict) else _num(exec_gate.get('intraday_structure_score')) or 0.0,
            },
            "order_flow_score": (_num(exec_gate.get('detail', {}).get("order_flow_score")) if isinstance(exec_gate.get("detail"), dict) else None) or 50.0,
            "trend_state": str(r.get("trend_state") or ""),
            "previous_trend_state": "",
            "trend_state_streak": 1 if r.get("trend_state") else 0,
            "trend_state_as_of": r.get("trade_date") or date,
            "trend_state_changed_at": r.get("trade_date") or date,
        })
    return {
        "phase": "holdings",
        "as_of_date": date or (rows[0].get("trade_date") if rows else ""),
        "count": len(out),
        "holdings": out,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "candidate_pool_t1",
    }


def _extract_intraday_detail(row: Dict[str, Any]) -> Dict[str, Any]:
    exec_gate = (row.get("gates") or {}).get("execution") or {}
    detail = exec_gate.get("detail") or {}
    nested = detail.get("detail") or {}
    price = _num(detail.get("price"))
    if price is None:
        price = _num(nested.get("price"))
    prev_close = _num(detail.get("prev_close")) or _num(nested.get("prev_close"))
    open_px = _num(detail.get("open")) or _num(nested.get("open"))
    high = _num(detail.get("high")) or _num(nested.get("high"))
    vwap = _num(detail.get("vwap")) or _num(nested.get("vwap"))
    volume_ratio = _num(nested.get("volume_ratio")) or _num(detail.get("volume_ratio"))
    atr = _num(detail.get("atr")) or _num(nested.get("atr"))
    risk = (row.get("gates") or {}).get("risk") or {}
    risk_detail = risk.get("detail") or {}
    atr_abs = _num(risk_detail.get("stop_distance_abs"))
    if atr is None and atr_abs:
        atr = atr_abs / 2.5
    return {
        "price": price,
        "prev_close": prev_close,
        "open": open_px,
        "high": high,
        "vwap": vwap,
        "volume_ratio": volume_ratio,
        "atr": atr,
    }
