"""信号分级分类器
将候选���票分为A/B/C三个等���，对���不同的仓���策���
"""

from typing import Dict, List, Any, Tuple
from dataclasses import dataclass


@dataclass
class SignalTier:
    tier: str  # A/B/C
    confidence: float  # 0-100
    position_size_pct: float
    reasons: List[str]


class SignalTierClassifier:
    """根据多维度���标将���号分为A/B/C三���"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    def classify(
        self,
        signals: List[Dict[str, Any]],
        market_regime: str = "neutral"
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        将���号分级

        Returns:
            {
                "tier_A": [...],
                "tier_B": [...],
                "tier_C": [...],
                "tier_reject": [...]
            }
        """
        tiers = {
            "tier_A": [],
            "tier_B": [],
            "tier_C": [],
            "tier_reject": []
        }

        for signal in signals:
            tier_result = self._classify_single(signal, market_regime)
            tier_key = f"tier_{tier_result.tier}"

            enriched = dict(signal)
            enriched["signal_tier"] = tier_result.tier
            enriched["tier_confidence"] = tier_result.confidence
            enriched["recommended_position_size_pct"] = tier_result.position_size_pct
            enriched["tier_reasons"] = tier_result.reasons

            tiers[tier_key].append(enriched)

        return tiers

    def _classify_single(
        self,
        signal: Dict[str, Any],
        market_regime: str
    ) -> SignalTier:
        """单个信号分级"""
        score = signal.get("buy_score", 0)
        scorecard = signal.get("next_day_factor_scorecard", {})

        # ���取关���指标
        weekly_score = scorecard.get("weekly_trend_score", 0)
        rs_score = scorecard.get("relative_strength_score", 0)
        daily_score = scorecard.get("daily_entry_score", 0)
        catalyst_score = scorecard.get("catalyst_score", 0)
        flow_score = scorecard.get("capital_flow_score", 0)
        technical_score = scorecard.get("technical_score", 0)

        ma20_dev = scorecard.get("ma20_deviation_pct")
        prev_gain = scorecard.get("prev_day_gain_pct")

        primary_catalyst = scorecard.get("primary_catalyst", False)
        flow_available = scorecard.get("flow_data_available", False)

        # 计���置信���得分（0-100）
        confidence = self._calculate_confidence(
            weekly_score, rs_score, daily_score,
            catalyst_score, flow_score, technical_score,
            ma20_dev, prev_gain, primary_catalyst
        )

        reasons = []

        # A级���高确���性（多���度���势+催化���）
        if (
            score >= 70
            and confidence >= 75
            and weekly_score >= 60
            and rs_score >= 55
            and daily_score >= 55
            and (primary_catalyst or (catalyst_score >= 60 and flow_score >= 60))
            and (ma20_dev is None or ma20_dev <= 8)
            and (prev_gain is None or prev_gain <= 5)
        ):
            reasons.append(f"综合分{score:.1f}+置信度{confidence:.1f}")
            reasons.append(f"周线{weekly_score:.1f}/RS{rs_score:.1f}/日线{daily_score:.1f}")
            if primary_catalyst:
                reasons.append("主要催���剂确���")
            if flow_score >= 60:
                reasons.append(f"资金流确认{flow_score:.1f}")

            return SignalTier(
                tier="A",
                confidence=confidence,
                position_size_pct=15.0,
                reasons=reasons
            )

        # B级：标���信号���符���基本���槛���
        elif (
            score >= 60
            and confidence >= 60
            and weekly_score >= 55
            and rs_score >= 50
            and daily_score >= 50
            and (ma20_dev is None or ma20_dev <= 12)
            and (prev_gain is None or prev_gain <= 6)
        ):
            reasons.append(f"综���分{score:.1f}+置信���{confidence:.1f}")
            reasons.append(f"周���{weekly_score:.1f}/RS{rs_score:.1f}")
            if catalyst_score >= 55:
                reasons.append(f"���化剂{catalyst_score:.1f}")

            return SignalTier(
                tier="B",
                confidence=confidence,
                position_size_pct=8.0,
                reasons=reasons
            )

        # C���：观察���号（降���门槛，���需要密切���注）
        elif (
            score >= 50
            and confidence >= 50
            and weekly_score >= 50
            and rs_score >= 45
            and (ma20_dev is None or ma20_dev <= 15)
        ):
            reasons.append(f"���合���{score:.1f}���观察级）")
            reasons.append(f"周线{weekly_score:.1f}/RS{rs_score:.1f}")
            if daily_score < 50:
                reasons.append(f"日线���场分偏���{daily_score:.1f}")

            return SignalTier(
                tier="C",
                confidence=confidence,
                position_size_pct=5.0,
                reasons=reasons
            )

        # 拒绝
        else:
            reasons.append(f"综合分{score:.1f}不足")
            if weekly_score < 50:
                reasons.append(f"周线趋势���{weekly_score:.1f}")
            if rs_score < 45:
                reasons.append(f"相对���度弱{rs_score:.1f}")

            return SignalTier(
                tier="reject",
                confidence=confidence,
                position_size_pct=0.0,
                reasons=reasons
            )

    def _calculate_confidence(
        self,
        weekly_score: float,
        rs_score: float,
        daily_score: float,
        catalyst_score: float,
        flow_score: float,
        technical_score: float,
        ma20_dev: float | None,
        prev_gain: float | None,
        primary_catalyst: bool
    ) -> float:
        """
        计算信号���信度���0-100）

        置信度 = 趋势一���性 + 催化剂强度 + 技术位置 + ���金确认
        """
        confidence = 50.0  # ���础分

        # 1. 趋势一���性（最高+20分���
        trend_consistency = min(weekly_score, rs_score, daily_score)
        if trend_consistency >= 60:
            confidence += 20
        elif trend_consistency >= 55:
            confidence += 15
        elif trend_consistency >= 50:
            confidence += 10

        # 2. 催化剂强度（最���+15分）
        if primary_catalyst:
            confidence += 15
        elif catalyst_score >= 60:
            confidence += 12
        elif catalyst_score >= 55:
            confidence += 8

        # 3. 技���位置（最���+10分���
        if ma20_dev is not None:
            if 0 <= ma20_dev <= 5:  # 理想位置
                confidence += 10
            elif 5 < ma20_dev <= 8:
                confidence += 5
            elif ma20_dev < 0 or ma20_dev > 12:
                confidence -= 5

        # 4. 资金确认（最高+10分）
        if flow_score >= 60:
            confidence += 10
        elif flow_score >= 55:
            confidence += 5

        # 5. 防追���惩罚
        if prev_gain is not None and prev_gain > 6:
            confidence -= (prev_gain - 6) * 2

        return max(0.0, min(100.0, confidence))

    def get_tier_summary(self, tiers: Dict[str, List[Dict[str, Any]]]) -> str:
        """生成分级摘要"""
        lines = [
            "=" * 60,
            "���号分���结���",
            "=" * 60,
        ]

        for tier_name in ["tier_A", "tier_B", "tier_C"]:
            tier_list = tiers.get(tier_name, [])
            tier_label = tier_name.split("_")[1]

            if not tier_list:
                lines.append(f"{tier_label}级���高确定性���: 0个")
                continue

            lines.append(f"\n{tier_label}级���号 ({len(tier_list)}个):")
            for i, signal in enumerate(tier_list, 1):
                name = signal.get("symbol_name", "")
                code = signal.get("symbol_code", "")
                score = signal.get("buy_score", 0)
                confidence = signal.get("tier_confidence", 0)
                position = signal.get("recommended_position_size_pct", 0)

                lines.append(
                    f"  {i}. {name}({code}) | "
                    f"分数{score:.1f} | 置���度{confidence:.1f} | "
                    f"建议仓位{position:.1f}%"
                )

                reasons = signal.get("tier_reasons", [])
                if reasons:
                    lines.append(f"     理���: {' | '.join(reasons[:3])}")

        lines.append("=" * 60)
        return "\n".join(lines)
