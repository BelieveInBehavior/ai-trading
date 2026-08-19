"""Deterministic market-regime model for portfolio risk control."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pandas as pd


def _num(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result == result else None
    except (TypeError, ValueError):
        return None


class MarketRegimeDetector:
    """Classify bull/neutral/bear from price, breadth and liquidity evidence."""

    def detect(
        self,
        market_context: Dict[str, Any],
        index_data: pd.DataFrame | None = None,
    ) -> Tuple[str, float, List[str]]:
        context = market_context or {}
        score = 0.0
        reasons: List[str] = []

        if index_data is not None and not index_data.empty and "close" in index_data:
            closes = pd.to_numeric(index_data["close"], errors="coerce").dropna()
            if len(closes) >= 20:
                latest = float(closes.iloc[-1])
                ma5 = float(closes.tail(5).mean())
                ma20 = float(closes.tail(20).mean())
                return_5d = (latest / float(closes.iloc[-6]) - 1.0) * 100.0 if len(closes) >= 6 else 0.0
                if latest > ma5 > ma20:
                    score += 25
                    reasons.append("指数位于5日和20日均线上方")
                elif latest < ma5 < ma20:
                    score -= 25
                    reasons.append("指数位于5日和20日均线下方")
                score += max(-15.0, min(15.0, return_5d * 3.0))
                reasons.append(f"指数5日收益{return_5d:.2f}%")

        breadth = _num(context.get("advance_ratio"))
        if breadth is not None:
            breadth = breadth / 100.0 if breadth > 1 else breadth
            breadth_edge = (breadth - 0.5) * 60.0
            score += max(-20.0, min(20.0, breadth_edge))
            reasons.append(f"上涨家数占比{breadth * 100:.1f}%")

        limit_ratio = _num(context.get("limit_up_down_ratio"))
        if limit_ratio is not None:
            if limit_ratio >= 2:
                score += 10
            elif limit_ratio < 0.7:
                score -= 10
            reasons.append(f"涨跌停比{limit_ratio:.2f}")

        turnover_change = _num(context.get("market_turnover_change_pct"))
        if turnover_change is not None:
            trend = str(context.get("market_trend") or "neutral")
            direction = 1.0 if trend == "up" else -1.0 if trend == "down" else 0.0
            score += max(-10.0, min(10.0, turnover_change * 0.5 * direction))
            reasons.append(f"市场成交额变化{turnover_change:.1f}%")

        risk_sentiment = str(context.get("risk_sentiment") or "neutral").lower()
        if risk_sentiment == "risk_on":
            score += 12
            reasons.append("风险偏好上升")
        elif risk_sentiment == "risk_off":
            score -= 12
            reasons.append("风险偏好下降")

        if score >= 20:
            regime = "bull"
        elif score <= -20:
            regime = "bear"
        else:
            regime = "neutral"
        confidence = min(95.0, 50.0 + abs(score) * 0.8)
        if not reasons:
            reasons.append("市场广度和指数数据不足，按中性处理")
        return regime, round(confidence, 2), reasons


def format_regime_report(regime: str, confidence: float, reasons: List[str]) -> str:
    labels = {"bull": "风险偏好扩张", "neutral": "中性/震荡", "bear": "风险收缩"}
    lines = [f"市场环境: {labels.get(regime, regime)}", f"置信度: {confidence:.1f}%"]
    lines.extend(f"- {reason}" for reason in reasons)
    return "\n".join(lines)
