"""T+1 Execution：无实时 API 时手工输入 6 个字段。"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        result = float(value)
        if result != result:
            return default
        return result
    except (TypeError, ValueError):
        return default


def grade_execution(
    *,
    open_px: Optional[float],
    price_0935: Optional[float],
    prev_close: Optional[float],
    auction_amount: Optional[float],
    index_change_pct: Optional[float],
    sector_change_pct: Optional[float],
    bid_support: str = "",
    vwap: Optional[float] = None,
) -> Dict[str, Any]:
    """6 字段 -> Gap / Index / Sector / VWAP / 承接 / Execution / Action。"""
    ref = prev_close or open_px
    px = price_0935 if price_0935 is not None else open_px
    gap = None
    if open_px and ref and ref > 0:
        gap = (open_px / ref - 1.0) * 100.0

    vwap_state = ""
    if px is not None and vwap is not None and vwap > 0:
        vwap_state = "Above" if px >= vwap else "Below"
    elif px is not None and open_px is not None:
        vwap_state = "Above" if px >= open_px else "Below"

    support = str(bid_support or "").strip() or "未知"
    score = 50.0
    reasons = []

    if gap is None:
        reasons.append("Gap未知")
    elif gap >= 5.0:
        score -= 20
        reasons.append("高开成本过高")
    elif gap >= 2.0:
        score -= 8
        reasons.append("高开成本偏高")
    elif gap <= -3.0:
        score -= 15
        reasons.append("低开偏弱")
    else:
        score += 10
        reasons.append("Gap可控")

    idx = _num(index_change_pct)
    if idx is not None:
        if idx >= 1.5:
            score += 12
            reasons.append("指数>=+1.5%")
        elif idx >= 0.5:
            score += 6
        elif idx <= -1.0:
            score -= 10
            reasons.append("指数转弱")

    sec = _num(sector_change_pct)
    if sec is not None:
        if sec >= 3.0:
            score += 15
            reasons.append("板块>=+3%")
        elif sec >= 1.0:
            score += 8
        elif sec <= -1.0:
            score -= 12
            reasons.append("板块转弱")

    if vwap_state == "Above":
        score += 10
        reasons.append("价格>=VWAP/开盘")
    elif vwap_state == "Below":
        score -= 12
        reasons.append("价格低于VWAP/开盘")

    if support in ("强", "strong", "A"):
        score += 12
        reasons.append("盘口承接强")
    elif support in ("弱", "weak", "C"):
        score -= 15
        reasons.append("盘口承接弱")

    amt = _num(auction_amount)
    if amt is not None and amt >= 80_000_000:
        score += 6
        reasons.append("竞价额大")

    score = max(0.0, min(100.0, score))
    if score >= 75 and vwap_state != "Below" and (gap is None or gap < 5.0) and support not in ("弱", "weak", "C"):
        grade, action = "A", "BUY"
    elif score >= 55:
        grade, action = "B", "WAIT"
    else:
        grade, action = "C", "WAIT"

    return {
        "gap_pct": None if gap is None else round(gap, 2),
        "index_change_pct": None if idx is None else round(idx, 2),
        "sector_change_pct": None if sec is None else round(sec, 2),
        "vwap_state": vwap_state or "?",
        "bid_support": support,
        "execution_score": round(score, 2),
        "execution_grade": grade,
        "action": action,
        "reasons": reasons,
        "open": open_px,
        "price_0935": price_0935,
        "auction_amount": amt,
    }
