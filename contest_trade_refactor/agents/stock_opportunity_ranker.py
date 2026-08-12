"""
Stock opportunity ranking engine.

Goal:
- Convert loosely-structured research signals into tradable ranked opportunities.
- Prefer precision over recall: if confidence is weak, do not recommend buy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import math
import re

from agents.signal_schema import validate_buy_decision


@dataclass
class RankerConfig:
    top_k: int = 8
    min_buy_score: float = 60.0
    min_probability: float = 0.55
    min_tradeability_score: float = 55.0
    min_risk_reward_score: float = 50.0
    min_data_quality_score: float = 45.0
    min_technical_score: float = 45.0
    max_prev_day_gain_pct: float = 6.0
    max_ma20_deviation_pct: float = 8.0
    min_flow_confirmation_score: float = 55.0
    min_regime_confirmation_score: float = 52.0
    enforce_flow_confirmation_if_available: bool = True
    freshness_half_life_hours: int = 18
    max_evidence_points: int = 25
    limitation_penalty_cap: int = 15
    expected_return_floor_pct: float = 0.3
    reject_future_evidence: bool = True
    risk_veto_enabled: bool = True
    enforce_multi_timeframe: bool = False
    min_weekly_trend_score: float = 55.0
    min_relative_strength_score: float = 50.0
    min_relative_strength_20d_pct: float = 0.0
    min_daily_entry_score: float = 50.0
    probability_calibration_path: str = "agents_workspace/models/probability_calibration.json"


class StockOpportunityRanker:
    """Score and rank stock opportunities from research signals."""

    BUY_ACTION_KEYWORDS = ["buy", "long", "加仓", "买入", "增持", "做多"]
    SELL_ACTION_KEYWORDS = ["sell", "short", "减仓", "卖出", "做空", "回避"]

    BULLISH_KEYWORDS = [
        "超预期", "回购", "增持", "中标", "订单", "提价", "扩产", "景气", "增长", "改善", "上修", "利好",
        "主力吸筹", "主力净流入", "融资净买入", "溢价成交", "封单极强", "空头回补",
    ]
    BEARISH_KEYWORDS = [
        "下修", "暴雷", "违约", "减持", "诉讼", "处罚", "亏损", "下滑", "利空", "风险", "承压",
        "主力净流出", "主力出货", "融资净偿还", "大幅折价", "封单偏弱",
    ]

    HIGH_CREDIBILITY_SOURCES = [
        "证监会", "上交所", "深交所", "北交所", "公司公告", "交易所", "财政部", "央行",
        "individual_fund_flow", "margin_trading", "block_trade", "zt_seal_strength",
    ]
    LOW_CREDIBILITY_SOURCES = ["论坛", "微博", "传闻", "自媒体", "匿名"]

    CATALYST_KEYWORDS = [
        "定增", "回购", "分红", "业绩", "预增", "重组", "并购", "政策", "降准", "降息", "获批", "中标", "指引",
    ]
    CAPITAL_FLOW_KEYWORDS = [
        "净买入", "龙虎榜", "北向", "资金流入", "机构", "游资", "增持", "获配", "成交额",
        "主力净流入", "主力吸筹", "超大单净流入", "连续主力资金流入",
        "融资净买入", "融资余额增", "空头回补", "融券偿还",
        "大宗交易溢价", "溢价成交", "大宗买入",
        "封单极强", "封单强度", "封单额",
        "板块资金净流入", "板块连续流入",
    ]
    PRIMARY_CATALYST_KEYWORDS = [
        "业绩预增", "上修", "并购", "重组", "回购", "分红", "中标", "获批", "政策落地", "订单超预期",
    ]

    TECHNICAL_BULLISH_KEYWORDS = [
        "均线多头", "均线多头排列", "金叉", "站上5日线", "站上10日线", "站上20日线",
        "放量突破", "突破前高", "趋势向上", "沿5日线", "macd金叉", "rsi回升",
    ]
    TECHNICAL_BEARISH_KEYWORDS = [
        "均线空头", "均线空头排列", "死叉", "跌破5日线", "跌破10日线", "跌破20日线",
        "放量下跌", "冲高回落", "趋势转弱", "macd死叉", "rsi超买", "破位",
    ]
    HARD_RISK_KEYWORDS = [
        "财务造假", "暴雷", "违约", "退市", "立案调查", "停牌核查",
        "无法交易", "跌停", "重大诉讼", "数据缺失", "无法实时核对",
        "代码推断", "代码识别风险", "需再确认",
    ]
    HARD_DATA_QUALITY_TAGS = {"tool_error", "code_uncertain", "missing_price"}

    def __init__(self, config: Optional[RankerConfig] = None):
        self.config = config or RankerConfig()
        self.calibration = self._load_probability_calibration()

    def rank_signals(
        self,
        research_signals: List[Dict[str, Any]],
        trigger_time: str,
        market_context: Optional[Dict[str, Any]] = None,
        system_health: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not research_signals:
            return []

        scored = self.score_signals(
            research_signals=research_signals,
            trigger_time=trigger_time,
            market_context=market_context,
            system_health=system_health,
        )

        merged = self._merge_same_symbol(scored)
        merged.sort(key=lambda x: x["buy_score"], reverse=True)

        selected = [
            item for item in merged
            if self._passes_next_day_buy_gates(item)
        ]
        return selected[: self.config.top_k]

    def build_watchlist(
        self,
        research_signals: List[Dict[str, Any]],
        trigger_time: str,
        market_context: Optional[Dict[str, Any]] = None,
        system_health: Optional[Dict[str, Any]] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        scored = self.score_signals(
            research_signals=research_signals,
            trigger_time=trigger_time,
            market_context=market_context,
            system_health=system_health,
        )
        merged = self._merge_same_symbol(scored)
        merged.sort(key=lambda x: x.get("buy_score", 0), reverse=True)
        for item in merged:
            gate = item.get("next_day_gate_report") or {}
            item["buy_decision"] = "buy" if gate.get("passed") else "watch"
        watchable = [
            item for item in merged
            if not self._is_hard_watchlist_reject(item)
        ]
        return watchable[:top_k]

    def score_signals(
        self,
        research_signals: List[Dict[str, Any]],
        trigger_time: str,
        market_context: Optional[Dict[str, Any]] = None,
        system_health: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        scored = []
        for signal in research_signals:
            scored_signal = self._score_single_signal(
                signal=signal,
                trigger_time=trigger_time,
                market_context=market_context,
                system_health=system_health,
            )
            if scored_signal:
                scored.append(scored_signal)
        return scored

    def _score_single_signal(
        self,
        signal: Dict[str, Any],
        trigger_time: str,
        market_context: Optional[Dict[str, Any]] = None,
        system_health: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        symbol_code = (signal.get("symbol_code") or "").strip()
        symbol_name = (signal.get("symbol_name") or "").strip()
        if not symbol_code and not symbol_name:
            return None

        has_opportunity = self._bool_like(signal.get("has_opportunity"))
        action = str(signal.get("action") or "").strip().lower()

        action_score, action_reason = self._score_action(action)
        probability_raw = self._parse_probability(signal.get("probability"))
        probability_value = self._calibrate_probability(probability_raw)

        evidence_list = signal.get("evidence_list") or []
        evidence_score, evidence_reason = self._score_evidence_quality(evidence_list, trigger_time)
        direction_score, direction_reason = self._score_direction_bias(evidence_list)
        source_score, source_reason = self._score_source_credibility(evidence_list)

        limitation_penalty = self._score_limitations(signal.get("limitations") or [])
        opportunity_bonus = 8 if has_opportunity else -12
        consensus_score, consensus_reason = self._score_consensus(signal)

        probability_score = (probability_value - 0.5) * 80
        base_score = 50

        total = (
            base_score
            + action_score
            + opportunity_bonus
            + probability_score
            + evidence_score
            + direction_score
            + source_score
            - limitation_penalty
            + consensus_score
        )

        if self._is_non_tradable_name(symbol_name):
            total -= 20

        total = max(0.0, min(100.0, total))

        catalyst_score, catalyst_reason = self._score_catalyst_strength(evidence_list, trigger_time)
        capital_flow_score, capital_flow_reason = self._score_capital_flow_strength(evidence_list)
        market_regime_score, market_regime_reason = self._score_market_regime(market_context)
        flow_data_available = bool((market_context or {}).get("has_sector_flow_data", False))
        tradeability_score, tradeability_reason = self._score_tradeability(symbol_code, symbol_name, action)
        risk_reward_score, risk_reward_reason = self._score_risk_reward(
            signal=signal,
            probability_value=probability_value,
            direction_score=direction_score,
            limitations=signal.get("limitations") or [],
        )
        data_quality_score, data_quality_reason = self._score_data_quality(
            signal=signal,
            evidence_list=evidence_list,
            system_health=system_health,
            trigger_time=trigger_time,
        )
        technical_score, technical_reason = self._score_technical_setup(signal, evidence_list)
        weekly_trend_score, weekly_trend_reason, weekly_data_available = self._score_weekly_trend(signal)
        relative_strength_score, relative_strength_reason, relative_strength_available = (
            self._score_relative_strength(signal)
        )
        daily_entry_score, daily_entry_reason, daily_data_available = self._score_daily_entry(
            signal,
            technical_score,
        )
        prev_day_gain_pct = self._extract_prev_day_gain_pct(signal, evidence_list)
        ma20_deviation_pct = self._extract_ma20_deviation_pct(signal, evidence_list)
        primary_catalyst = self._is_primary_catalyst(signal, evidence_list, catalyst_score)
        future_evidence_count = self._count_future_evidence(evidence_list, trigger_time)

        total += (technical_score - 50.0) * 0.12
        total += (weekly_trend_score - 50.0) * 0.16
        total += (relative_strength_score - 50.0) * 0.16
        total += (daily_entry_score - 50.0) * 0.08
        total = max(0.0, min(100.0, total))

        expected_return_t1 = self._estimate_expected_return_t1(
            probability=probability_value,
            catalyst_score=catalyst_score,
            capital_flow_score=capital_flow_score,
            market_regime_score=market_regime_score,
            tradeability_score=tradeability_score,
            risk_reward_score=risk_reward_score,
            data_quality_score=data_quality_score,
            technical_score=technical_score,
            weekly_trend_score=weekly_trend_score,
            relative_strength_score=relative_strength_score,
            daily_entry_score=daily_entry_score,
        )
        risk_veto_report = self._evaluate_risk_veto(
            signal=signal,
            symbol_name=symbol_name,
            action=action,
            evidence_list=evidence_list,
            future_evidence_count=future_evidence_count,
        )

        reasons = [
            action_reason,
            f"prob_raw={probability_raw:.2f}",
            f"prob_cal={probability_value:.2f}",
            evidence_reason,
            direction_reason,
            source_reason,
            consensus_reason,
            f"limitation_penalty={limitation_penalty}",
        ]

        scorecard = {
            "catalyst_score": round(catalyst_score, 2),
            "capital_flow_score": round(capital_flow_score, 2),
            "market_regime_score": round(market_regime_score, 2),
            "tradeability_score": round(tradeability_score, 2),
            "risk_reward_score": round(risk_reward_score, 2),
            "data_quality_score": round(data_quality_score, 2),
            "technical_score": round(technical_score, 2),
            "weekly_trend_score": round(weekly_trend_score, 2),
            "relative_strength_score": round(relative_strength_score, 2),
            "daily_entry_score": round(daily_entry_score, 2),
            "prev_day_gain_pct": round(prev_day_gain_pct, 3) if prev_day_gain_pct is not None else None,
            "ma20_deviation_pct": round(ma20_deviation_pct, 3) if ma20_deviation_pct is not None else None,
            "future_evidence_count": future_evidence_count,
            "consensus_score": round(consensus_score, 2),
            "flow_data_available": flow_data_available,
            "primary_catalyst": primary_catalyst,
            "risk_veto_report": risk_veto_report,
            "catalyst_reason": catalyst_reason,
            "capital_flow_reason": capital_flow_reason,
            "market_regime_reason": market_regime_reason,
            "tradeability_reason": tradeability_reason,
            "risk_reward_reason": risk_reward_reason,
            "data_quality_reason": data_quality_reason,
            "technical_reason": technical_reason,
            "weekly_trend_reason": weekly_trend_reason,
            "relative_strength_reason": relative_strength_reason,
            "daily_entry_reason": daily_entry_reason,
            "weekly_data_available": weekly_data_available,
            "relative_strength_available": relative_strength_available,
            "daily_data_available": daily_data_available,
        }

        gate_report = self._evaluate_gate_report(
            buy_score=total,
            probability_value=probability_value,
            tradeability_score=tradeability_score,
            risk_reward_score=risk_reward_score,
            data_quality_score=data_quality_score,
            technical_score=technical_score,
            capital_flow_score=capital_flow_score,
            market_regime_score=market_regime_score,
            flow_data_available=flow_data_available,
            weekly_trend_score=weekly_trend_score,
            relative_strength_score=relative_strength_score,
            relative_strength_20d_pct=self._extract_relative_strength_20(signal),
            daily_entry_score=daily_entry_score,
            weekly_data_available=weekly_data_available,
            relative_strength_available=relative_strength_available,
            daily_data_available=daily_data_available,
            prev_day_gain_pct=prev_day_gain_pct,
            ma20_deviation_pct=ma20_deviation_pct,
            primary_catalyst=primary_catalyst,
            expected_return_t1=expected_return_t1,
            future_evidence_count=future_evidence_count,
            risk_veto_report=risk_veto_report,
        )

        result = dict(signal)
        result.update(
            {
                "buy_score": round(total, 2),
                "probability_value": round(probability_value, 4),
                "probability_raw": round(probability_raw, 4),
                "probability_calibration": self.calibration,
                "expected_return_t1_pct": round(expected_return_t1, 3),
                "next_day_factor_scorecard": scorecard,
                "next_day_gate_report": gate_report,
                "buy_decision": "buy" if gate_report["passed"] else "watch",
                "entry_timing": "next_trading_day_open",
                "analysis_as_of_date": self._analysis_as_of_date(trigger_time),
                "risk_flags": risk_veto_report["risk_flags"],
                "risk_veto_report": risk_veto_report,
                "selection_basis": "ranked_gate_and_risk_veto",
                "opportunity_reason": " | ".join([r for r in reasons if r]),
                "score_components": {
                    "action_score": round(action_score, 2),
                    "opportunity_bonus": opportunity_bonus,
                    "probability_score": round(probability_score, 2),
                    "evidence_score": round(evidence_score, 2),
                    "direction_score": round(direction_score, 2),
                    "source_score": round(source_score, 2),
                    "limitation_penalty": round(limitation_penalty, 2),
                    "consensus_score": round(consensus_score, 2),
                    "weekly_trend_score": round(weekly_trend_score, 2),
                    "relative_strength_score": round(relative_strength_score, 2),
                    "daily_entry_score": round(daily_entry_score, 2),
                },
            }
        )
        return validate_buy_decision(result)

    def _merge_same_symbol(self, signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for sig in signals:
            key = (sig.get("symbol_code") or sig.get("symbol_name") or "").strip()
            if not key:
                continue
            grouped.setdefault(key, []).append(sig)

        merged = []
        for _, group in grouped.items():
            group = sorted(group, key=lambda x: x.get("buy_score", 0), reverse=True)
            best = dict(group[0])
            if len(group) > 1:
                avg_score = sum(g.get("buy_score", 0) for g in group) / len(group)
                avg_prob = sum(g.get("probability_value", 0.5) for g in group) / len(group)
                avg_er = sum(g.get("expected_return_t1_pct", 0.0) for g in group) / len(group)
                best["buy_score"] = round(0.65 * best["buy_score"] + 0.35 * avg_score, 2)
                best["probability_value"] = round(0.6 * best["probability_value"] + 0.4 * avg_prob, 4)
                best["expected_return_t1_pct"] = round(0.6 * best.get("expected_return_t1_pct", 0.0) + 0.4 * avg_er, 3)
                best["supporting_signal_count"] = len(group)
            else:
                best["supporting_signal_count"] = max(
                    1,
                    int(best.get("supporting_signal_count", 1) or 1),
                )
            gate_report = best.get("next_day_gate_report") or {}
            best["buy_decision"] = "buy" if gate_report.get("passed") else "watch"
            merged.append(best)

        return merged

    def _score_consensus(self, signal: Dict[str, Any]) -> Tuple[float, str]:
        report = signal.get("consensus_report")
        if not isinstance(report, dict):
            return 0.0, "consensus=none"

        action = str(report.get("consensus_action") or "watch")
        confidence = self._parse_optional_ratio(report.get("consensus_confidence"))
        if confidence is None:
            confidence = 0.0

        if action == "buy":
            score = max(-4.0, min(10.0, (confidence - 0.5) * 20.0))
        elif action == "sell":
            score = -10.0
        else:
            score = -4.0
        return score, f"consensus={action},confidence={confidence:.2f}"

    def _parse_optional_ratio(self, raw: Any) -> Optional[float]:
        if raw is None:
            return None
        try:
            value = float(str(raw).strip().rstrip("%"))
        except (TypeError, ValueError):
            return None
        if "%" in str(raw) or value > 1.0:
            value /= 100.0
        return max(0.0, min(1.0, value))

    def _score_action(self, action_text: str) -> Tuple[float, str]:
        if any(key in action_text for key in self.BUY_ACTION_KEYWORDS):
            return 12.0, "action=buy-like"
        if any(key in action_text for key in self.SELL_ACTION_KEYWORDS):
            return -18.0, "action=sell-like"
        if action_text:
            return -4.0, "action=unclear"
        return -8.0, "action=missing"

    def _score_evidence_quality(self, evidence_list: List[Dict[str, Any]], trigger_time: str) -> Tuple[float, str]:
        if not evidence_list:
            return -10.0, "evidence=none"

        count_points = min(self.config.max_evidence_points, len(evidence_list) * 5)

        freshness_scores = []
        for evidence in evidence_list:
            evidence_time = str(evidence.get("time") or "").strip()
            freshness_scores.append(self._freshness_weight(evidence_time, trigger_time))

        freshness = sum(freshness_scores) / len(freshness_scores) if freshness_scores else 0.2
        freshness_points = (freshness - 0.5) * 20

        total = count_points + freshness_points
        total = max(-10.0, min(30.0, total))
        return total, f"evidence_count={len(evidence_list)},freshness={freshness:.2f}"

    def _score_direction_bias(self, evidence_list: List[Dict[str, Any]]) -> Tuple[float, str]:
        texts = " ".join(str(x.get("description") or "") for x in evidence_list).lower()
        bull_hits = sum(1 for key in self.BULLISH_KEYWORDS if key in texts)
        bear_hits = sum(1 for key in self.BEARISH_KEYWORDS if key in texts)

        if bull_hits > bear_hits:
            return min(12.0, (bull_hits - bear_hits) * 3.0), f"bull_hits={bull_hits},bear_hits={bear_hits}"
        if bear_hits > bull_hits:
            return -min(12.0, (bear_hits - bull_hits) * 4.0), f"bull_hits={bull_hits},bear_hits={bear_hits}"
        return 0.0, f"bull_hits={bull_hits},bear_hits={bear_hits}"

    def _score_source_credibility(self, evidence_list: List[Dict[str, Any]]) -> Tuple[float, str]:
        source_text = " ".join(str(x.get("from_source") or "") for x in evidence_list)
        high_hits = sum(1 for key in self.HIGH_CREDIBILITY_SOURCES if key in source_text)
        low_hits = sum(1 for key in self.LOW_CREDIBILITY_SOURCES if key in source_text)
        score = high_hits * 2.0 - low_hits * 3.0
        score = max(-10.0, min(10.0, score))
        return score, f"source_high={high_hits},source_low={low_hits}"

    def _score_catalyst_strength(self, evidence_list: List[Dict[str, Any]], trigger_time: str) -> Tuple[float, str]:
        evidence_text = " ".join(str(item.get("description") or "") for item in evidence_list)
        catalyst_hits = sum(1 for keyword in self.CATALYST_KEYWORDS if keyword in evidence_text)

        freshness_scores = [self._freshness_weight(str(item.get("time") or ""), trigger_time) for item in evidence_list]
        freshness = sum(freshness_scores) / len(freshness_scores) if freshness_scores else 0.35

        score = min(100.0, 35.0 + catalyst_hits * 8.0 + freshness * 25.0)
        return score, f"catalyst_hits={catalyst_hits},freshness={freshness:.2f}"

    def _score_capital_flow_strength(self, evidence_list: List[Dict[str, Any]]) -> Tuple[float, str]:
        evidence_text = " ".join(str(item.get("description") or "") for item in evidence_list)
        flow_hits = sum(1 for keyword in self.CAPITAL_FLOW_KEYWORDS if keyword in evidence_text)

        source_text = " ".join(str(item.get("from_source") or "") for item in evidence_list)
        institutional_bonus = 8.0 if any(tag in source_text for tag in ["龙虎榜", "机构", "交易所", "深股通", "沪股通"]) else 0.0
        score = min(100.0, 30.0 + flow_hits * 10.0 + institutional_bonus)
        return score, f"flow_hits={flow_hits},institutional_bonus={institutional_bonus:.1f}"

    def _score_market_regime(self, market_context: Optional[Dict[str, Any]]) -> Tuple[float, str]:
        if not isinstance(market_context, dict):
            return 50.0, "no_market_context"

        trend = str(market_context.get("market_trend") or "neutral").lower()
        risk_sentiment = str(market_context.get("risk_sentiment") or "neutral").lower()
        flow_complete = bool(market_context.get("has_sector_flow_data", False))

        score = 50.0
        if trend in {"up", "bullish"}:
            score += 15.0
        elif trend in {"down", "bearish"}:
            score -= 15.0

        if risk_sentiment in {"risk_on", "hot"}:
            score += 12.0
        elif risk_sentiment in {"risk_off", "cold"}:
            score -= 12.0

        if not flow_complete:
            score -= 8.0

        score = max(0.0, min(100.0, score))
        return score, f"trend={trend},risk={risk_sentiment},flow_data={flow_complete}"

    def _score_tradeability(self, symbol_code: str, symbol_name: str, action_text: str) -> Tuple[float, str]:
        score = 60.0
        reasons = []

        if any(keyword in action_text for keyword in self.BUY_ACTION_KEYWORDS):
            score += 8.0
            reasons.append("buy-action")
        elif any(keyword in action_text for keyword in self.SELL_ACTION_KEYWORDS):
            score -= 18.0
            reasons.append("sell-action")
        else:
            score -= 6.0
            reasons.append("unclear-action")

        if symbol_code.startswith("688") or symbol_code.startswith("300"):
            score -= 3.0
            reasons.append("high-vol-board")

        if self._is_non_tradable_name(symbol_name):
            score -= 25.0
            reasons.append("non-tradable-tag")

        if not symbol_code:
            score -= 25.0
            reasons.append("missing-code")

        score = max(0.0, min(100.0, score))
        return score, ",".join(reasons)

    def _score_risk_reward(
        self,
        signal: Dict[str, Any],
        probability_value: float,
        direction_score: float,
        limitations: List[str],
    ) -> Tuple[float, str]:
        score = 52.0
        score += (probability_value - 0.5) * 40.0
        score += max(-10.0, min(10.0, direction_score * 0.6))

        limitation_severity = 0
        for text in limitations:
            content = str(text or "")
            if any(word in content for word in ["追高", "波动", "不确定", "风险", "未验证"]):
                limitation_severity += 1
        score -= min(20.0, limitation_severity * 4.5)

        score = max(0.0, min(100.0, score))
        return score, f"limitation_severity={limitation_severity},direction_score={direction_score:.1f}"

    def _score_data_quality(
        self,
        signal: Dict[str, Any],
        evidence_list: List[Dict[str, Any]],
        system_health: Optional[Dict[str, Any]],
        trigger_time: str,
    ) -> Tuple[float, str]:
        score = 70.0
        reasons = []

        if len(evidence_list) < 2:
            score -= 14.0
            reasons.append("few-evidence")

        missing_time = sum(1 for ev in evidence_list if not str(ev.get("time") or "").strip())
        if missing_time:
            score -= min(12.0, missing_time * 3.0)
            reasons.append(f"missing-time={missing_time}")

        evidence_source_text = " ".join(str(ev.get("from_source") or "") for ev in evidence_list)
        if "逻辑推断" in evidence_source_text:
            score -= 10.0
            reasons.append("inference-source")

        if isinstance(system_health, dict):
            tool_error_count = int(system_health.get("tool_error_count", 0) or 0)
            if tool_error_count > 0:
                score -= min(25.0, tool_error_count * 5.0)
                reasons.append(f"tool-errors={tool_error_count}")

        quality_tags = signal.get("data_quality_warnings") or []
        if quality_tags:
            score -= min(15.0, len(quality_tags) * 5.0)
            reasons.append(f"quality-warnings={len(quality_tags)}")

        future_evidence_count = self._count_future_evidence(evidence_list, trigger_time)
        if future_evidence_count:
            score -= min(35.0, future_evidence_count * 15.0)
            reasons.append(f"future-evidence={future_evidence_count}")

        score = max(0.0, min(100.0, score))
        return score, ",".join(reasons) if reasons else "ok"

    def _count_future_evidence(
        self,
        evidence_list: List[Dict[str, Any]],
        trigger_time: str,
    ) -> int:
        trigger_dt = self._parse_datetime(trigger_time)
        if not trigger_dt:
            return 0

        count = 0
        for evidence in evidence_list or []:
            evidence_dt = self._parse_datetime(str(evidence.get("time") or ""))
            if evidence_dt and evidence_dt > trigger_dt:
                count += 1
        return count

    def _analysis_as_of_date(self, trigger_time: str) -> str:
        trigger_dt = self._parse_datetime(trigger_time)
        if trigger_dt:
            return trigger_dt.strftime("%Y-%m-%d")
        return str(trigger_time or "").strip().split(" ")[0]

    def _evaluate_risk_veto(
        self,
        signal: Dict[str, Any],
        symbol_name: str,
        action: str,
        evidence_list: List[Dict[str, Any]],
        future_evidence_count: int,
    ) -> Dict[str, Any]:
        if not self.config.risk_veto_enabled:
            return {"passed": True, "reasons": [], "risk_flags": []}

        reasons: List[str] = []
        risk_flags: List[str] = []

        def add(reason: str, flag: Optional[str] = None) -> None:
            if reason not in reasons:
                reasons.append(reason)
            if flag and flag not in risk_flags:
                risk_flags.append(flag)

        if not self._bool_like(signal.get("has_opportunity")):
            add("no_opportunity", "no_opportunity")
        if any(keyword in action for keyword in self.SELL_ACTION_KEYWORDS):
            add("sell_like_action", "sell_like_action")
        elif not any(keyword in action for keyword in self.BUY_ACTION_KEYWORDS):
            add("action_not_buy_like", "action_not_buy_like")

        if self._is_non_tradable_name(symbol_name):
            add("non_tradable_name", "non_tradable_name")

        quality_tags = {
            str(tag).strip()
            for tag in (signal.get("data_quality_warnings") or [])
            if str(tag).strip()
        }
        for tag in sorted(quality_tags & self.HARD_DATA_QUALITY_TAGS):
            add(f"data_quality:{tag}", tag)

        if future_evidence_count:
            add("future_evidence", "future_evidence")

        text = " ".join(
            [
                " ".join(str(item or "") for item in (signal.get("limitations") or [])),
                " ".join(str(item.get("description") or "") for item in evidence_list or []),
            ]
        )
        for keyword in self.HARD_RISK_KEYWORDS:
            if keyword in text:
                add(f"hard_risk:{keyword}", keyword)

        return {
            "passed": not reasons,
            "reasons": reasons,
            "risk_flags": risk_flags,
        }

    def _estimate_expected_return_t1(
        self,
        probability: float,
        catalyst_score: float,
        capital_flow_score: float,
        market_regime_score: float,
        tradeability_score: float,
        risk_reward_score: float,
        data_quality_score: float,
        technical_score: float,
        weekly_trend_score: float,
        relative_strength_score: float,
        daily_entry_score: float,
    ) -> float:
        """Estimate next-day expected return percentage (rough proxy)."""
        edge = (
            (probability - 0.5) * 3.0
            + (catalyst_score - 50.0) * 0.015
            + (capital_flow_score - 50.0) * 0.012
            + (market_regime_score - 50.0) * 0.010
            + (tradeability_score - 50.0) * 0.008
            + (risk_reward_score - 50.0) * 0.010
            + (data_quality_score - 50.0) * 0.006
            + (technical_score - 50.0) * 0.012
            + (weekly_trend_score - 50.0) * 0.010
            + (relative_strength_score - 50.0) * 0.010
            + (daily_entry_score - 50.0) * 0.008
        )
        # bound in practical short-term range
        return max(-3.5, min(5.0, edge))

    def _passes_next_day_buy_gates(self, item: Dict[str, Any]) -> bool:
        gate = item.get("next_day_gate_report") or {}
        return bool(gate.get("passed", False))

    def _is_hard_watchlist_reject(self, item: Dict[str, Any]) -> bool:
        gate = item.get("next_day_gate_report") or {}
        failed_reasons = gate.get("failed_reasons") or []
        failed_text = " ".join(str(reason) for reason in failed_reasons)
        return (
            "technical<" in failed_text
            and "ma20_deviation>" in failed_text
        ) or bool(gate.get("risk_veto_reasons"))

    def _evaluate_gate_report(
        self,
        buy_score: float,
        probability_value: float,
        tradeability_score: float,
        risk_reward_score: float,
        data_quality_score: float,
        technical_score: float,
        capital_flow_score: float,
        market_regime_score: float,
        flow_data_available: bool,
        weekly_trend_score: float,
        relative_strength_score: float,
        relative_strength_20d_pct: Optional[float],
        daily_entry_score: float,
        weekly_data_available: bool,
        relative_strength_available: bool,
        daily_data_available: bool,
        prev_day_gain_pct: Optional[float],
        ma20_deviation_pct: Optional[float],
        primary_catalyst: bool,
        expected_return_t1: float,
        future_evidence_count: int,
        risk_veto_report: Dict[str, Any],
    ) -> Dict[str, Any]:
        failed = []
        if buy_score < self.config.min_buy_score:
            failed.append(f"buy_score<{self.config.min_buy_score}")
        if probability_value < self.config.min_probability:
            failed.append(f"prob<{self.config.min_probability}")
        if tradeability_score < self.config.min_tradeability_score:
            failed.append(f"tradeability<{self.config.min_tradeability_score}")
        if risk_reward_score < self.config.min_risk_reward_score:
            failed.append(f"risk_reward<{self.config.min_risk_reward_score}")
        if data_quality_score < self.config.min_data_quality_score:
            failed.append(f"data_quality<{self.config.min_data_quality_score}")
        if technical_score < self.config.min_technical_score:
            failed.append(f"technical<{self.config.min_technical_score}")

        if self.config.enforce_multi_timeframe:
            if not weekly_data_available:
                failed.append("weekly_data_missing")
            elif weekly_trend_score < self.config.min_weekly_trend_score:
                failed.append(f"weekly_trend<{self.config.min_weekly_trend_score}")

            if not relative_strength_available:
                failed.append("relative_strength_data_missing")
            else:
                if relative_strength_score < self.config.min_relative_strength_score:
                    failed.append(
                        f"relative_strength<{self.config.min_relative_strength_score}"
                    )
                if (
                    relative_strength_20d_pct is not None
                    and relative_strength_20d_pct < self.config.min_relative_strength_20d_pct
                ):
                    failed.append(
                        f"relative_strength_20d<{self.config.min_relative_strength_20d_pct}%"
                    )

            if not daily_data_available:
                failed.append("daily_entry_data_missing")
            elif daily_entry_score < self.config.min_daily_entry_score:
                failed.append(f"daily_entry<{self.config.min_daily_entry_score}")

        if (
            prev_day_gain_pct is not None
            and prev_day_gain_pct > self.config.max_prev_day_gain_pct
            and not primary_catalyst
        ):
            failed.append(f"chase_up>{self.config.max_prev_day_gain_pct}%")

        if (
            ma20_deviation_pct is not None
            and ma20_deviation_pct > self.config.max_ma20_deviation_pct
            and not primary_catalyst
        ):
            failed.append(f"ma20_deviation>{self.config.max_ma20_deviation_pct}%")

        if self.config.enforce_flow_confirmation_if_available and flow_data_available:
            if capital_flow_score < self.config.min_flow_confirmation_score:
                failed.append(f"flow<{self.config.min_flow_confirmation_score}")
            if market_regime_score < self.config.min_regime_confirmation_score:
                failed.append(f"regime<{self.config.min_regime_confirmation_score}")

        if expected_return_t1 < self.config.expected_return_floor_pct:
            failed.append(f"expected_t1<{self.config.expected_return_floor_pct}")
        if self.config.reject_future_evidence and future_evidence_count:
            failed.append(f"evidence_after_analysis>{future_evidence_count}")
        if self.config.risk_veto_enabled and not risk_veto_report.get("passed", True):
            failed.extend(
                f"risk_veto:{reason}"
                for reason in risk_veto_report.get("reasons", [])
            )
        return {
            "passed": len(failed) == 0,
            "failed_reasons": failed,
            "risk_veto_reasons": list(risk_veto_report.get("reasons", [])),
        }

    def _extract_prev_day_gain_pct(
        self,
        signal: Dict[str, Any],
        evidence_list: List[Dict[str, Any]],
    ) -> Optional[float]:
        direct_fields = [
            signal.get("prev_day_gain_pct"),
            signal.get("prev_day_pct"),
            signal.get("yesterday_change_pct"),
            signal.get("price_change_pct"),
        ]
        for raw in direct_fields:
            value = self._parse_optional_pct(raw)
            if value is not None:
                return value

        merged_text = " ".join(
            [
                str(signal.get("technical_analysis") or ""),
                str(signal.get("kline_description") or ""),
                " ".join(str(x.get("description") or "") for x in evidence_list),
            ]
        ).lower()

        context_patterns = [
            r"(?:昨日|前一日|上日|收盘)\D{0,6}(?:涨幅|涨跌幅)\D{0,6}([-+]?\d+(?:\.\d+)?)\s*%",
            r"(?:涨幅|涨跌幅)\D{0,6}([-+]?\d+(?:\.\d+)?)\s*%",
        ]
        for pattern in context_patterns:
            match = re.search(pattern, merged_text)
            if match:
                try:
                    return float(match.group(1))
                except Exception:
                    pass

        if any(key in merged_text for key in ["涨停", "封板", "一字板"]):
            return 9.9
        return None

    def _extract_ma20_deviation_pct(
        self,
        signal: Dict[str, Any],
        evidence_list: List[Dict[str, Any]],
    ) -> Optional[float]:
        signed_distance = self._extract_signed_ma20_distance_pct(signal, evidence_list)
        if signed_distance is not None:
            return abs(signed_distance)

        merged_text = " ".join(
            [
                str(signal.get("kline_description") or ""),
                str(signal.get("technical_analysis") or ""),
                " ".join(str(x.get("description") or "") for x in evidence_list),
            ]
        ).lower()

        pct_match = re.search(r"(?:偏离|乖离)\D{0,6}(?:ma20|20日线)\D{0,6}([-+]?\d+(?:\.\d+)?)\s*%", merged_text)
        if pct_match:
            try:
                return abs(float(pct_match.group(1)))
            except Exception:
                pass

        ma5, ma10, ma20 = self._extract_ma_values(merged_text)
        close_match = re.search(r"收盘\s*[:：]\s*([-+]?\d+(?:\.\d+)?)", merged_text)
        if ma20 is None or close_match is None or ma20 == 0:
            return None
        try:
            close_value = float(close_match.group(1))
            return abs((close_value - ma20) / ma20 * 100.0)
        except Exception:
            return None

    def _extract_signed_ma20_distance_pct(
        self,
        signal: Dict[str, Any],
        evidence_list: List[Dict[str, Any]],
    ) -> Optional[float]:
        direct_fields = [
            signal.get("ma20_distance_pct"),
            signal.get("ma20_deviation_pct"),
            signal.get("price_ma20_deviation_pct"),
        ]
        for raw in direct_fields:
            value = self._parse_optional_pct(raw)
            if value is not None:
                return value

        merged_text = " ".join(
            [
                str(signal.get("kline_description") or ""),
                str(signal.get("technical_analysis") or ""),
                " ".join(str(x.get("description") or "") for x in evidence_list),
            ]
        ).lower()

        patterns = [
            r"(?:ma20|20日线)\s*(?:距离|偏离|乖离)\s*([-+]?\d+(?:\.\d+)?)\s*%",
            r"(?:偏离|乖离)\D{0,6}(?:ma20|20日线)\D{0,6}([-+]?\d+(?:\.\d+)?)\s*%",
        ]
        for pattern in patterns:
            match = re.search(pattern, merged_text, flags=re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except Exception:
                    pass

        below_match = re.search(r"20日线下方\D{0,4}(\d+(?:\.\d+)?)\s*%", merged_text)
        if below_match:
            try:
                return -float(below_match.group(1))
            except Exception:
                pass

        above_match = re.search(r"20日线上方\D{0,4}(\d+(?:\.\d+)?)\s*%", merged_text)
        if above_match:
            try:
                return float(above_match.group(1))
            except Exception:
                pass

        return None

    def _is_primary_catalyst(
        self,
        signal: Dict[str, Any],
        evidence_list: List[Dict[str, Any]],
        catalyst_score: float,
    ) -> bool:
        if catalyst_score >= 82:
            return True
        text = " ".join(
            [
                str(signal.get("technical_analysis") or ""),
                str(signal.get("kline_description") or ""),
                " ".join(str(x.get("description") or "") for x in evidence_list),
            ]
        )
        return any(keyword in text for keyword in self.PRIMARY_CATALYST_KEYWORDS)

    def _parse_optional_pct(self, raw: Any) -> Optional[float]:
        if raw is None:
            return None
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            if math.isnan(float(raw)):
                return None
            return float(raw)
        text = str(raw).strip().lower()
        if not text:
            return None
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        if not match:
            return None
        value = float(match.group(0))
        if "%" not in text and -1.0 <= value <= 1.0:
            value = value * 100.0
        return value

    def _score_technical_setup(
        self,
        signal: Dict[str, Any],
        evidence_list: List[Dict[str, Any]],
    ) -> Tuple[float, str]:
        score = 50.0
        reasons = []

        text_parts = [
            str(signal.get("technical_analysis") or ""),
            str(signal.get("kline_description") or ""),
            " ".join(str(x.get("description") or "") for x in evidence_list),
        ]
        text = " ".join(part.lower() for part in text_parts if part)

        bull_hits = sum(1 for key in self.TECHNICAL_BULLISH_KEYWORDS if key in text)
        bear_hits = sum(1 for key in self.TECHNICAL_BEARISH_KEYWORDS if key in text)
        score += bull_hits * 6.0
        score -= bear_hits * 7.0
        reasons.append(f"tech_bull={bull_hits},tech_bear={bear_hits}")

        ma20_distance_pct = self._extract_signed_ma20_distance_pct(signal, evidence_list)
        if ma20_distance_pct is not None:
            if ma20_distance_pct <= -3.0:
                penalty = min(22.0, abs(ma20_distance_pct) * 1.5)
                score -= penalty
                reasons.append(f"below_ma20={ma20_distance_pct:.1f}%")
            elif ma20_distance_pct >= 3.0:
                bonus = min(4.0, ma20_distance_pct * 0.4)
                score += bonus
                reasons.append(f"above_ma20={ma20_distance_pct:.1f}%")

        ma5, ma10, ma20 = self._extract_ma_values(text)
        if ma5 is not None and ma10 is not None and ma20 is not None:
            if ma5 >= ma10 >= ma20:
                score += 14.0
                reasons.append("ma_alignment=bullish")
            elif ma5 <= ma10 <= ma20:
                score -= 16.0
                reasons.append("ma_alignment=bearish")
            else:
                reasons.append("ma_alignment=mixed")
        else:
            score -= 3.0
            reasons.append("ma_alignment=missing")

        score = max(0.0, min(100.0, score))
        return score, ",".join(reasons)

    def _extract_ma_values(self, text: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        normalized = text.replace("，", ",").replace("：", ":")

        patterns = [
            r"ma5\s*/\s*10\s*/\s*20\s*=\s*([-+]?\d+(?:\.\d+)?)\s*/\s*([-+]?\d+(?:\.\d+)?)\s*/\s*([-+]?\d+(?:\.\d+)?)",
            r"5/10/20日均线\s*:\s*([-+]?\d+(?:\.\d+)?)\s*/\s*([-+]?\d+(?:\.\d+)?)\s*/\s*([-+]?\d+(?:\.\d+)?)",
            r"ma5\s*[:=]\s*([-+]?\d+(?:\.\d+)?)\D+ma10\s*[:=]\s*([-+]?\d+(?:\.\d+)?)\D+ma20\s*[:=]\s*([-+]?\d+(?:\.\d+)?)",
        ]

        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            try:
                return float(match.group(1)), float(match.group(2)), float(match.group(3))
            except Exception:
                continue

        return None, None, None

    def _technical_factor(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        factor = signal.get("technical_factor")
        return factor if isinstance(factor, dict) else {}

    def _factor_value(self, signal: Dict[str, Any], key: str) -> Any:
        factor = self._technical_factor(signal)
        return factor.get(key, signal.get(key))

    def _score_weekly_trend(
        self,
        signal: Dict[str, Any],
    ) -> Tuple[float, str, bool]:
        raw_score = self._factor_value(signal, "weekly_trend_score")
        raw_trend = str(self._factor_value(signal, "weekly_trend") or "").lower()
        available_flag = self._factor_value(signal, "weekly_data_available")
        score = None
        try:
            if raw_score is not None:
                score = float(raw_score)
        except (TypeError, ValueError):
            score = None

        if score is None:
            score = {
                "bullish": 75.0,
                "neutral": 50.0,
                "bearish": 25.0,
            }.get(raw_trend)

        available = bool(available_flag) if available_flag is not None else score is not None
        if score is None:
            return 50.0, "weekly=missing", False
        score = max(0.0, min(100.0, score))
        return score, f"weekly={raw_trend or 'scored'},weekly_score={score:.1f}", available

    def _extract_relative_strength_20(self, signal: Dict[str, Any]) -> Optional[float]:
        raw = self._factor_value(signal, "relative_strength_20d_pct")
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return self._parse_optional_pct(raw)

    def _score_relative_strength(
        self,
        signal: Dict[str, Any],
    ) -> Tuple[float, str, bool]:
        factor = self._technical_factor(signal)
        raw_score = self._factor_value(signal, "relative_strength_score")
        rs20 = self._extract_relative_strength_20(signal)
        raw_rs60 = self._factor_value(signal, "relative_strength_60d_pct")
        try:
            rs60 = float(raw_rs60) if raw_rs60 is not None else None
        except (TypeError, ValueError):
            rs60 = self._parse_optional_pct(raw_rs60)

        score = None
        try:
            if raw_score is not None:
                score = float(raw_score)
        except (TypeError, ValueError):
            score = None
        if score is None and (rs20 is not None or rs60 is not None):
            score = 50.0 + (rs20 or 0.0) * 2.0 + (rs60 or 0.0)

        available_flag = factor.get("relative_strength_available")
        available = (
            bool(available_flag)
            if available_flag is not None
            else rs20 is not None and rs60 is not None
        )
        if score is None:
            return 50.0, "relative_strength=missing", False
        score = max(0.0, min(100.0, score))
        return (
            score,
            f"relative_strength_score={score:.1f},rs20={rs20 if rs20 is not None else 'N/A'},"
            f"rs60={rs60 if rs60 is not None else 'N/A'}",
            available,
        )

    def _score_daily_entry(
        self,
        signal: Dict[str, Any],
        technical_score: float,
    ) -> Tuple[float, str, bool]:
        raw_score = self._factor_value(signal, "daily_entry_score")
        if raw_score is None:
            return technical_score, "daily_entry=technical_fallback", False
        try:
            score = max(0.0, min(100.0, float(raw_score)))
        except (TypeError, ValueError):
            return technical_score, "daily_entry=technical_fallback", False
        return score, f"daily_entry_score={score:.1f}", True

    def _score_limitations(self, limitations: List[str]) -> float:
        if not limitations:
            return 0.0
        penalty = 0.0
        for limitation in limitations:
            text = str(limitation or "")
            if not text:
                continue
            if any(key in text for key in ["不确定", "待验证", "传闻", "未知", "可能"]):
                penalty += 5
            else:
                penalty += 3
        return min(self.config.limitation_penalty_cap, penalty)

    def _freshness_weight(self, evidence_time: str, trigger_time: str) -> float:
        evidence_dt = self._parse_datetime(evidence_time)
        trigger_dt = self._parse_datetime(trigger_time)
        if not evidence_dt or not trigger_dt:
            return 0.5
        if evidence_dt > trigger_dt:
            return 0.0

        delta_hours = (trigger_dt - evidence_dt).total_seconds() / 3600
        half_life = max(1, self.config.freshness_half_life_hours)
        weight = math.exp(-math.log(2) * (delta_hours / half_life))
        return max(0.05, min(1.0, weight))

    def _parse_datetime(self, text: str) -> Optional[datetime]:
        if not text:
            return None

        normalized = (
            text.strip()
            .replace("/", "-")
            .replace("T", " ")
            .replace("年", "-")
            .replace("月", "-")
            .replace("日", "")
        )
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y%m%d %H:%M:%S",
            "%Y%m%d",
            "%m-%d %H:%M",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(normalized, fmt)
                if fmt == "%m-%d %H:%M":
                    now = datetime.now()
                    dt = dt.replace(year=now.year)
                return dt
            except ValueError:
                continue

        # Try timestamp
        if re.fullmatch(r"\d{10,13}", normalized):
            timestamp = int(normalized[:10])
            return datetime.fromtimestamp(timestamp)

        return None

    def _parse_probability(self, probability_raw: Any) -> float:
        if probability_raw is None:
            return 0.5

        text = str(probability_raw).strip().lower()
        if not text:
            return 0.5

        number_match = re.search(r"\d+(?:\.\d+)?", text)
        if not number_match:
            return 0.5

        value = float(number_match.group(0))
        if "%" in text or value > 1.0:
            value = value / 100.0

        return max(0.0, min(1.0, value))

    def _calibrate_probability(self, raw_probability: float) -> float:
        """Apply simple affine calibration clipped to [0, 1]."""
        slope = float(self.calibration.get("slope", 1.0))
        intercept = float(self.calibration.get("intercept", 0.0))
        calibrated = raw_probability * slope + intercept
        return max(0.0, min(1.0, calibrated))

    def _load_probability_calibration(self) -> Dict[str, Any]:
        default = {"slope": 0.92, "intercept": 0.03, "source": "default"}
        try:
            path = Path(self.config.probability_calibration_path)
            if not path.exists():
                return default
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                return default
            slope = float(payload.get("slope", default["slope"]))
            intercept = float(payload.get("intercept", default["intercept"]))
            return {
                "slope": slope,
                "intercept": intercept,
                "source": str(path),
            }
        except Exception:
            return default

    def _bool_like(self, value: Any) -> bool:
        text = str(value).strip().lower()
        return text in {"1", "true", "yes", "y", "是", "有", "有机会"}

    def _is_non_tradable_name(self, symbol_name: str) -> bool:
        if not symbol_name:
            return False
        name = symbol_name.upper()
        blocked_tags = ["ST", "*ST", "退", "B"]
        return any(tag in name for tag in blocked_tags)
