"""Deterministic scoring helpers for the T+1~T+3 strong-stock lifecycle.

The project already has rich technical factors, limit-up snapshots and trade
plans. This module turns those inputs into a single lifecycle view:

- strong stock discovery: 连板 / 突破 / 趋势强股
- divergence quality: 首阴 / 断板
- weak-to-strong confirmation: VWAP / MA5 / 量价 / 回踩 / 短线结构（不重复 entry_quality）
- entry quality: 价格/风险/止损空间/RR/板块拥挤（不重复转强信号）

The functions are deliberately rule-based. LLMs can explain the result, but do
not decide it.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from utils.factor_store import ZT_SEAL_STORE


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.strip().replace("%", "")
        result = float(value)
        if result != result:
            return default
        return result
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.strip()
        result = int(float(value))
        return result
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "是", "有", "ok", "passed"}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _normalize_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 6:
        return ""
    code = digits[-6:]
    suffix = ".SH" if code.startswith("6") else ".SZ"
    return f"{code}{suffix}"


def _normalize_reason_list(items: Iterable[Any]) -> List[str]:
    return [str(item).strip() for item in items if str(item).strip()]


def load_zt_strength_snapshot(trade_date: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """Load daily limit-up seal strength snapshot from the factor store."""
    if not trade_date:
        return {}
    try:
        df = ZT_SEAL_STORE.load(trade_date)
    except Exception:
        return {}
    if df is None or df.empty:
        return {}

    snapshot: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        code = _normalize_code(row.get("symbol_code"))
        if not code:
            continue
        meta: Dict[str, Any] = {}
        try:
            meta = json.loads(row.get("metadata_json") or "{}")
        except Exception:
            meta = {}
        factor_value = _num(row.get("factor_value"), 0.0) or 0.0
        continuous_board = _int(meta.get("continuous_board", meta.get("limit_times", 1)), 1)
        break_count = _int(meta.get("break_count", meta.get("open_times", 0)), 0)
        seal_amount = _num(meta.get("seal_amount"), 0.0) or 0.0
        turnover = _num(meta.get("turnover"), 0.0) or 0.0
        one_word_limit_up = _bool(meta.get("one_word_limit_up")) or (
            continuous_board >= 1
            and break_count == 0
            and factor_value >= 5.0
            and turnover <= 1.0
        )
        snapshot[code] = {
            "symbol_code": code,
            "seal_strength": round(factor_value, 3),
            "continuous_board": continuous_board,
            "break_count": break_count,
            "seal_amount": round(seal_amount, 3),
            "turnover": round(turnover, 3),
            "one_word_limit_up": one_word_limit_up,
        }
        snapshot[code.split(".")[0]] = snapshot[code]
    return snapshot


def classify_strong_stock(
    factor: Dict[str, Any],
    zt_snapshot: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Identify the strong-stock type and score it."""
    zt_snapshot = zt_snapshot or {}
    code = _normalize_code(factor.get("symbol_code"))
    zt_info = zt_snapshot.get(code) or zt_snapshot.get(code.split(".")[0]) if code else None

    change_pct = _num(factor.get("change_pct"))
    ma20_dev = _num(factor.get("ma20_deviation_pct"))
    volume_ratio = _num(factor.get("volume_ratio"))
    amount_ratio = _num(factor.get("amount_ratio"))
    weekly_score = _num(factor.get("weekly_trend_score"), 50.0) or 50.0
    relative_score = _num(factor.get("relative_strength_score"), 50.0) or 50.0
    daily_score = _num(factor.get("daily_entry_score"), 50.0) or 50.0
    short_score = _num(factor.get("short_setup_score"), 50.0) or 50.0
    sector_score = _num(factor.get("sector_score"), 50.0) or 50.0
    stock_vs_sector = _num(factor.get("stock_vs_sector_strength"))
    close_above_ma5 = _bool(factor.get("close_above_ma5"))
    ma5_slope = _num(factor.get("ma5_slope_pct"))
    breakout20 = _bool(factor.get("breakout_20d"))
    breakout60 = _bool(factor.get("breakout_60d"))
    rsi = _num(factor.get("rsi"))

    board_count = _int((zt_info or {}).get("continuous_board", factor.get("continuous_board")), 0)
    break_count = _int((zt_info or {}).get("break_count", factor.get("break_count")), 0)
    seal_strength = _num((zt_info or {}).get("seal_strength", factor.get("seal_strength")), 0.0) or 0.0
    one_word_limit_up = _bool((zt_info or {}).get("one_word_limit_up", factor.get("one_word_limit_up")))

    hard_failed: List[str] = []
    if not _bool(factor.get("data_quality_valid", True)) or str(factor.get("data_quality_status") or "ok") != "ok":
        hard_failed.append("data_quality")
    if one_word_limit_up:
        hard_failed.append("one_word_limit_up")
    if change_pct is not None and change_pct > 18 and not (board_count >= 2 or breakout60):
        hard_failed.append("too_hot")
    if ma20_dev is not None and ma20_dev > 35 and not breakout60:
        hard_failed.append("ma20_overextended")
    if str(factor.get("symbol_name") or "").upper().find("ST") >= 0:
        hard_failed.append("st_name")

    strong_tags: List[str] = []
    identity_score = 0.0
    reasons: List[str] = []

    if board_count >= 3:
        strong_tags.append("连板股")
        identity_score += 42 + min(18, (board_count - 3) * 6)
        reasons.append(f"{board_count}连板")
    elif board_count == 2:
        strong_tags.append("连板股")
        identity_score += 36
        reasons.append("2连板")
    elif board_count == 1 and seal_strength >= 2.0:
        strong_tags.append("连板股")
        identity_score += 28
        reasons.append(f"首板封单{seal_strength:.1f}%")

    if breakout20:
        strong_tags.append("突破股")
        identity_score += 18
        reasons.append("20日突破")
    if breakout60:
        strong_tags.append("突破股")
        identity_score += 12
        reasons.append("60日突破")

    if weekly_score >= 65 and relative_score >= 60:
        strong_tags.append("趋势强股")
        identity_score += 18
        reasons.append(f"周线{weekly_score:.1f}/RS{relative_score:.1f}")
    elif weekly_score >= 60 and relative_score >= 55:
        strong_tags.append("趋势强股")
        identity_score += 12
        reasons.append("趋势确认")

    if close_above_ma5:
        identity_score += 8
        reasons.append("站上MA5")
    if ma5_slope is not None and ma5_slope > 0:
        identity_score += 6
        reasons.append("MA5上行")
    if volume_ratio is not None and volume_ratio >= 1.2:
        identity_score += 8
        reasons.append(f"量比{volume_ratio:.2f}")
    if amount_ratio is not None and amount_ratio >= 1.2:
        identity_score += 4
        reasons.append(f"额比{amount_ratio:.2f}")
    if sector_score >= 60:
        identity_score += 6
        reasons.append(f"板块{sector_score:.1f}")
    if stock_vs_sector is not None and stock_vs_sector >= 5:
        identity_score += 4
        reasons.append(f"强于板块{stock_vs_sector:.1f}")
    if rsi is not None and 45 <= rsi <= 75:
        identity_score += 3
    if change_pct is not None and change_pct > 15 and not strong_tags:
        identity_score -= 12
    if ma20_dev is not None and ma20_dev > 25 and not breakout60:
        identity_score -= 10
    if volume_ratio is not None and volume_ratio < 0.8:
        identity_score -= 5

    identity_score = _clamp(identity_score)
    if not strong_tags and identity_score >= 55:
        strong_tags.append("趋势强股" if weekly_score >= 60 else "突破股" if breakout20 else "连板股")

    if not strong_tags and identity_score < 50:
        strong_identity = "观察股"
    else:
        priority = ("连板股", "突破股", "趋势强股")
        strong_identity = next((tag for tag in priority if tag in strong_tags), strong_tags[0])

    return {
        "symbol_code": code,
        "strong_identity": strong_identity,
        "strong_tags": _normalize_reason_list(strong_tags),
        "strong_identity_score": round(identity_score, 2),
        "strong_identity_reasons": _normalize_reason_list(reasons),
        "board_count": board_count,
        "break_count": break_count,
        "seal_strength": round(seal_strength, 3),
        "one_word_limit_up": one_word_limit_up,
        "hard_failed": _normalize_reason_list(hard_failed),
    }


def score_divergence_quality(
    factor: Dict[str, Any],
    identity: Dict[str, Any],
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Score the divergence setup after strong-stock discovery."""
    market_context = market_context or {}
    strong_identity = str(identity.get("strong_identity") or "观察股")
    board_count = _int(identity.get("board_count"), 0)
    break_count = _int(identity.get("break_count"), 0)
    seal_strength = _num(identity.get("seal_strength"), 0.0) or 0.0

    change_pct = _num(factor.get("change_pct"))
    volume_ratio = _num(factor.get("volume_ratio"))
    amount_ratio = _num(factor.get("amount_ratio"))
    ma20_dev = _num(factor.get("ma20_deviation_pct"))
    weekly_score = _num(factor.get("weekly_trend_score"), 50.0) or 50.0
    relative_score = _num(factor.get("relative_strength_score"), 50.0) or 50.0
    sector_score = _num(factor.get("sector_score"), 50.0) or 50.0
    close_above_ma5 = _bool(factor.get("close_above_ma5"))
    ma5_slope = _num(factor.get("ma5_slope_pct"))
    rsi = _num(factor.get("rsi"))
    breakout20 = _bool(factor.get("breakout_20d"))
    breakout60 = _bool(factor.get("breakout_60d"))

    mode = "none"
    if strong_identity == "连板股" and board_count >= 1:
        if change_pct is not None and change_pct <= 0:
            mode = "首阴"
        elif change_pct is not None and change_pct < 9.5:
            mode = "断板"
    elif strong_identity in {"突破股", "趋势强股"}:
        if change_pct is not None and change_pct <= 0 and (close_above_ma5 or breakout20 or breakout60):
            mode = "首阴"
        elif change_pct is not None and change_pct < 7 and (breakout20 or breakout60 or weekly_score >= 65):
            mode = "断板"

    score = 0.0
    reasons: List[str] = []

    if mode == "首阴":
        score += 45
        reasons.append("首次阴线")
        if change_pct is not None and -5 <= change_pct <= 0:
            score += 12
        elif change_pct is not None and change_pct < -5:
            score -= 10
        if close_above_ma5:
            score += 10
        if ma5_slope is not None and ma5_slope > 0:
            score += 8
        if volume_ratio is not None and volume_ratio < 1.0:
            score += 8
        if amount_ratio is not None and amount_ratio < 1.0:
            score += 4
        if ma20_dev is not None and -2 <= ma20_dev <= 18:
            score += 8
        if sector_score >= 60:
            score += 8
        if 40 <= (rsi or 50) <= 70:
            score += 4
        if relative_score >= 60:
            score += 4
    elif mode == "断板":
        score += 40
        reasons.append("断板观察")
        if board_count >= 2:
            score += 10
        if break_count <= 1:
            score += 8
        else:
            score -= 8
        if seal_strength >= 5:
            score += 15
        elif seal_strength >= 2:
            score += 10
        if change_pct is not None and 0 <= change_pct <= 6:
            score += 10
        if volume_ratio is not None and 0.7 <= volume_ratio <= 1.4:
            score += 8
        if close_above_ma5:
            score += 5
        if ma5_slope is not None and ma5_slope > 0:
            score += 5
        if sector_score >= 60:
            score += 8
        if weekly_score >= 65:
            score += 4
        if relative_score >= 60:
            score += 4
    else:
        if strong_identity != "观察股":
            score += 28
            reasons.append("强势待观察")
        if breakout20 or breakout60:
            score += 8
        if close_above_ma5 and ma5_slope is not None and ma5_slope > 0:
            score += 8
        if sector_score >= 60:
            score += 6

    trend = str(market_context.get("market_trend") or "").lower()
    risk_sentiment = str(market_context.get("risk_sentiment") or "").lower()
    if trend == "down":
        score -= 8
        reasons.append("大盘下行")
    if risk_sentiment == "risk_off":
        score -= 8
        reasons.append("风险偏好下降")
    if risk_sentiment == "risk_on":
        score += 4

    score = _clamp(score)
    return {
        "divergence_mode": mode,
        "divergence_score": round(score, 2),
        "divergence_pass": bool(mode != "none" and score >= 60),
        "divergence_reasons": _normalize_reason_list(reasons),
    }


def score_entry_quality(
    factor: Dict[str, Any],
    trade_plan: Optional[Dict[str, Any]] = None,
    identity: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Score the actual actionable entry quality.

    只回答“这个价格值不值得买”。
    不允许放 VWAP / MA5 / 量比 / EMA 这些“资金转强确认”类信号，避免与
    weak_to_strong 重复计权；这些因子统一留给 weak_to_strong。
    """
    market_context = market_context or {}
    identity = identity or {}
    strong_identity = str(identity.get("strong_identity") or "观察股")
    sector_score = _num(factor.get("sector_score"), 50.0) or 50.0
    crowding_score = _num(factor.get("crowding_score"), 0.0) or 0.0
    ma20_dev = _num(factor.get("ma20_deviation_pct"))
    change_pct = _num(factor.get("change_pct"))
    close_vs_20h = _num(factor.get("close_vs_20d_high_pct"))

    score = 50.0
    reasons: List[str] = []

    if trade_plan and str(trade_plan.get("status") or "").lower() == "ok":
        plan = trade_plan.get("plan") or {}
        inds = trade_plan.get("indicators") or {}
        close = _num(trade_plan.get("close"))
        rr1 = _num(plan.get("rr_1"))
        stop_loss_pct = _num(plan.get("stop_loss_pct"))
        entry_low = _num(plan.get("entry_zone_low"))
        entry_high = _num(plan.get("entry_zone_high"))
        take_profit_1 = _num(plan.get("take_profit_1"))
        if entry_low is not None and entry_high is not None and close is not None:
            if entry_low <= close <= entry_high:
                score += 8
                reasons.append("位于入场区")
            else:
                score -= 6
                reasons.append("不在入场区")
        if rr1 is not None and rr1 >= 1.5:
            score += 12
            reasons.append(f"RR={rr1:.2f}")
        elif rr1 is not None and rr1 >= 1.2:
            score += 8
            reasons.append(f"RR={rr1:.2f}")
        elif rr1 is not None and rr1 < 1.0:
            score -= 12
            reasons.append(f"RR过低={rr1:.2f}")
        if stop_loss_pct is not None and -6.5 <= stop_loss_pct <= -2.5:
            score += 8
            reasons.append(f"止损合理{stop_loss_pct:.1f}%")
        elif stop_loss_pct is not None and stop_loss_pct < -8.0:
            score -= 6
            reasons.append(f"止损过宽{stop_loss_pct:.1f}%")
        if take_profit_1 is not None and close is not None:
            room_pct = (take_profit_1 / close - 1.0) * 100.0
            if 3 <= room_pct <= 12:
                score += 10
                reasons.append(f"目标空间{room_pct:.1f}%")
            elif room_pct < 2:
                score -= 8
                reasons.append("目标空间过近")
            elif room_pct > 20:
                score -= 4
                reasons.append(f"目标空间过大{room_pct:.1f}%")
        rsi = _num(inds.get("rsi"))
        if rsi is not None and 45 <= rsi <= 70:
            score += 4
            reasons.append(f"RSI={rsi:.0f}")
        elif rsi is not None and rsi > 80:
            score -= 6
            reasons.append("RSI过热")
        # 板块/拥挤是环境风险（不交给 weak_to_strong）
        if crowding_score >= 70:
            score -= 8
            reasons.append("板块拥挤")
        elif sector_score >= 60:
            score += 8
            reasons.append("板块强势")
        # 价格位置：涨幅、距前高、MA20偏离
        if change_pct is not None:
            if 0 <= change_pct <= 7:
                score += 6
                reasons.append(f"涨幅适中{change_pct:.1f}%")
            elif 7 < change_pct <= 9.5:
                score -= 5
                reasons.append("临近涨停再去追")
            elif change_pct > 9.5:
                score -= 10
                reasons.append("涨停附近买入风险大")
            elif change_pct < -2:
                score -= 8
                reasons.append("当日转弱")
        if close_vs_20h is not None and close_vs_20h <= -8:
            score -= 12
            reasons.append("距前高过远")
        elif close_vs_20h is not None and close_vs_20h >= -2:
            score += 8
            reasons.append("贴近前高")
        if ma20_dev is not None:
            if -3 <= ma20_dev <= 18:
                score += 6
                reasons.append(f"MA20偏离健康{ma20_dev:.1f}%")
            elif ma20_dev > 35:
                score -= 8
                reasons.append(f"MA20偏离过大{ma20_dev:.1f}%")
    else:
        # 无交易计划时仍要回答“价格值不值得买”，不含 VWAP/MA5/量比
        change_pct = change_pct or _num(factor.get("ret_1d_pct"))
        if change_pct is not None:
            if 0 <= change_pct <= 7:
                score += 6
                reasons.append(f"涨幅适中{change_pct:.1f}%")
            elif 7 < change_pct <= 9.5:
                score -= 5
                reasons.append("临近涨停再去追")
            elif change_pct > 9.5:
                score -= 10
                reasons.append("涨停附近追高")
            elif change_pct < -2:
                score -= 8
                reasons.append("当日弱势")
        if close_vs_20h is not None and close_vs_20h <= -8:
            score -= 12
            reasons.append("距前高过远")
        elif close_vs_20h is not None and close_vs_20h >= -2:
            score += 8
            reasons.append("贴近前高")
        if ma20_dev is not None:
            if -3 <= ma20_dev <= 18:
                score += 6
                reasons.append(f"MA20偏离正常{ma20_dev:.1f}%")
            elif ma20_dev > 35:
                score -= 8
                reasons.append(f"MA20偏离过大{ma20_dev:.1f}%")
        if crowding_score >= 70:
            score -= 8
            reasons.append("板块拥挤")
        elif sector_score >= 60:
            score += 6
            reasons.append("板块强势")
        if strong_identity == "连板股" and _int(identity.get("board_count"), 0) >= 2:
            score += 4
        if market_context.get("risk_sentiment") == "risk_off":
            score -= 5
        if market_context.get("market_trend") == "down":
            score -= 4

    score = _clamp(score)
    return {
        "entry_quality_score": round(score, 2),
        "entry_quality_pass": bool(score >= 70),
        "entry_quality_reasons": _normalize_reason_list(reasons),
    }


def score_weak_to_strong(
    factor: Dict[str, Any],
    trade_plan: Optional[Dict[str, Any]] = None,
    identity: Optional[Dict[str, Any]] = None,
    divergence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Score the weak-to-strong confirmation after the divergence setup.

    只回答“分歧后资金有没有重新转强”。
    不允许再引入 entry_quality / RR / 止损 / 目标空间 / 入场区这些
    “值不值得买”因子，避免与 entry_quality 重复计权。
    """
    reasons: List[str] = []
    volume_ratio = _num(factor.get("volume_ratio"))
    amount_ratio = _num(factor.get("amount_ratio"))
    close_above_ma5 = _bool(factor.get("close_above_ma5"))
    ma5_slope = _num(factor.get("ma5_slope_pct"))
    short_setup_score = _num(factor.get("short_setup_score"), 50.0) or 50.0
    hh_hl_strict = _bool(factor.get("hh_hl_strict")) or _bool(factor.get("hh_hl"))
    pullback_shrink = _bool(factor.get("pullback_shrink"))
    rising_volume = _bool(factor.get("rising_volume"))

    score = 50.0

    if trade_plan and str(trade_plan.get("status") or "").lower() == "ok":
        plan = trade_plan.get("plan") or {}
        inds = trade_plan.get("indicators") or {}
        close = _num(trade_plan.get("close"))
        vwap20 = _num(inds.get("vwap_20"))
        ema13 = _num(inds.get("ema13"))
        ema21 = _num(inds.get("ema21"))
        entry_trigger = str(plan.get("entry_trigger") or "")
        if close is not None and vwap20 is not None:
            if close >= vwap20:
                score += 18
                reasons.append("站上VWAP")
            else:
                score -= 12
                reasons.append("VWAP下方")
        if close is not None and ema13 is not None and close >= ema13:
            score += 10
            reasons.append("站上EMA13")
        if close is not None and ema21 is not None and close >= ema21:
            score += 8
            reasons.append("站上EMA21")
        if "回踩" in entry_trigger or "企稳" in entry_trigger:
            score += 8
            reasons.append("回踩企稳触发")
        if "VWAP" in entry_trigger:
            score += 6
            reasons.append("VWAP回踩触发")
    else:
        if close_above_ma5:
            score += 10
        if ma5_slope is not None and ma5_slope > 0:
            score += 10
        if volume_ratio is not None and 0.85 <= volume_ratio <= 1.8:
            score += 10
            reasons.append(f"量比健康{volume_ratio:.2f}")
        if amount_ratio is not None and amount_ratio >= 1.0:
            score += 5
            reasons.append("额比充足")
        if rising_volume and volume_ratio is not None and volume_ratio >= 1.0:
            score += 8
            reasons.append("上涨放量")
        if pullback_shrink:
            score += 8
            reasons.append("缩量回踩")
        if hh_hl_strict:
            score += 8
            reasons.append("HH/HL结构强")

    if short_setup_score >= 65:
        score += 8
        reasons.append("短线结构强")
    if close_above_ma5 or _bool(factor.get("close_above_ma5")):
        reasons.append("MA5之上")
    if ma5_slope is not None and ma5_slope > 0:
        reasons.append("MA5上行")
    if volume_ratio is not None and volume_ratio < 1.0:
        reasons.append("缩量回踩")

    score = _clamp(score)
    return {
        "weak_to_strong_score": round(score, 2),
        "weak_to_strong_pass": bool(score >= 80),
        "weak_to_strong_reasons": _normalize_reason_list(reasons),
    }


def evaluate_lifecycle(
    factor: Dict[str, Any],
    trade_plan: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None,
    zt_snapshot: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compose the full lifecycle assessment for a single stock."""
    identity = classify_strong_stock(factor, zt_snapshot=zt_snapshot)
    divergence = score_divergence_quality(factor, identity, market_context=market_context)
    factor_with_divergence = dict(factor)
    factor_with_divergence.update(divergence)
    entry = score_entry_quality(
        factor_with_divergence,
        trade_plan=trade_plan,
        identity=identity,
        market_context=market_context,
    )
    factor_with_entry = dict(factor_with_divergence)
    factor_with_entry.update(entry)
    weak_to_strong = score_weak_to_strong(
        factor_with_entry,
        trade_plan=trade_plan,
        identity=identity,
        divergence=divergence,
    )

    hard_failed = _normalize_reason_list(identity.get("hard_failed") or [])
    lifecycle_state = "观察池"
    if hard_failed:
        lifecycle_state = "过滤"
    elif identity["strong_identity"] != "观察股" and divergence["divergence_pass"]:
        if entry["entry_quality_pass"] and weak_to_strong["weak_to_strong_pass"]:
            lifecycle_state = "T+1买入候选"
        else:
            lifecycle_state = "等待分歧"
    elif identity["strong_identity"] != "观察股":
        lifecycle_state = "强势观察池"

    lifecycle_score = 0.4 * identity["strong_identity_score"] + 0.25 * divergence["divergence_score"] + 0.35 * weak_to_strong["weak_to_strong_score"]
    if hard_failed:
        lifecycle_score *= 0.35

    return {
        "hard_failed": hard_failed,
        "strong_identity": identity["strong_identity"],
        "strong_tags": identity["strong_tags"],
        "strong_identity_score": identity["strong_identity_score"],
        "strong_identity_reasons": identity["strong_identity_reasons"],
        "board_count": identity["board_count"],
        "break_count": identity["break_count"],
        "seal_strength": identity["seal_strength"],
        "one_word_limit_up": identity["one_word_limit_up"],
        "divergence_mode": divergence["divergence_mode"],
        "divergence_score": divergence["divergence_score"],
        "divergence_pass": divergence["divergence_pass"],
        "divergence_reasons": divergence["divergence_reasons"],
        "entry_quality_score": entry["entry_quality_score"],
        "entry_quality_pass": entry["entry_quality_pass"],
        "entry_quality_reasons": entry["entry_quality_reasons"],
        "weak_to_strong_score": weak_to_strong["weak_to_strong_score"],
        "weak_to_strong_pass": weak_to_strong["weak_to_strong_pass"],
        "weak_to_strong_reasons": weak_to_strong["weak_to_strong_reasons"],
        "lifecycle_state": lifecycle_state,
        "lifecycle_score": round(_clamp(lifecycle_score), 2),
        "buy_ready": bool(
            not hard_failed
            and identity["strong_identity"] != "观察股"
            and divergence["divergence_score"] >= 60
            and entry["entry_quality_score"] >= 70
            and weak_to_strong["weak_to_strong_score"] >= 80
        ),
    }
