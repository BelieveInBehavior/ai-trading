"""Forward-opportunity signal allocation and risk sizing.

The class name is kept for the existing pipeline contract, but the legacy
weekly-trend/relative-strength tier gates have intentionally been removed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from utils.strong_stock_lifecycle import evaluate_lifecycle


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if result == result else default
    except (TypeError, ValueError):
        return default


@dataclass
class SignalTier:
    tier: str
    confidence: float
    position_size_pct: float
    reasons: List[str]


@dataclass
class AllocationConfig:
    min_buy_score: float = 60.0
    high_conviction_score: float = 80.0
    min_net_edge_pct: float = 0.20
    high_net_edge_pct: float = 0.80
    min_data_quality_score: float = 50.0
    min_identity_score: float = 55.0
    min_divergence_score: float = 60.0
    min_entry_quality_score: float = 70.0
    min_weak_to_strong_score: float = 80.0
    risk_budget_pct: float = 0.60
    min_position_pct: float = 30.0
    max_position_pct: float = 50.0
    max_high_conviction_position_pct: float = 70.0


class SignalTierClassifier:
    """Allocate passed signals using forward edge and volatility-aware risk."""

    def __init__(self, config: Dict[str, Any] | AllocationConfig | None = None):
        if isinstance(config, AllocationConfig):
            self.config = config
        elif isinstance(config, dict):
            allowed = AllocationConfig.__dataclass_fields__
            self.config = AllocationConfig(**{k: v for k, v in config.items() if k in allowed})
        else:
            self.config = AllocationConfig()

    def classify(
        self,
        signals: List[Dict[str, Any]],
        market_regime: str = "neutral",
    ) -> Dict[str, List[Dict[str, Any]]]:
        tiers = {"tier_A": [], "tier_B": [], "tier_C": [], "tier_reject": []}
        for signal in signals or []:
            result = self._classify_single(signal, market_regime)
            enriched = dict(signal)
            enriched.update(
                {
                    "signal_tier": result.tier,
                    "tier_confidence": result.confidence,
                    "recommended_position_size_pct": result.position_size_pct,
                    "tier_reasons": result.reasons,
                    "allocation_model": "forward-edge-risk-v1",
                    "recommended_holding_days": _holding_days(signal),
                    "holding_rule": _holding_rule(signal),
                }
            )
            tiers[f"tier_{result.tier}"].append(enriched)
        return tiers

    def _classify_single(self, signal: Dict[str, Any], market_regime: str) -> SignalTier:
        cfg = self.config
        scorecard = signal.get("next_day_factor_scorecard") or {}
        gate = signal.get("next_day_gate_report") or {}
        lifecycle = signal.get("strong_stock_lifecycle")
        if not isinstance(lifecycle, dict):
            lifecycle = evaluate_lifecycle(
                signal.get("technical_factor") or signal,
                trade_plan=signal.get("trade_plan"),
                market_context=signal.get("market_context") or {},
            )
        lifecycle_identity = str(lifecycle.get("strong_identity") or "观察股")
        lifecycle_identity_score = _number(lifecycle.get("strong_identity_score"), 0.0)
        lifecycle_divergence = _number(lifecycle.get("divergence_score"), 0.0)
        lifecycle_entry = _number(lifecycle.get("entry_quality_score"), 0.0)
        lifecycle_weak = _number(lifecycle.get("weak_to_strong_score"), 0.0)
        lifecycle_buy_ready = bool(lifecycle.get("buy_ready"))
        forward_score = _number(
            scorecard.get("forward_opportunity_score", signal.get("buy_score")),
            0.0,
        )
        net_edge = _number(
            signal.get("expected_net_edge_pct", signal.get("expected_return_t1_pct")),
            0.0,
        )
        data_quality = _number(scorecard.get("data_quality_score"), 0.0)
        probability = _number(signal.get("probability_value"), 0.5)
        volatility = max(
            1.0,
            _number(
                signal.get("expected_downside_pct")
                or scorecard.get("atr_pct")
                or scorecard.get("daily_volatility_20d_pct"),
                4.0,
            ),
        )
        risk_flags = list(signal.get("risk_flags") or [])
        passed = bool(gate.get("passed", True))

        if lifecycle_identity != "观察股":
            return self._classify_lifecycle(signal, lifecycle, market_regime)

        reasons = [
            f"前瞻机会分{forward_score:.1f}",
            f"预期净收益{net_edge:.2f}%",
            f"预估下行{volatility:.2f}%",
        ]
        if not passed or risk_flags:
            reasons.extend(str(x) for x in (gate.get("failed_reasons") or risk_flags)[:3])
            return SignalTier("reject", 0.0, 0.0, reasons)
        if data_quality < cfg.min_data_quality_score:
            reasons.append(f"数据质量不足{data_quality:.1f}")
            return SignalTier("reject", 0.0, 0.0, reasons)

        position = cfg.risk_budget_pct / volatility * 100.0
        regime_multiplier = {"bull": 1.10, "neutral": 1.0, "bear": 0.65}.get(
            str(market_regime).lower(),
            1.0,
        )
        edge_multiplier = max(0.65, min(1.35, 0.75 + max(0.0, net_edge) / 2.0))
        position *= regime_multiplier * edge_multiplier

        confidence = (
            forward_score * 0.55
            + max(0.0, min(100.0, probability * 100.0)) * 0.20
            + data_quality * 0.15
            + max(0.0, min(100.0, 50.0 + net_edge * 20.0)) * 0.10
        )
        confidence = max(0.0, min(100.0, confidence))

        daily_entry = _number(scorecard.get("daily_entry_score"), 0.0)
        technical = _number(scorecard.get("technical_score"), 0.0)
        quant_score = _number(
            signal.get("quantitative_score")
            or (signal.get("quantitative_screen") or {}).get("forward_opportunity_score")
            or (signal.get("quantitative_screen") or {}).get("opportunity_rank_score"),
            0.0,
        )
        # 2026-08-16 tuning: A/B should not be gated only by T+1 expected net
        # edge.  A strong daily-entry/technical structure is also executable even
        # if expected T1 is small/negative (the payoff often comes T3/T5).
        if forward_score >= cfg.high_conviction_score and net_edge >= cfg.high_net_edge_pct:
            position = max(cfg.min_position_pct, min(cfg.max_high_conviction_position_pct, position))
            reasons.append("高前瞻收益+风控通过")
            return SignalTier("A", round(confidence, 2), round(position, 2), reasons)
        if forward_score >= cfg.min_buy_score and (
            net_edge >= cfg.min_net_edge_pct or daily_entry >= 65.0 or technical >= 55.0 or quant_score >= 70.0
        ):
            position = max(cfg.min_position_pct, min(cfg.max_position_pct, position))
            reasons.append("前瞻机会+买点/技术/量化确认")
            return SignalTier("B", round(confidence, 2), round(position, 2), reasons)

        reasons.append("净收益或机会分尚未达到执行门槛")
        return SignalTier("C", round(confidence, 2), 0.0, reasons)

    def _classify_lifecycle(self, signal: Dict[str, Any], lifecycle: Dict[str, Any], market_regime: str) -> SignalTier:
        cfg = self.config
        scorecard = signal.get("next_day_factor_scorecard") or {}
        gate = signal.get("next_day_gate_report") or {}
        risk_flags = list(signal.get("risk_flags") or [])
        passed = bool(gate.get("passed", True))
        strong_identity = str(lifecycle.get("strong_identity") or "观察股")
        identity_score = _number(lifecycle.get("strong_identity_score"), 0.0)
        divergence_score = _number(lifecycle.get("divergence_score"), 0.0)
        entry_quality = _number(lifecycle.get("entry_quality_score"), 0.0)
        weak_to_strong = _number(lifecycle.get("weak_to_strong_score"), 0.0)
        buy_ready = bool(lifecycle.get("buy_ready"))
        lifecycle_state = str(lifecycle.get("lifecycle_state") or "观察池")
        probability = _number(signal.get("probability_value"), 0.5)
        forward_score = _number(scorecard.get("forward_opportunity_score", signal.get("buy_score")), 0.0)
        volatility = max(
            1.0,
            _number(
                signal.get("expected_downside_pct")
                or scorecard.get("atr_pct")
                or scorecard.get("daily_volatility_20d_pct"),
                4.0,
            ),
        )

        reasons = [
            f"生命周期={lifecycle_state}",
            f"强势={strong_identity}/{identity_score:.1f}",
            f"分歧={divergence_score:.1f}",
            f"入场={entry_quality:.1f}",
            f"转强={weak_to_strong:.1f}",
        ]
        if not passed or risk_flags or lifecycle.get("hard_failed"):
            reasons.extend(str(x) for x in (gate.get("failed_reasons") or risk_flags or lifecycle.get("hard_failed") or [])[:3])
            return SignalTier("reject", 0.0, 0.0, reasons)

        # 金融口径风险预算：仓位与波动率成反比（risk_budget / volatility）。
        position = 30.0 + max(0.0, min(25.0, (weak_to_strong - 80.0) * 1.0 + (entry_quality - 70.0) * 0.5))
        position = position * (1.0 / max(1.0, volatility / 4.0))
        regime_multiplier = {"bull": 1.10, "neutral": 1.0, "bear": 0.65}.get(str(market_regime).lower(), 1.0)
        position *= regime_multiplier

        confidence = (
            identity_score * 0.30
            + divergence_score * 0.25
            + entry_quality * 0.25
            + weak_to_strong * 0.20
        )
        confidence = max(0.0, min(100.0, confidence))

        if buy_ready and identity_score >= cfg.min_identity_score and divergence_score >= cfg.min_divergence_score and entry_quality >= cfg.min_entry_quality_score and weak_to_strong >= cfg.min_weak_to_strong_score:
            position = max(cfg.max_position_pct, min(cfg.max_high_conviction_position_pct, position))
            reasons.append("强势身份+分歧/转强/入场全通过")
            return SignalTier("A", round(confidence, 2), round(position, 2), reasons)

        if strong_identity != "观察股" and (
            divergence_score >= cfg.min_divergence_score
            or entry_quality >= cfg.min_entry_quality_score
            or weak_to_strong >= cfg.min_weak_to_strong_score
            or forward_score >= cfg.min_buy_score
        ):
            position = max(cfg.min_position_pct, min(cfg.max_position_pct, position))
            reasons.append("强势观察，等待确认")
            return SignalTier("B", round(confidence, 2), round(position, 2), reasons)

        reasons.append("仍处观察池")
        return SignalTier("C", round(confidence, 2), 0.0, reasons)

    def get_tier_summary(self, tiers: Dict[str, List[Dict[str, Any]]]) -> str:
        lines = ["=" * 60, "前瞻机会与风险分级", "=" * 60]
        for tier_name in ("tier_A", "tier_B", "tier_C", "tier_reject"):
            items = tiers.get(tier_name) or []
            label = tier_name.split("_", 1)[1]
            lines.append(f"{label}级: {len(items)}个")
            for signal in items:
                lifecycle = signal.get("strong_stock_lifecycle") or {}
                lines.append(
                    f"  {signal.get('symbol_name', '')}({signal.get('symbol_code', '')}) | "
                    f"机会分{_number(signal.get('buy_score')):.1f} | "
                    f"强势{lifecycle.get('strong_identity', '')} | "
                    f"仓位{_number(signal.get('recommended_position_size_pct')):.1f}%"
                )
        return "\n".join(lines)


def _holding_days(signal: dict) -> int:
    """T+1~T+2 优先；仅当入场质量高且板块不极端拥挤时允许 T+3。"""
    lifecycle = signal.get("strong_stock_lifecycle") or {}
    entry_quality = _number(lifecycle.get("entry_quality_score"), 50.0)
    weak_to_strong = _number(lifecycle.get("weak_to_strong_score"), 50.0)
    if entry_quality >= 70.0 and weak_to_strong >= 80.0:
        return 3
    return 2


def _holding_rule(signal: dict) -> str:
    lifecycle = signal.get("strong_stock_lifecycle") or {}
    entry_quality = _number(lifecycle.get("entry_quality_score"), 50.0)
    weak_to_strong = _number(lifecycle.get("weak_to_strong_score"), 50.0)
    if entry_quality >= 70.0 and weak_to_strong >= 80.0:
        return "T+3_ok"
    return "T+1_2_fast_exit"
