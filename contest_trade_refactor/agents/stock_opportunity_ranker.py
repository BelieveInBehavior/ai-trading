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
from loguru import logger


@dataclass
class RankerConfig:
    top_k: int = 8
    min_buy_score: float = 60.0
    min_probability: float = 0.55
    min_tradeability_score: float = 55.0
    min_risk_reward_score: float = 50.0
    min_data_quality_score: float = 45.0
    min_technical_score: float = 45.0
    max_prev_day_gain_pct: float = 8.0
    max_ma20_deviation_pct: float = 12.0
    min_flow_confirmation_score: float = 55.0
    min_regime_confirmation_score: float = 52.0
    enforce_flow_confirmation_if_available: bool = True
    freshness_half_life_hours: int = 18
    max_evidence_points: int = 25
    limitation_penalty_cap: int = 15
    expected_return_floor_pct: float = 0.3
    strong_trend_penalty_bias: float = 0.0
    reject_future_evidence: bool = True
    risk_veto_enabled: bool = True
    enforce_financial_evidence_consistency: bool = True
    enforce_multi_timeframe: bool = False
    min_weekly_trend_score: float = 40.0
    min_relative_strength_score: float = 30.0
    min_relative_strength_20d_pct: float = 0.0
    min_daily_entry_score: float = 40.0
    # T+1 short gate: a stock with only a sector-flow catalyst (no company-level
    # catalyst) should not be a hard "buy" when the attached trade plan has RR<1.
    reject_below_rr_without_company_catalyst: bool = True
    min_rr_without_company_catalyst: float = 1.0
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
        short_momentum_score, short_momentum_reason = self._score_short_setup(signal)
        volume_amount_score, volume_amount_reason = self._score_volume_amount(signal)
        sector_score, sector_reason = self._score_sector_strength(signal)
        prev_day_gain_pct = self._extract_prev_day_gain_pct(signal, evidence_list)
        ma20_deviation_pct = self._extract_ma20_deviation_pct(signal, evidence_list)
        primary_catalyst = self._is_primary_catalyst(signal, evidence_list, catalyst_score)
        future_evidence_count = self._count_future_evidence(evidence_list, trigger_time)
        entry_quality_delta, entry_quality_reason, entry_quality_report = self._score_entry_quality(
            signal=signal,
            short_momentum_score=short_momentum_score,
            volume_amount_score=volume_amount_score,
            sector_strength_score=sector_score,
            catalyst_score=catalyst_score,
        )

        total += (technical_score - 50.0) * 0.12
        total += (weekly_trend_score - 50.0) * 0.06
        total += (relative_strength_score - 50.0) * 0.08
        total += (daily_entry_score - 50.0) * 0.05
        total += (short_momentum_score - 50.0) * 0.12
        total += (volume_amount_score - 50.0) * 0.12
        total += (sector_score - 50.0) * 0.10
        total += (catalyst_score - 50.0) * 0.22
        total = max(0.0, min(100.0, total))

        total += entry_quality_delta
        total += self._score_strong_trend_penalty(signal)
        # keep one step always below 100 to avoid a perfect-score no-op (test contract)
        total = max(0.0, min(99.5, total))

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
            short_momentum_score=short_momentum_score,
            volume_amount_score=volume_amount_score,
            sector_score=sector_score,
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
            short_momentum_reason,
            volume_amount_reason,
            sector_reason,
            entry_quality_reason,
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
            "short_momentum_score": round(short_momentum_score, 2),
            "volume_amount_score": round(volume_amount_score, 2),
            "sector_score": round(sector_score, 2),
            "entry_quality_score": round(entry_quality_report.get("entry_quality_score", 50.0), 2),
            "crowding_score": round(entry_quality_report.get("crowding_score", 0.0), 2),
            "entry_quality_delta": round(entry_quality_delta, 2),
            "prev_day_gain_pct": round(prev_day_gain_pct, 3) if prev_day_gain_pct is not None else None,
            "ma20_deviation_pct": round(ma20_deviation_pct, 3) if ma20_deviation_pct is not None else None,
            "future_evidence_count": future_evidence_count,
            "consensus_score": round(consensus_score, 2),
            "forward_opportunity_score": round(total, 2),
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
            flow_data_marked_missing=bool((market_context or {}).get("has_sector_flow_data") is False),
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
            short_momentum_score=short_momentum_score,
            volume_amount_score=volume_amount_score,
            sector_score=sector_score,
            expected_return_t1=expected_return_t1,
            future_evidence_count=future_evidence_count,
            risk_veto_report=risk_veto_report,
            event_type=self._event_type(signal),
            company_catalyst=self._has_company_level_catalyst(signal, evidence_list),
            trade_plan_rr=self._trade_plan_rr(signal),
            sector_outflow=self._sector_net_outflow_amount(signal),
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
                "setup_meta": self._classify_risk_state(signal, evidence_list),
                "signal_confidence_type": "subjective_confidence_not_backtest",
                "expected_return_method": "heuristic_edge_from_scoring_formula", 
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
                    "short_momentum_score": round(short_momentum_score, 2),
                    "volume_amount_score": round(volume_amount_score, 2),
                    "sector_score": round(sector_score, 2),
                    "entry_quality_score": round(entry_quality_report.get("entry_quality_score", 50.0), 2),
                    "crowding_score": round(entry_quality_report.get("crowding_score", 0.0), 2),
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

        # 更强调“资金已经确认”的表现，而不是只出现资金相关词
        strong_confirm = [
            "主力净流入", "连续主力资金流入", "融资净买入", "北向净买入",
            "龙虎榜净买入", "机构净买入", "大宗交易溢价", "封单极强", "超大单净流入",
        ]
        weak_or_just_mention = [
            "资金流入", "净流入", "板块资金净流入", "主力吸筹",
        ]
        strong_hits = sum(1 for keyword in strong_confirm if keyword in evidence_text)
        weak_hits = sum(1 for keyword in weak_or_just_mention if keyword in evidence_text)

        source_text = " ".join(str(item.get("from_source") or "") for item in evidence_list)
        institutional_bonus = 8.0 if any(tag in source_text for tag in ["龙虎榜", "机构", "交易所", "深股通", "沪股通"]) else 0.0

        # 基础分 + 强确认每个 +12，弱提及每个 +4；避免只靠“资金净流入”几个字就拿高分
        score = 30.0 + strong_hits * 12.0 + weak_hits * 4.0 + institutional_bonus

        # 有明确资金金额时加强（例如“主力净流入10.5亿元”）
        if re.search(r'(?:净流入|主力流入|资金流入|超大单净流入)[^。；;]{0,10}?(\d+(?:\.\d+)?)\s*(?:亿|万)', evidence_text):
            score += 14.0
        elif re.search(r'(?:净流出|主力流出|资金流出)[^。；;]{0,10}?(\d+(?:\.\d+)?)\s*(?:亿|万)', evidence_text):
            score -= 12.0

        score = min(100.0, score)
        return score, f"strong_hits={strong_hits},weak_hits={weak_hits},institutional_bonus={institutional_bonus:.1f},amount_conf={bool(re.search(r'净流入|净买入', evidence_text))}"

    def _sector_net_outflow_amount(self, signal: Dict[str, Any]) -> Optional[float]:
        """Extract a negative '板块主力净流出' magnitude from evidence text."""
        text = " ".join(
            [
                str(signal.get("event_summary") or ""),
                " ".join(str(ev.get("description") or "") for ev in signal.get("evidence_list") or []),
                " ".join(str(ev.get("content") or "") for ev in signal.get("evidence_list") or []),
                str(signal.get("technical_analysis") or ""),
                " ".join(str(lim) for lim in signal.get("limitations") or []),
            ]
        )
        patterns = [
            r"板块([^。；;]{0,30}?)主力净流出\s*([0-9]+(?:\.[0-9]+)?)\s*亿",
            r"([^。；;]{0,12}?半导体|电子|板块|行业)([^。；;]{0,20}?)主力净流出\s*([0-9]+(?:\.[0-9]+)?)\s*亿",
            r"板块资金面偏弱[^。；;]{0,10}净流出\s*([0-9]+(?:\.[0-9]+)?)\s*亿",
            r"净流出\s*([0-9]+(?:\.[0-9]+)?)\s*亿",
        ]
        max_flow = None
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                try:
                    # pick the group that is the amount (last numeric capture)
                    groups = [g for g in match.groups() if g is not None]
                    amount = float(groups[-1])
                except (TypeError, ValueError, IndexError):
                    continue
                # Only treat capitalized outflow as a block-level headwind.
                ctx = match.group(0)
                if any(k in ctx for k in ["净流出", "流出"]):
                    max_flow = -max(abs(amount), abs(max_flow or 0))
        return max_flow if max_flow is not None else None

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

    def _score_strong_trend_penalty(self, signal: Dict[str, Any]) -> float:
        """Signal-quality delta for stocks in an uptrend but not overheated.

        The goal is to select stocks that are in an established/started uptrend
        BEFORE they become a crowded, already-pumped trade:
        - below MA20: likely not in uptrend yet -> penalize
        - mildly above MA20: good "in-trend early / mid leg"
        - far above MA20: already extended -> penalize
        - RSI 40-65: good; RSI >75 or deeply weak <35: penalize
        - volume ratio 1-1.8: healthy participation; too dry or too hot: penalize

        Returns a score delta in ~[-25, +8]. The caller clamps total to [0,100].
        """
        factor = self._technical_factor(signal)
        if not factor:
            # 没有量化因子时轻微惩罚，避免仅有新闻/资金关键词就占用名额
            if signal.get("strong_trend_penalty_reasons") is None:
                signal["strong_trend_penalty_reasons"] = ["missing_technical_factor"]
            return -3.0

        score_delta = 0.0
        reasons = []

        ma20_dist_raw = self._factor_value(signal, "ma20_deviation_pct")
        try:
            ma20_dist = float(ma20_dist_raw) if ma20_dist_raw is not None else None
        except (TypeError, ValueError):
            ma20_dist = None
        if ma20_dist is not None:
            if ma20_dist < 0:
                # 还在 MA20 下方：尚未走出 20 日线上涨阶段
                penalty = min(16.0, abs(ma20_dist) * 1.0)
                score_delta -= penalty
                reasons.append(f"below_ma20={ma20_dist:.1f}%")
            elif 0.0 <= ma20_dist <= 6.0:
                # 温和站上 20 日线：启动/中段健康
                score_delta += 6.0
                reasons.append(f"early_uptrend_ma20={ma20_dist:.1f}%")
            elif ma20_dist <= 12.0:
                # 已上涨但偏离可控，小加分
                score_delta += 1.0
                reasons.append(f"moderate_above_ma20={ma20_dist:.1f}%")
            else:
                # 偏离太大：已经涨过，追高风险
                score_delta -= 8.0
                reasons.append(f"extended_ma20={ma20_dist:.1f}%")

        rsi_raw = self._factor_value(signal, "rsi")
        try:
            rsi = float(rsi_raw) if rsi_raw is not None else None
        except (TypeError, ValueError):
            rsi = None
        if rsi is not None:
            if rsi < 35:
                score_delta -= 8.0
                reasons.append(f"rsi_weak={rsi:.1f}")
            elif 40.0 <= rsi <= 65.0:
                score_delta += 4.0
                reasons.append(f"rsi_healthy={rsi:.1f}")
            elif rsi > 75.0:
                score_delta -= 8.0
                reasons.append(f"rsi_overbought={rsi:.1f}")

        vol_ratio_raw = self._factor_value(signal, "volume_ratio")
        try:
            vol_ratio = float(vol_ratio_raw) if vol_ratio_raw is not None else None
        except (TypeError, ValueError):
            vol_ratio = None
        # volume_ratio now = 今日量 / 前5日均量(不含今日); 1.0+ is genuinely "放量".
        if vol_ratio is not None:
            if 1.2 <= vol_ratio < 2.5:
                score_delta += 4.0
                reasons.append(f"volume_ratio_healthy={vol_ratio:.2f}")
            elif 1.0 <= vol_ratio < 1.2:
                score_delta += 1.0
                reasons.append(f"volume_ratio_mild={vol_ratio:.2f}")
            elif vol_ratio < 0.8:
                score_delta -= 5.0
                reasons.append(f"volume_ratio_dry={vol_ratio:.2f}")
            elif vol_ratio >= 3.0:
                score_delta -= 4.0
                reasons.append(f"volume_ratio_hot={vol_ratio:.2f}")

        macd_raw = self._factor_value(signal, "macd")
        try:
            macd = float(macd_raw) if macd_raw is not None else None
        except (TypeError, ValueError):
            macd = None
        if macd is not None:
            if macd < 0:
                score_delta -= 6.0
                reasons.append(f"macd_neg={macd:.3f}")
            elif macd > 0:
                score_delta += 2.0
                reasons.append(f"macd_pos={macd:.3f}")

        if signal.get("strong_trend_penalty_reasons"):
            signal["strong_trend_penalty_reasons"] += reasons
        else:
            signal["strong_trend_penalty_reasons"] = reasons
        logger.info("strong_trend_penalty: {} delta={:.1f}", reasons, score_delta)
        # The strategy layer can soften the anti-chase penalty, e.g. momentum
        # rewards hot candidates that are still inside the strongest main lines.
        score_delta += float(self.config.strong_trend_penalty_bias or 0.0)
        return max(-50.0, min(12.0, score_delta))

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

        if self.config.enforce_financial_evidence_consistency:
            financial_check = self._financial_evidence_consistency(signal, evidence_list)
            conflict_level = int(financial_check.get("conflict_level") or 0)
            if conflict_level > 0:
                penalty = min(30.0, conflict_level * 7.0)
                score -= penalty
                reasons.append(f"financial-conflict-level={conflict_level}")

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

        if self.config.enforce_financial_evidence_consistency:
            financial_check = self._financial_evidence_consistency(signal, evidence_list)
            if not financial_check.get("passed", True):
                for reason in (financial_check.get("reasons") or []):
                    add(f"financial:{reason}", reason)
                for flag in (financial_check.get("risk_flags") or []):
                    if flag not in risk_flags:
                        risk_flags.append(flag)

        text = " ".join(
            [
                " ".join(str(item or "") for item in (signal.get("limitations") or [])),
                " ".join(str(item.get("description") or "") for item in evidence_list or []),
            ]
        )
        for keyword in self.HARD_RISK_KEYWORDS:
            if keyword in text:
                add(f"hard_risk:{keyword}", keyword)

        # --- Stale/priced-in event guard (fatal flaw #1) ---
        # A "future catalyst" that has already been announced after today's close
        # is not a 3-5D alpha; it will be absorbed on tomorrow's open.  Catch both
        # explicit "已发布/盘后/已公告" wording and event_dates <= trigger day.
        event_summary = str(signal.get("event_summary") or "").lower()
        event_date = str(signal.get("event_date") or "")
        stale_markers = [
            "已发布", "已公告", "已披露", "已落地", "公告已出",
            "盘后发布", "盘后公告", "今日发布", "今天发布",
            "收盘后发布", "收盘后公告", "拟追加", "拟投资", "拟增发",
        ]
        stale_hit = any(marker in event_summary or marker in text.lower() for marker in stale_markers)
        # If event_date has already passed (or is today, since the 18:00 run is
        # after the close) treat it as priced-in.
        ev_date = str(signal.get("event_date") or "").strip()
        today_prefix = str(signal.get("analysis_as_of_date") or "")[:10]
        stale_date = False
        if ev_date:
            ev_compact = "".join(ch for ch in ev_date if ch.isdigit())[:8]
            today_compact = "".join(ch for ch in today_prefix if ch.isdigit())[:8]
            if ev_compact and today_compact and ev_compact <= today_compact:
                stale_date = True
        if stale_hit or stale_date:
            add("catalyst_already_priced", "catalyst_stale")

        return {
            "passed": not reasons,
            "reasons": reasons,
            "risk_flags": risk_flags,
        }

    def _financial_evidence_consistency(
        self,
        signal: Dict[str, Any],
        evidence_list: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Rule-based consistency check between bullish financial claims in
        evidence (e.g. news/summaries) and counter-signals from limitations or
        official-statement caveats (e.g. "与公告口径差异,以正式财报为准").

        Returns:
            {"passed": bool, "reasons": [...], "risk_flags": [...], "conflict_level": int}
        """
        reasons: List[str] = []
        risk_flags: List[str] = []

        evidence_text = " ".join(
            str(item.get("description") or "") for item in (evidence_list or [])
        )
        limitations_text = " ".join(
            str(item or "") for item in (signal.get("limitations") or [])
        )
        combined = signal.get("data_quality_warnings") or []
        for tag in combined:
            limitations_text += " " + str(tag)

        # 1) Detect a high-certainty financial-growth claim in evidence.
        growth_pattern = re.compile(
            r"(?:净利|利润|营收|收入|业绩)[^。；;]{0,30}?"
            r"(?:同比增长|暴增|大增|增长|上修|预增)"
            r"[^。；;]{0,30}?"
            r"(\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?\s*倍)",
            re.I,
        )
        growth_match = growth_pattern.search(evidence_text)

        # 2) Detect a caveat that the claim may not match the official report
        official_caveats = [
            "口径差异", "以正式财报为准", "以公告为准", "需以正式财报为准",
            "需以公告为准", "与公告存在差异", "公司公告", "统计口径",
        ]
        caveat_hits = [kw for kw in official_caveats if kw in limitations_text]
        conflict_hits: List[str] = []

        # 3) Detect a negative/declining figure in limitation/statement text.
        negative_pattern = re.compile(
            r"(?:净利|净利润|利润|营收|收入|同比)[^。；]{0,20}?"
            r"(?:下滑|下降|减少|亏损|同比|-?\d+(?:\.\d+)?\s*%?)",
            re.I,
        )
        if negative_pattern.search(limitations_text):
            conflict_hits.append("negative_figure_in_limitations")

        # 4) Explicit official-report YOY figures attached to signal (from akshare income statement).
        report_yoy = signal.get("financial_report_net_profit_yoy")
        if isinstance(report_yoy, (int, float)) and growth_match and report_yoy < -0.01:
            reasons.append("financial_report_conflict")
            risk_flags.append("financial_report_conflict")
            conflict_hits.append("official_report_negative")

        conflict_level = 0
        if growth_match and caveat_hits:
            reasons.append("financial_evidence_caveat")
            risk_flags.append("financial_statement_conflict")
            conflict_level += 2
        if growth_match and conflict_hits:
            reasons.append("financial_claim_conflict")
            risk_flags.append("financial_claim_conflict")
            conflict_level += 3

        if not reasons:
            return {"passed": True, "reasons": [], "risk_flags": [], "conflict_level": 0}
        return {"passed": False, "reasons": reasons, "risk_flags": risk_flags, "conflict_level": conflict_level}

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
        short_momentum_score: float = 50.0,
        volume_amount_score: float = 50.0,
        sector_score: float = 50.0,
    ) -> float:
        """Estimate next-day expected return percentage (rough proxy)."""
        edge = (
            (probability - 0.5) * 3.0
            + (catalyst_score - 50.0) * 0.018
            + (capital_flow_score - 50.0) * 0.012
            + (market_regime_score - 50.0) * 0.010
            + (tradeability_score - 50.0) * 0.008
            + (risk_reward_score - 50.0) * 0.010
            + (data_quality_score - 50.0) * 0.006
            + (technical_score - 50.0) * 0.010
            + (weekly_trend_score - 50.0) * 0.006
            + (relative_strength_score - 50.0) * 0.006
            + (daily_entry_score - 50.0) * 0.005
            + (short_momentum_score - 50.0) * 0.010
            + (volume_amount_score - 50.0) * 0.010
            + (sector_score - 50.0) * 0.009
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
        short_momentum_score: float = 50.0,
        volume_amount_score: float = 50.0,
        sector_score: float = 50.0,
        flow_data_marked_missing: bool = False,
        event_type: Optional[str] = None,
        company_catalyst: bool = False,
        trade_plan_rr: Optional[float] = None,
        sector_outflow: Optional[float] = None,
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
            # T+3~T+5: weekly/trend/RS are informational, not hard gates.
            if not weekly_data_available and not daily_data_available:
                failed.append("trend_data_missing")
            if not daily_data_available and daily_entry_score < self.config.min_daily_entry_score:
                failed.append("daily_entry_data_missing")

        short_momentum_ok = short_momentum_score >= 58
        volume_amount_ok = volume_amount_score >= 55
        sector_ok = sector_score >= 45
        strong_short_confirm = primary_catalyst or (short_momentum_ok and volume_amount_ok and sector_ok)

        if (
            prev_day_gain_pct is not None
            and prev_day_gain_pct > self.config.max_prev_day_gain_pct
            and not strong_short_confirm
        ):
            failed.append(f"chase_up>{self.config.max_prev_day_gain_pct}%")

        if (
            ma20_deviation_pct is not None
            and ma20_deviation_pct > self.config.max_ma20_deviation_pct
            and not strong_short_confirm
        ):
            failed.append(f"ma20_deviation>{self.config.max_ma20_deviation_pct}%")

        if self.config.enforce_flow_confirmation_if_available and flow_data_available:
            if capital_flow_score < self.config.min_flow_confirmation_score:
                failed.append(f"flow<{self.config.min_flow_confirmation_score}")
            if market_regime_score < self.config.min_regime_confirmation_score:
                failed.append(f"regime<{self.config.min_regime_confirmation_score}")
        elif (
            self.config.enforce_flow_confirmation_if_available
            and flow_data_marked_missing
        ):
            # 板块资金数据明确缺失时不能静默放行：降至 watch，并给出明确原因。
            failed.append("flow_data_missing")

        if expected_return_t1 < self.config.expected_return_floor_pct:
            failed.append(f"expected_t1<{self.config.expected_return_floor_pct}")
        if self.config.reject_future_evidence and future_evidence_count:
            failed.append(f"evidence_after_analysis>{future_evidence_count}")
        financial_conflict_flags = [
            f
            for f in (risk_veto_report.get("risk_flags") or [])
            if "financial" in str(f).lower()
        ]
        if self.config.risk_veto_enabled and not risk_veto_report.get("passed", True):
            # 财务一致性冲突只以 risk_flag 单独体现，避免 failed_reasons 重复刷屏。
            if financial_conflict_flags:
                failed.extend(financial_conflict_flags)
            else:
                failed.extend(
                    f"risk_veto:{reason}"
                    for reason in risk_veto_report.get("reasons", [])
                )
        # Company-level catalyst hedge: pure sector-flow candidates are not
        # strong enough to justify a poor reward/risk plan.
        if self.config.reject_below_rr_without_company_catalyst:
            no_company_catalyst = not company_catalyst and not primary_catalyst
            if trade_plan_rr is None:
                # trade_plan is attached later in main_loop, so we cannot hard
                # fail here without a number; demote later via post-attach gate.
                pass
            elif trade_plan_rr < self.config.min_rr_without_company_catalyst:
                failed.append(
                    f"rr<{self.config.min_rr_without_company_catalyst}"
                    f"{'_no_company_catalyst' if no_company_catalyst else ''}"
                )

        # Sector ebbing: if a pure sector-flow candidate sits in a sector with a
        # large main-capital net outflow, the 'catalyst' is internally conflicted.
        if (
            event_type in {"sector_flow", ""}
            and not company_catalyst
            and sector_outflow is not None
            and sector_outflow <= -100.0
        ):
            failed.append(f"sector_main_net_outflow_{abs(sector_outflow):.0f}亿")
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

    def _score_short_setup(self, signal: Dict[str, Any]) -> Tuple[float, str]:
        factor = self._technical_factor(signal)
        ret5 = factor.get("ret_5d_pct")
        ret3 = factor.get("ret_3d_pct")
        close_above_ma5 = factor.get("close_above_ma5")
        ma5_slope = factor.get("ma5_slope_pct")
        breakout20 = factor.get("breakout_20d")
        breakout60 = factor.get("breakout_60d")
        if None in (ret3, ret5) and not close_above_ma5 and not ma5_slope and not breakout20:
            return 50.0, "short_setup=missing"

        score = 50.0
        if close_above_ma5:
            score += 10.0
        else:
            score -= 8.0
        try:
            slope = float(ma5_slope)
            score += 6.0 if slope > 0 else -6.0
        except (TypeError, ValueError):
            pass
        try:
            r5 = float(ret5)
            r3 = float(ret3) if ret3 is not None else r5
            blended = r3 * 0.4 + r5 * 0.6
            if 0 <= blended <= 12:
                score += 16.0
            elif blended < 0:
                score -= 12.0
            elif blended > 25:
                score -= 10.0
            else:
                score += 6.0
        except (TypeError, ValueError):
            pass
        if breakout20 or breakout60:
            score += 6.0
        score = max(0.0, min(100.0, score))
        return score, f"short_mom={ret3 is not None or ret5 is not None},ma5={close_above_ma5},slope={ma5_slope},breakout={bool(breakout20 or breakout60)}"

    def _score_volume_amount(self, signal: Dict[str, Any]) -> Tuple[float, str]:
        factor = self._technical_factor(signal)
        vol = self._factor_value(signal, "volume_ratio")
        amount = self._factor_value(signal, "amount_ratio")
        change_pct = self._factor_value(signal, "change_pct")
        try:
            vol_f = float(vol) if vol is not None else None
        except (TypeError, ValueError):
            vol_f = None
        try:
            amount_f = float(amount) if amount is not None else None
        except (TypeError, ValueError):
            amount_f = None
        try:
            change_f = float(change_pct) if change_pct is not None else None
        except (TypeError, ValueError):
            change_f = None

        score = 50.0
        if vol_f is not None:
            if vol_f >= 1.2:
                score += 12.0
            elif vol_f >= 1.0:
                score += 4.0
            else:
                score -= 8.0
        if amount_f is not None:
            if amount_f >= 1.2:
                score += 8.0
            elif amount_f >= 1.0:
                score += 3.0
            else:
                score -= 5.0
        if change_f is not None and 2.0 <= change_f <= 10.0:
            score += 8.0
        elif change_f is not None and change_f > 15.0:
            score -= 6.0
        score = max(0.0, min(100.0, score))
        return score, f"vol={vol_f},amount={amount_f},chg={change_f}"

    def _score_sector_strength(self, signal: Dict[str, Any]) -> Tuple[float, str]:
        factor = self._technical_factor(signal)
        s1 = self._factor_value(signal, "sector_1d_return")
        s3 = self._factor_value(signal, "sector_3d_return")
        rank = self._factor_value(signal, "sector_rank")
        svs = self._factor_value(signal, "stock_vs_sector_strength")
        if s1 is None and s3 is None and rank is None and svs is None:
            return 50.0, "sector=missing"
        score = 50.0
        try:
            f1 = float(s1)
            score += 8.0 if f1 >= 1.0 else -4.0 if f1 < 0 else 0.0
        except (TypeError, ValueError):
            pass
        try:
            f3 = float(s3)
            score += 10.0 if f3 >= 3.0 else -6.0 if f3 < 0 else 0.0
        except (TypeError, ValueError):
            pass
        try:
            fr = float(rank)
            if fr <= 20:
                score += 10.0
            elif fr <= 50:
                score += 3.0
            elif fr >= 90:
                score -= 8.0
        except (TypeError, ValueError):
            pass
        try:
            fsvs = float(svs)
            if fsvs >= 3.0:
                score += 6.0
            elif fsvs < 0:
                score -= 6.0
        except (TypeError, ValueError):
            pass
        score = max(0.0, min(100.0, score))
        return score, f"sector1d={s1},sector3d={s3},rank={rank},svs={svs}"

    def _score_entry_quality(
        self,
        signal: dict,
        short_momentum_score: float,
        volume_amount_score: float,
        sector_strength_score: float,
        catalyst_score: float,
    ) -> Tuple[float, str, dict]:
        """新增第五维度：入场位置/拥挤度/加速末端。

        基于 2400 条 6/7/8 月候选面板校准：
          - 10 = (3行) 个股 15~25 + 板块拥挤>15 -> T5 -16%
          - 板块拥挤 3-8% + 个股 8-25% -> 基本面/轮动刚启动，反而可加
          - 个股 5D>25 + 板块不拥挤 -> T5 仍正，不砍也不重罚
        """
        factor = self._technical_factor(signal)
        ret3 = self._safe_value(self._factor_value(signal, "ret_3d_pct"))
        ret5 = self._safe_value(self._factor_value(signal, "ret_5d_pct"))
        ret10 = self._safe_value(self._factor_value(signal, "ret_10d_pct"))
        ret20_s = self._safe_value(self._factor_value(signal, "ret_20d_pct"))
        s1 = self._safe_value(self._factor_value(signal, "sector_1d_return"))
        s3 = self._safe_value(self._factor_value(signal, "sector_3d_return"))
        s5 = self._safe_value(self._factor_value(signal, "sector_5d_return"))
        s10 = self._safe_value(self._factor_value(signal, "sector_10d_return"))
        rank = self._safe_value(self._factor_value(signal, "sector_rank"))
        svs = self._safe_value(self._factor_value(signal, "stock_vs_sector_strength"))
        ma20 = self._safe_value(self._factor_value(signal, "ma20_deviation_pct"))
        prev_gain = self._safe_value(self._factor_value(signal, "change_pct"))
        rsi = self._safe_value(self._factor_value(signal, "rsi"))
        breakout20 = bool(factor.get("breakout_20d") or signal.get("breakout_20d"))
        breakout60 = bool(factor.get("breakout_60d") or signal.get("breakout_60d"))
        close_above_ma5 = bool(factor.get("close_above_ma5") or signal.get("close_above_ma5"))

        report = {
            "entry_quality_score": 60.0,
            "crowding_score": 0.0,
            "crowding_mean": None,
        }
        sectors = [x for x in (s3, s5, s10) if x is not None]
        mean_sector = (sum(sectors) / len(sectors)) if sectors else None

        if all(v is None for v in (ret3, ret5, ret10, mean_sector, ma20, rsi)):
            return 0.0, "entry=missing", report

        delta = 0.0
        reasons = []
        crowding = 0.0

        # --- 板块拥挤度 (0-100) ---
        if mean_sector is not None:
            report["crowding_mean"] = round(float(mean_sector), 3)
            if mean_sector >= 15:
                crowding = 80.0
                reasons.append(f"sector_crowded={mean_sector:.1f}%")
            elif mean_sector >= 12:
                crowding = 70.0
                reasons.append(f"sector_crowded={mean_sector:.1f}%")
            elif mean_sector >= 8:
                crowding = 55.0
                reasons.append(f"sector_warm={mean_sector:.1f}%")
            elif mean_sector >= 3:
                crowding = 30.0
                reasons.append(f"sector_starting={mean_sector:.1f}%")
            else:
                crowding = 10.0
                reasons.append(f"sector_cold={mean_sector:.1f}%")
            report["crowding_score"] = round(crowding, 1)

        # --- 个股涨幅（软扣分，不 reject）---
        if ret5 is not None:
            if ret5 < 8:
                # 温和/刚启动
                if close_above_ma5 or breakout20:
                    delta += 1.0
                    reasons.append(f"ret5={ret5:.1f}%_early")
                else:
                    delta += 0.0
                reasons.append(f"ret5={ret5:.1f}%_normal")
            elif ret5 < 15:
                delta -= 2.0
                reasons.append(f"ret5={ret5:.1f}%_mild")
            elif ret5 < 18:
                delta -= 4.0
                reasons.append(f"ret5={ret5:.1f}%_extended")
            elif ret5 < 25:
                # 高危区：只有板块不拥挤+突破可部分对冲
                pen = -8.0
                if mean_sector is not None and mean_sector < 8 and (breakout20 or breakout60):
                    pen = -3.0
                    reasons.append("breakout_offsets")
                if mean_sector is not None and mean_sector >= 15:
                    pen = -15.0
                    reasons.append("crowd_exhaust")
                delta += pen
                reasons.append(f"ret5={ret5:.1f}%_extended")
            else:
                # >25 面板里 T5 仍 +1.5，不重罚；仅板块极拥挤才扣更多
                pen = -6.0
                if mean_sector is not None and mean_sector >= 12:
                    pen = -12.0
                    reasons.append("crowd_high_ret")
                if mean_sector is not None and mean_sector < 8 and (breakout20 or breakout60):
                    pen = -2.0
                    reasons.append("ret_high_but_breakout")
                delta += pen
                reasons.append(f"ret5={ret5:.1f}%_high")

        if ret10 is not None and ret10 > 30:
            delta -= 1.0
            reasons.append(f"ret10={ret10:.1f}%")

        # --- 加速末端 ---
        ret1 = self._safe_value(self._factor_value(signal, "ret_1d_pct"))
        if ret1 is not None and ret5 is not None:
            if ret1 > 12 and ret5 > 18:
                delta -= 6.0
                reasons.append(f"accel_end={ret1:.1f}%/{ret5:.1f}%")
        if prev_gain is not None and prev_gain > 12.0:
            delta -= 2.0
            reasons.append(f"prev_chg={prev_gain:.1f}%")

        # --- 板块拥挤-个股交叉（对痛苦组合下调）---
        if mean_sector is not None and ret5 is not None:
            if mean_sector >= 15 and ret5 >= 8:
                delta -= 5.0
                reasons.append("crowd_stock_exhaust")
            elif mean_sector >= 12 and ret5 > 12:
                delta -= 3.0
                reasons.append("warm_stock_extended")
            # 板块刚启动但个股还在加速且不极端 -> 不好但别太过了
            elif mean_sector >= 3 and mean_sector < 8 and 8 <= ret5 < 25:
                delta += 2.0
                reasons.append("sector_starting_stock_running")

        if s1 is not None and s1 >= 4.0 and crowding >= 55:
            delta -= 2.0
            reasons.append(f"sector1d_hot={s1:.1f}%")
        if rank is not None and rank <= 10 and crowding >= 70:
            delta -= 1.0
            reasons.append(f"sector_rank_hot={rank:.0f}")

        # --- 个股 vs 板块 ---
        if svs is not None:
            if svs >= 5.0 and crowding < 45:
                delta += 3.0
                reasons.append(f"svs_strong={svs:.1f}%")
            elif svs >= 8.0 and crowding >= 55:
                delta -= 1.0
                reasons.append(f"svs_strong_but_crowded={svs:.1f}%")

        # --- RSI/MA20 ---
        if rsi is not None and rsi > 80:
            delta -= 2.0
            reasons.append(f"rsi_hot={rsi:.1f}")
        if ma20 is not None and ma20 > 25:
            delta -= 2.0
            reasons.append(f"ma20_ext={ma20:.1f}%")
        elif ma20 is not None and ma20 > 18:
            delta -= 1.0
            reasons.append(f"ma20_warm={ma20:.1f}%")

        # --- 对冲 ---
        if catalyst_score >= 80:
            delta += 2.0
            reasons.append("catalyst_bonus")
        if volume_amount_score >= 70 and crowding < 55:
            delta += 1.0
            reasons.append("volume_confirmed")
        if short_momentum_score >= 75 and crowding < 55:
            delta += 1.0
            reasons.append("short_setup")
        if sector_strength_score >= 70 and crowding < 45:
            delta += 2.0
            reasons.append("sector_strong_but_not_crowded")

        report["entry_quality_score"] = round(max(0.0, min(100.0, 60.0 + delta * 2.5)), 1)
        return max(-25.0, min(8.0, delta)), ",".join(reasons), report

    def _safe_value(self, value) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

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

    def _event_type(self, signal: Dict[str, Any]) -> str:
        raw = str(signal.get("event_type") or "").strip().lower()
        if raw:
            return raw
        # fall back to any evidence doc that carries an event type tag
        for ev in signal.get("evidence_list") or []:
            et = str(ev.get("event_type") or "").strip().lower()
            if et:
                return et
        return ""

    def _has_company_level_catalyst(
        self,
        signal: Dict[str, Any],
        evidence_list: List[Dict[str, Any]],
    ) -> bool:
        """True if a T+1~T+3 catalyst is company-specific (order, earnings,
        price-hike, M&A, repurchase, etc.), rather than genus-level sector_flow"""
        event_type = self._event_type(signal)
        if event_type and event_type not in {"sector_flow", "technical_reversal", "none"}:
            return True

        text = " ".join(
            [
                str(signal.get("event_summary") or ""),
                str(signal.get("event_type") or ""),
                " ".join(str(ev.get("description") or "") for ev in evidence_list),
            ]
        )
        candidate_catalyst_markers = [
            "业绩预增", "上修", "并购", "重组", "回购", "分红",
            "中标", "获批", "订单超预期", "新产品", "涨价", "定增",
        ]
        return any(kw in text for kw in candidate_catalyst_markers)

    def _trade_plan_rr(self, signal: Dict[str, Any]) -> Optional[float]:
        plan = signal.get("trade_plan") or {}
        if isinstance(plan, dict):
            try:
                rr = plan.get("plan", {}).get("rr_1")
                if rr is not None:
                    return float(rr)
            except (TypeError, ValueError):
                pass
            try:
                rr = plan.get("rr_1")
                if rr is not None:
                    return float(rr)
            except (TypeError, ValueError):
                pass
        return None

    def _classify_risk_state(
        self,
        signal: Dict[str, Any],
        evidence_list: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """A/B/C/D style state label for the candidate."""
        factor = self._technical_factor(signal)
        company = self._has_company_level_catalyst(signal, evidence_list)
        event_type = self._event_type(signal)
        sector_only = event_type in {"sector_flow", ""} and not company

        rs20 = self._extract_relative_strength_20(signal)
        ma20_raw = self._factor_value(signal, "ma20_deviation_pct")
        try:
            ma20 = float(ma20_raw) if ma20_raw is not None else None
        except (TypeError, ValueError):
            ma20 = None
        breakout20 = self._factor_value(signal, "breakout_20d")
        short_mom = self._factor_value(signal, "short_setup_score")

        if sector_only:
            state = "D_纯板块跟随"
            label = "sector_follow"
        elif company:
            state = "B_公司催化启动"
            label = "company_driven"
        elif (rs20 is not None and rs20 < 0) and (ma20 is None or ma20 < 5):
            state = "B_底部启动"
            label = "bottom_launch"
        elif ma20 is not None and ma20 > 15:
            state = "C_高位加速"
            label = "extended_momentum"
        else:
            state = "A_顺势启动"
            label = "trend_launch"

        driver_bucket = "company" if company else ("sector_follow" if sector_only else "transaction")
        return {
            "risk_state": state,
            "position_type": label,
            "driver_quality": driver_bucket,
        }

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
