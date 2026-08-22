"""Main Trend Following Engine - 主升浪趋势跟踪系统独立数据结构。

对齐“MTF：不是总分，而是状态机”：
  - Layer 0 DataQuality：硬过滤，不合格直接不进入系统。
  - Layer 1 MarketRegime：A/B/C/D 市场环境，决定准入与风险预算。
  - Layer 2 TrendState：S0~S5，主升浪核心状态机。
  - Layer 3 TrendQuality：A/B/C，避免总量分重复计权。
  - Layer 4 SectorState：Ex-Self 板块强度，避免个股推板块再反向加分。
  - Layer 5 CatalystState：结构化事件，LLM 只产出结构化信息，Engine 确定性计算。
  - T+1 ExecutionState：Gap/Auction/Index/Sector/VWAP/OrderFlow。
  - Layer 6 RiskState：风险预算定仓位。
  - Layer 7 PositionStateMachine：HOLD/ADD/DECAY/REDUCE/EXIT。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GateResult:
    """单层 Gate 结果，替代单一大总分。"""
    name: str = ""
    passed: bool = False
    score: float = 0.0
    reason: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "score": round(self.score, 3),
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass
class DataQualityState:
    """Layer 0：数据可靠性。"""
    valid: bool = False
    reasons: List[str] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"valid": self.valid, "reasons": list(self.reasons), "detail": self.detail}


@dataclass
class MarketRegimeState:
    """Layer 1：A/B/C/D 市场环境。"""
    regime: str = "D"              # A 强趋势 / B 偏强 / C 震荡 / D 弱势
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)
    risk_multiplier: float = 1.0    # C 级 -> 0.5
    allow_new: bool = False
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime,
            "score": round(self.score, 2),
            "reasons": list(self.reasons),
            "risk_multiplier": self.risk_multiplier,
            "allow_new": self.allow_new,
            "detail": self.detail,
        }


@dataclass
class TrendState:
    """Layer 2：主升浪状态 S0~S5。"""
    state: str = "S0"
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)
    tradeable: bool = False         # S1/S2/S3 才允许新增候选
    action_hint: str = ""          # 用于提交到 T+1 Candidate Pool
    atr_quality_ok: bool = True    # 新高+ATR升 vs 不新高+ATR升 联合判断
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "score": round(self.score, 2),
            "reasons": list(self.reasons),
            "tradeable": self.tradeable,
            "action_hint": self.action_hint,
            "atr_quality_ok": self.atr_quality_ok,
            "detail": self.detail,
        }


@dataclass
class TrendQuality:
    """Layer 3：趋势质量 A/B/C/D，不做“我综合给 83.5 分”。"""
    grade: str = "D"
    score: float = 0.0
    family: Dict[str, Any] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    multiplier: float = 0.0
    residual_rs_vs_index: Optional[float] = None
    residual_rs_vs_sector: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grade": self.grade,
            "score": round(self.score, 2),
            "family": self.family,
            "reasons": list(self.reasons),
            "multiplier": self.multiplier,
            "residual_rs_vs_index": self.residual_rs_vs_index,
            "residual_rs_vs_sector": self.residual_rs_vs_sector,
        }


@dataclass
class SectorState:
    """Layer 4：板块环境（Ex-Self 原则）。"""
    sector_name: str = ""
    sector_strength_pct: float = 0.0
    breadth_pct: Optional[float] = None
    rank: Optional[int] = None
    ex_self: bool = True
    ex_self_detail: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    grade: str = "D"
    passed: bool = False
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sector_name": self.sector_name,
            "sector_strength_pct": self.sector_strength_pct,
            "breadth_pct": self.breadth_pct,
            "rank": self.rank,
            "ex_self": self.ex_self,
            "ex_self_detail": self.ex_self_detail,
            "score": round(self.score, 2),
            "grade": self.grade,
            "passed": self.passed,
            "reasons": list(self.reasons),
        }


@dataclass
class CatalystState:
    """Layer 5：催化。LLM只负责结构化解释；Engine只做确定性Gate。"""
    has_event: bool = False
    event_type: str = ""
    event_level: str = ""          # S/A/B/C
    freshness: float = 0.0
    company_specific: bool = False
    price_reaction: str = ""       # positive/negative/neutral
    score: float = 0.0
    detail: Dict[str, Any] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_event": self.has_event,
            "event_type": self.event_type,
            "event_level": self.event_level,
            "freshness": self.freshness,
            "company_specific": self.company_specific,
            "price_reaction": self.price_reaction,
            "score": round(self.score, 2),
            "detail": self.detail,
            "reasons": list(self.reasons),
        }


@dataclass
class ExecutionState:
    """Layer 6：T+1 两阶段执行确认（Gap / Auction / Index / Sector / VWAP / Flow）。

    Phase 1 = Auction Signal（9:25 竞价先验，预判）
    Phase 2 = Real-time Confirmation（9:30 后价格/VWAP/量/盘口/指数/板块实时确认）
    """
    opening_gap_pct: Optional[float] = None
    phase: str = "PENDING"            # PENDING / AUCTION_SIGNAL / PHASE1_READY / PHASE2_EXECUTE / ABANDON / CANCEL
    auction_score: float = 0.0
    index_state: str = ""
    sector_state: str = ""
    vwap_state: bool = False
    order_flow_score: float = 0.0
    intraday_structure_score: float = 0.0
    active_buy_pct: Optional[float] = None
    bid_ask_imbalance: Optional[float] = None
    bid_recovery_score: Optional[float] = None
    low_break_failure: Optional[float] = None
    gap_penalty: float = 0.0
    confirmed: bool = False
    abandon_reason: str = ""
    reasons: List[str] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "opening_gap_pct": self.opening_gap_pct,
            "phase": self.phase,
            "auction_score": round(self.auction_score, 2),
            "index_state": self.index_state,
            "sector_state": self.sector_state,
            "vwap_state": self.vwap_state,
            "order_flow_score": round(self.order_flow_score, 2),
            "intraday_structure_score": round(self.intraday_structure_score, 2),
            "active_buy_pct": self.active_buy_pct,
            "bid_ask_imbalance": self.bid_ask_imbalance,
            "bid_ask_imbalance_pct": None if self.bid_ask_imbalance is None else round((self.bid_ask_imbalance - 1.0) * 100.0, 2),
            "bid_recovery_score": self.bid_recovery_score,
            "low_break_failure": self.low_break_failure,
            "gap_penalty": self.gap_penalty,
            "confirmed": self.confirmed,
            "abandon_reason": self.abandon_reason,
            "reasons": list(self.reasons),
            "detail": self.detail,
        }


@dataclass
class RiskState:
    """Layer 6：风险预算。AccountRisk / StopDistance * QualityMultiplier。"""
    account_risk_pct: float = 1.0
    stop_distance_pct: Optional[float] = None
    stop_distance_abs: Optional[float] = None
    quality_multiplier: float = 1.0
    suggested_position_pct: Optional[float] = None
    max_position_pct: float = 50.0
    pass_or_wait: bool = False
    reason: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "account_risk_pct": self.account_risk_pct,
            "stop_distance_pct": self.stop_distance_pct,
            "stop_distance_abs": self.stop_distance_abs,
            "quality_multiplier": self.quality_multiplier,
            "suggested_position_pct": self.suggested_position_pct,
            "max_position_pct": self.max_position_pct,
            "pass_or_wait": self.pass_or_wait,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass
class PositionState:
    """Layer 7：持仓状态机 HOLD / ADD / DECAY / REDUCE / EXIT。"""
    state: str = "HOLD"
    action: str = "hold"          # hold/add/decay/reduce/exit
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)
    add_allowed: bool = False     # 只允许盈利趋势再确认加仓，不做亏损补仓
    trend_decay_score: float = 0.0
    entry_reentry_ok: bool = False   # 盈利状态下回踩企稳/重新突破允许加仓

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "action": self.action,
            "score": round(self.score, 2),
            "reasons": list(self.reasons),
            "add_allowed": self.add_allowed,
            "entry_reentry_ok": self.entry_reentry_ok,
            "trend_decay_score": round(self.trend_decay_score, 2),
        }


@dataclass
class MTFCandidate:
    """T日候选：进入 T+1 Candidate Pool。"""
    symbol_code: str
    symbol_name: str
    trade_date: str
    trend_state: str = "S0"
    trend_quality: str = "D"
    market_regime: str = "D"
    sector_name: str = ""
    catalyst_score: float = 0.0
    risk_multiplier: float = 1.0
    entry_score: float = 0.0
    eligible: bool = False
    reasons: List[str] = field(default_factory=list)
    technical_factor: Dict[str, Any] = field(default_factory=dict)
    market_regime_state: Optional[MarketRegimeState] = None
    trend_state_info: Optional[TrendState] = None
    quality_info: Optional[TrendQuality] = None
    sector_info: Optional[SectorState] = None
    catalyst_info: Optional[CatalystState] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol_code": self.symbol_code,
            "symbol_name": self.symbol_name,
            "trade_date": self.trade_date,
            "trend_state": self.trend_state,
            "trend_quality": self.trend_quality,
            "market_regime": self.market_regime,
            "sector_name": self.sector_name,
            "catalyst_score": round(self.catalyst_score, 2),
            "risk_multiplier": self.risk_multiplier,
            "entry_score": round(self.entry_score, 2),
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "market_regime_state": self.market_regime_state.to_dict() if self.market_regime_state else None,
            "trend_state_info": self.trend_state_info.to_dict() if self.trend_state_info else None,
            "trend_quality_info": self.quality_info.to_dict() if self.quality_info else None,
            "sector_state": self.sector_info.to_dict() if self.sector_info else None,
            "catalyst_state": self.catalyst_info.to_dict() if self.catalyst_info else None,
        }


@dataclass
class MTFDiscovery:
    """当日常规扫描池。"""
    trade_date: str = ""
    all_candidates: List[MTFCandidate] = field(default_factory=list)
    eligible: List[MTFCandidate] = field(default_factory=list)
    universe_count: int = 0
    market_regime: Optional[MarketRegimeState] = None
    context_string: str = ""
    scan_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "candidates": [c.to_dict() for c in self.all_candidates],
            "eligible": [c.to_dict() for c in self.eligible],
            "universe_count": self.universe_count,
            "market_regime": self.market_regime.to_dict() if self.market_regime else None,
            "context_string": self.context_string,
            "scan_errors": self.scan_errors,
        }


@dataclass
class BuySignal:
    """T+1 候选 / 最终可执行买入。"""
    symbol_code: str
    symbol_name: str
    trade_date: str
    lifecycle_state: str = "T+1候选"
    pool_type: str = "主升浪"
    divergence_mode: str = "mtf"
    divergence_score: float = 0.0
    entry_quality_score: float = 0.0
    weak_to_strong_score: float = 0.0
    t1_buy_score: float = 0.0
    buy_ready: bool = False
    reasons: List[str] = field(default_factory=list)
    candidate: str = "MAIN_TREND"
    gates: Dict[str, Any] = field(default_factory=dict)
    trend_state: str = ""
    trend_quality: str = ""
    market_regime: str = ""
    suggested_position_pct: Optional[float] = None
    stop_loss_pct: float = -6.0
    take_profit_pct: float = 6.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol_code": self.symbol_code,
            "symbol_name": self.symbol_name,
            "trade_date": self.trade_date,
            "lifecycle_state": self.lifecycle_state,
            "pool_type": self.pool_type,
            "divergence_mode": self.divergence_mode,
            "divergence_score": self.divergence_score,
            "entry_quality_score": self.entry_quality_score,
            "weak_to_strong_score": self.weak_to_strong_score,
            "t1_buy_score": round(self.t1_buy_score, 2),
            "buy_ready": self.buy_ready,
            "reasons": list(self.reasons),
            "candidate": self.candidate,
            "gates": {k: (v.to_dict() if hasattr(v, "to_dict") else v) for k, v in self.gates.items()},
            "trend_state": self.trend_state,
            "trend_quality": self.trend_quality,
            "market_regime": self.market_regime,
            "suggested_position_pct": self.suggested_position_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
        }


@dataclass
class Holding:
    symbol_code: str
    symbol_name: str
    entry_date: str
    entry_price: float
    quantity: int = 0
    holding_days: int = 0
    highest_price: float = 0.0
    current_price: Optional[float] = None
    buy_score: float = 0.0
    signal_tier: str = "A"
    trade_plan: Dict[str, Any] = field(default_factory=dict)
    stop_loss_price: Optional[float] = None
    atr_trailing_stop: Optional[float] = None   # ATR trailing stop（价格绝对值）
    prev_close: Optional[float] = None          # 前一日收盘，用于“次日站回”
    ma20: Optional[float] = None                # 结构止损轨道：Close<MA20 判断
    realtime_quote: Dict[str, Any] = field(default_factory=dict)
    order_flow_score: float = 50.0


@dataclass
class ExitDecision:
    symbol_code: str
    symbol_name: str
    action: str = "hold"
    reason: str = ""
    urgency: str = "normal"
    exit_score: float = 0.0
    current_return_pct: float = 0.0
    stop_loss_triggered: bool = False
    take_profit_triggered: bool = False
    reduce_triggered: bool = False
    add_allowed: bool = False
    state: str = "HOLD"
    position_state: str = "HOLD"
    decay_score: float = 0.0
    atr_trailing_stop_triggered: bool = False
    recapture_triggered: bool = False
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol_code": self.symbol_code,
            "symbol_name": self.symbol_name,
            "action": self.action,
            "reason": self.reason,
            "urgency": self.urgency,
            "exit_score": round(self.exit_score, 2),
            "current_return_pct": self.current_return_pct,
            "stop_loss_triggered": self.stop_loss_triggered,
            "take_profit_triggered": self.take_profit_triggered,
            "reduce_triggered": self.reduce_triggered,
            "add_allowed": self.add_allowed,
            "state": self.state,
            "position_state": self.position_state,
            "decay_score": round(self.decay_score, 2),
            "atr_trailing_stop_triggered": self.atr_trailing_stop_triggered,
            "recapture_triggered": self.recapture_triggered,
            "reasons": list(self.reasons),
        }
