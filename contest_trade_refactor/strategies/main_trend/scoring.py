"""T 日 PreScore：短冲刺 1~5 天候选排序分。

T 日没有 Execution，只产生 Pre-Execution Score：
    PreScore = Trend×40% + Sector×25% + MarketSentiment×15% + HotMoney×10% + Catalyst×10%
T+1：
    FinalScore = PreScore×60% + Execution×40%
"""
from __future__ import annotations

from typing import Any, Dict, Optional


TREND_STATE_BASE = {"S2": 88.0, "S3": 76.0, "S1": 64.0, "S4": 40.0, "S0": 20.0, "S5": 10.0}


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        result = float(value)
        if result != result:
            return default
        return result
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def grade_from_score(score: float) -> str:
    if score >= 75:
        return "A"
    if score >= 55:
        return "B"
    if score >= 40:
        return "C"
    return "D"


def trend_component(trend_state: str, quality_score: Optional[float]) -> float:
    base = TREND_STATE_BASE.get(str(trend_state or "S0"), 30.0)
    q = _num(quality_score, 50.0) or 50.0
    # 质量只做微调，避免所有 S2+A 都顶满
    return _clamp(base + (q - 70.0) * 0.25)


def sector_component(sector_score: Optional[float], sector_grade: str = "") -> float:
    raw = _num(sector_score)
    if raw is not None:
        return _clamp(raw)
    return {"A": 80.0, "B": 55.0, "C": 40.0, "D": 20.0}.get(str(sector_grade or "").upper(), 50.0)


def catalyst_component(catalyst_score: Optional[float], has_event: bool = False) -> float:
    raw = _num(catalyst_score, 50.0) or 50.0
    if has_event:
        return _clamp(raw)
    # 无结构化事件：中性，不把“缺失”当成加分
    return 50.0


def neutral_component(score: Optional[float]) -> float:
    """市场情绪/热钱缺失时按 50 中性处理，不因数据缺失加减分。"""
    return _clamp(_num(score, 50.0) or 50.0)


def compute_pre_score(
    *,
    trend_state: str,
    quality_score: Optional[float],
    sector_score: Optional[float],
    sector_grade: str = "",
    market_sentiment_score: Optional[float] = None,
    hot_money_score: Optional[float] = None,
    catalyst_score: Optional[float] = None,
    has_event: bool = False,
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    w = weights or {}
    wt = float(w.get("trend", 0.40) or 0.40)
    ws = float(w.get("sector", 0.25) or 0.25)
    wm = float(w.get("market_sentiment", 0.15) or 0.15)
    wh = float(w.get("hot_money", 0.10) or 0.10)
    wc = float(w.get("catalyst", 0.10) or 0.10)
    total = wt + ws + wm + wh + wc
    if total <= 0:
        wt, ws, wm, wh, wc = 0.40, 0.25, 0.15, 0.10, 0.10
    else:
        wt, ws, wm, wh, wc = wt / total, ws / total, wm / total, wh / total, wc / total

    trend = trend_component(trend_state, quality_score)
    sector = sector_component(sector_score, sector_grade)
    market_sentiment = neutral_component(market_sentiment_score)
    hot_money = neutral_component(hot_money_score)
    catalyst = catalyst_component(catalyst_score, has_event)
    pre = _clamp(trend * wt + sector * ws + market_sentiment * wm + hot_money * wh + catalyst * wc)
    return {
        "trend_score": round(trend, 2),
        "trend_grade": grade_from_score(trend),
        "sector_score": round(sector, 2),
        "sector_grade": grade_from_score(sector) if not sector_grade else str(sector_grade).upper(),
        "market_sentiment_score": round(market_sentiment, 2),
        "market_sentiment_grade": grade_from_score(market_sentiment),
        "hot_money_score": round(hot_money, 2),
        "hot_money_grade": grade_from_score(hot_money),
        "catalyst_score": round(catalyst, 2),
        "catalyst_grade": grade_from_score(catalyst) if has_event else "B",
        "pre_score": round(pre, 2),
    }


def compute_final_score(
    pre_score: float,
    execution_score: Optional[float],
    *,
    pre_weight: float = 0.60,
    exec_weight: float = 0.40,
) -> float:
    if execution_score is None:
        return round(_clamp(pre_score), 2)
    pw = float(pre_weight)
    ew = float(exec_weight)
    if pw + ew <= 0:
        pw, ew = 0.60, 0.40
    else:
        s = pw + ew
        pw, ew = pw / s, ew / s
    return round(_clamp(pre_score * pw + float(execution_score) * ew), 2)


def compute_stops(
    reference_price: Optional[float],
    *,
    atr: Optional[float] = None,
    atr_pct: Optional[float] = None,
    ma20: Optional[float] = None,
    ma20_deviation_pct: Optional[float] = None,
    initial_atr_mult: float = 2.5,
    trail_atr_mult: float = 3.0,
) -> Dict[str, Any]:
    """动态风险：Initial Stop = max(MA20, Entry - K×ATR)；无固定 ±6%。"""
    ref = _num(reference_price)
    if ref is None or ref <= 0:
        return {
            "reference_price": None,
            "ma20": None,
            "atr": None,
            "initial_stop": None,
            "initial_stop_pct": None,
            "trailing_stop": None,
            "stop_method": "missing_price",
        }

    atr_abs = _num(atr)
    if atr_abs is None:
        ap = _num(atr_pct)
        if ap is not None:
            atr_abs = ref * ap / 100.0

    ma20_px = _num(ma20)
    if ma20_px is None:
        dev = _num(ma20_deviation_pct)
        if dev is not None and abs(dev) < 80:
            ma20_px = ref / (1.0 + dev / 100.0)

    atr_stop = ref - float(initial_atr_mult) * atr_abs if atr_abs and atr_abs > 0 else None
    # Initial Stop 与风险预算对齐：Entry - K×ATR；MA20 是生命线，不是固定 ±6%
    initial = atr_stop if atr_stop and atr_stop > 0 else None
    method = "atr" if initial else "none"
    if initial is None and ma20_px and 0 < ma20_px < ref:
        initial = ma20_px
        method = "ma20"

    trail = None
    if atr_abs and atr_abs > 0:
        trail = ref - float(trail_atr_mult) * atr_abs
        if trail <= 0:
            trail = None

    protective = [x for x in (initial, ma20_px) if x is not None and 0 < x < ref]
    current = max(protective) if protective else initial

    initial_pct = None
    if initial is not None:
        initial_pct = round((initial / ref - 1.0) * 100.0, 2)

    return {
        "reference_price": round(ref, 4),
        "ma20": None if ma20_px is None else round(ma20_px, 4),
        "atr": None if atr_abs is None else round(atr_abs, 4),
        "target_price_1": None if atr_abs is None or atr_abs <= 0 else round(ref + 1.5 * atr_abs, 4),
        "target_price_2": None if atr_abs is None or atr_abs <= 0 else round(ref + 2.5 * atr_abs, 4),
        "target_method": "atr_1.5_2.5" if atr_abs is not None and atr_abs > 0 else "none",
        "initial_stop": None if initial is None else round(initial, 4),
        "initial_stop_pct": initial_pct,
        "trailing_stop": None if trail is None else round(trail, 4),
        "highest_close": round(ref, 4),
        "current_stop": None if current is None else round(current, 4),
        "stop_method": method,
    }


def compute_profit_protect_price(
    entry_price: Optional[float],
    current_price: Optional[float],
    *,
    ma10: Optional[float] = None,
    vwap: Optional[float] = None,
    highest_close: Optional[float] = None,
) -> Dict[str, Any]:
    """短冲刺浮盈保护价。

    不做固定止盈；当浮盈达到阈值后，给出“利润保护线”供盘中/次日执行参考：
      - 浮盈 >= 4%：至少保护约 +2%，并参考 MA10 / VWAP。
      - 浮盈 >= 8%：至少保护约 +4%，并参考最高收盘回撤 6% / MA10。
    """
    entry = _num(entry_price)
    current = _num(current_price)
    if entry is None or current is None or entry <= 0 or current <= 0:
        return {
            "profit_protect_price": None,
            "profit_protect_level": "",
            "profit_protect_reason": "missing_price",
        }

    ret_pct = (current / entry - 1.0) * 100.0
    ma10_px = _num(ma10)
    vwap_px = _num(vwap)
    high_close = _num(highest_close)
    candidates = []
    level = ""
    reason_bits = []

    if ret_pct >= 8.0:
        candidates.append(entry * 1.04)
        reason_bits.append("entry+4%")
        if high_close and high_close > 0:
            candidates.append(high_close * 0.94)
            reason_bits.append("highest_close-6%")
        if ma10_px and ma10_px > 0:
            candidates.append(ma10_px)
            reason_bits.append("MA10")
        level = "lock_4pct"
    elif ret_pct >= 4.0:
        candidates.append(entry * 1.02)
        reason_bits.append("entry+2%")
        if ma10_px and ma10_px > 0:
            candidates.append(ma10_px)
            reason_bits.append("MA10")
        if vwap_px and vwap_px > 0:
            candidates.append(vwap_px)
            reason_bits.append("VWAP")
        level = "lock_2pct"

    if not candidates:
        return {
            "profit_protect_price": None,
            "profit_protect_level": "",
            "profit_protect_reason": "浮盈未达到4%，暂不设保护价",
        }

    protect = max(candidates)
    return {
        "profit_protect_price": round(protect, 4),
        "profit_protect_level": level,
        "profit_protect_reason": "+".join(reason_bits),
    }
