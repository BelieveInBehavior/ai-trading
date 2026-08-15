"""市场���境���别器
���据指数走势、���交���、资���流向等���断当前市场状态（���市/震荡/���市）
"""

from typing import Dict, Any, List, Tuple
import pandas as pd
from datetime import datetime, timedelta


class MarketRegimeDetector:
    """���别市场环境：bull/neutral/bear"""

    def __init__(self):
        self.regime_cache: Dict[str, str] = {}

    def detect(
        self,
        market_context: Dict[str, Any],
        index_data: pd.DataFrame = None,
    ) -> Tuple[str, float, List[str]]:
        """
        检测市场环境

        Returns:
            (regime, confidence, reasons)
            regime: "bull" | "neutral" | "bear"
            confidence: 0-100
            reasons: 判���依据列表
        """
        signals = []
        bull_score = 0
        bear_score = 0

        # 1. 从market_context提取基础信号
        trend = market_context.get("market_trend", "neutral")
        risk_sentiment = market_context.get("risk_sentiment", "neutral")

        if trend == "up":
            bull_score += 20
            signals.append("市场���势向上")
        elif trend == "down":
            bear_score += 20
            signals.append("���场趋势向下")

        if risk_sentiment == "risk_on":
            bull_score += 15
            signals.append("���险偏好积极")
        elif risk_sentiment == "risk_off":
            bear_score += 15
            signals.append("避险情绪升���")

        # 2. 资金���向信号
        has_fund_flow = market_context.get("has_fund_flow_data", False)
        has_margin = market_context.get("has_margin_data", False)

        if has_fund_flow:
            # ���里可以后续扩展：���析个股���金流���的总体���流入/流出
            # 暂���给予中���权重
            signals.append("个股���金流数据可用")

        if has_margin:
            # 同���可扩展：融资余���增减���势
            signals.append("���资���券数据可用")

        # 3. 指数���术面���如���提供）
        if index_data is not None and not index_data.empty:
            regime_from_index, index_signals = self._analyze_index_technicals(index_data)
            if regime_from_index == "bull":
                bull_score += 25
            elif regime_from_index == "bear":
                bear_score += 25
            signals.extend(index_signals)

        # 4. 判断最终���态
        if bull_score > bear_score + 15:
            regime = "bull"
            confidence = min(100, bull_score * 1.5)
        elif bear_score > bull_score + 15:
            regime = "bear"
            confidence = min(100, bear_score * 1.5)
        else:
            regime = "neutral"
            confidence = 50 + abs(bull_score - bear_score) * 0.5

        return regime, confidence, signals

    def _analyze_index_technicals(
        self,
        df: pd.DataFrame
    ) -> Tuple[str, List[str]]:
        """
        分析指数技术���

        期���df包���：date, close, volume等���
        """
        signals = []

        if len(df) < 20:
            return "neutral", ["指数数据不���"]

        closes = df["close"].values
        latest = closes[-1]
        ma5 = closes[-5:].mean()
        ma10 = closes[-10:].mean()
        ma20 = closes[-20:].mean()

        # 均线多头/空头排列
        if ma5 > ma10 > ma20 and latest > ma5:
            signals.append("指数均���多���排列")
            return "bull", signals
        elif ma5 < ma10 < ma20 and latest < ma5:
            signals.append("���数均���空头���列")
            return "bear", signals

        # 简单涨跌���判断（���10日）
        if len(closes) >= 10:
            change_10d = (latest - closes[-10]) / closes[-10]
            if change_10d > 0.05:
                signals.append(f"���数���10日涨���{change_10d*100:.1f}%")
                return "bull", signals
            elif change_10d < -0.05:
                signals.append(f"指数���10���跌幅{abs(change_10d)*100:.1f}%")
                return "bear", signals

        signals.append("指���处于震荡")
        return "neutral", signals

    def get_adjusted_thresholds(
        self,
        regime: str,
        base_config: Dict[str, float]
    ) -> Dict[str, float]:
        """
        根据市场���境���整门槛

        Args:
            regime: bull/neutral/bear
            base_config: 基���配���字典

        Returns:
            ���整���的���置
        """
        adjusted = dict(base_config)

        if regime == "bull":
            # 牛���：降低���槛，允许更多标���入选
            adjusted["min_buy_score"] = max(50, adjusted.get("min_buy_score", 60) - 5)
            adjusted["min_weekly_trend_score"] = max(50, adjusted.get("min_weekly_trend_score", 55) - 3)
            adjusted["max_ma20_deviation_pct"] = adjusted.get("max_ma20_deviation_pct", 8) + 3
            adjusted["max_prev_day_gain_pct"] = adjusted.get("max_prev_day_gain_pct", 6) + 2

        elif regime == "bear":
            # 熊市：提高门槛，只选最���标的
            adjusted["min_buy_score"] = adjusted.get("min_buy_score", 60) + 10
            adjusted["min_weekly_trend_score"] = adjusted.get("min_weekly_trend_score", 55) + 5
            adjusted["min_relative_strength_score"] = adjusted.get("min_relative_strength_score", 50) + 5
            adjusted["max_ma20_deviation_pct"] = max(5, adjusted.get("max_ma20_deviation_pct", 8) - 2)
            adjusted["require_capital_flow_confirmation"] = True

        # neutral保持不���

        return adjusted


def format_regime_report(
    regime: str,
    confidence: float,
    reasons: List[str]
) -> str:
    """生成可���的市场���境报告"""
    regime_label = {
        "bull": "牛市/上涨���势",
        "neutral": "震荡市场",
        "bear": "熊市/���跌���势"
    }

    lines = [
        "=" * 60,
        "市场���境识���",
        "=" * 60,
        f"当前状态: {regime_label.get(regime, regime)}",
        f"置信度: {confidence:.1f}%",
        "",
        "判断依���:",
    ]

    for i, reason in enumerate(reasons, 1):
        lines.append(f"  {i}. {reason}")

    lines.append("=" * 60)
    return "\n".join(lines)
