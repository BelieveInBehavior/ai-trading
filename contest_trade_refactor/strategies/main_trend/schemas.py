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
class MarketSentimentState:
    """Layer 1b：短线赚钱效应/热度，不替代指数 Regime，只调节仓位与门槛。"""
    score: float = 50.0
    grade: str = "B"               # A/B/C/D：短线赚钱效应
    risk_sentiment: str = "neutral" # risk_on / neutral / risk_off
    passed: bool = True
    available: bool = False
    risk_multiplier: float = 1.0
    reasons: List[str] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 2),
            "grade": self.grade,
            "risk_sentiment": self.risk_sentiment,
            "passed": self.passed,
            "available": self.available,
            "risk_multiplier": self.risk_multiplier,
            "reasons": list(self.reasons),
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
class FundamentalState:
    """公司基本面状态。按公告日更新；每日快照读取截至当日最新可见值。"""
    state: str = "FU"             # F1改善/F2稳定/F3分化/F4恶化/F5重大风险/FU未知
    score: float = 50.0
    available: bool = False
    passed: bool = True             # F4/F5 禁止新增，但不替代价格趋势状态
    risk_multiplier: float = 1.0
    as_of_date: str = ""
    report_period: str = ""
    reasons: List[str] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "score": round(self.score, 2),
            "available": self.available,
            "passed": self.passed,
            "risk_multiplier": self.risk_multiplier,
            "as_of_date": self.as_of_date,
            "report_period": self.report_period,
            "reasons": list(self.reasons),
            "risk_flags": list(self.risk_flags),
            "detail": self.detail,
        }


@dataclass
class HotMoneyState:
    """Layer 5b：个股热钱/龙虎榜状态。只做确认、加分或风险降权，不单独触发 BUY。"""
    score: float = 50.0
    grade: str = "B"
    passed: bool = True
    has_lhb: bool = False
    has_limit_up: bool = False
    risk_flag: str = ""
    reasons: List[str] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 2),
            "grade": self.grade,
            "passed": self.passed,
            "has_lhb": self.has_lhb,
            "has_limit_up": self.has_limit_up,
            "risk_flag": self.risk_flag,
            "reasons": list(self.reasons),
            "detail": self.detail,
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
    """Layer 7：持仓状态机 HOLD / ADD / DECAY / REDUCE / EXIT。

    ADD 三层分离：
      - add_setup：信号层。判断“能不能加”（重新突破 / 健康回踩 / 加速 + 板块/RS/趋势结构），
        不把“过去盈亏”当作开关。
      - add_confirmation：确认层。盘中执行是否安全（VWAP / 盘口 / 日内结构）。
      - add_size_pct：风险引擎输出。浮盈只参与加多少，不参与能不能加。
    核心哲学：盈利不是加仓理由，新的趋势确认才是。
    """
    state: str = "HOLD"
    action: str = "hold"          # hold/add/decay/reduce/exit
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)
    add_allowed: bool = False     # 兼容旧字段；现等价于 add_setup and add_confirmation
    trend_decay_score: float = 0.0
    entry_reentry_ok: bool = False   # 兼容旧字段；已由 add_setup / add_confirmation 取代
    add_setup: bool = False          # Setup Layer：结构/量价/板块/RS 是否构成新 Alpha
    add_confirmation: bool = False   # Confirmation Layer：盘中执行二次确认（VWAP/盘口/日内结构）
    add_signal: str = ""
    add_setup_class: str = ""        # A 健康回踩 / B 放量突破 / C 强势加速 / "" 无
    add_size_pct: float = 0.0
    add_reason: str = ""
    sector_source: str = "missing"
    rs_source: str = "missing"
    high_volume_class: str = ""            # extension / rejection / neutral
    high_volume_reason: str = ""
    next_day_guard_break_vwap: bool = False
    next_day_guard_vwap: Optional[float] = None
    next_day_guard_high: Optional[float] = None
    target_price_1: Optional[float] = None
    target_price_2: Optional[float] = None
    profit_protect_price: Optional[float] = None
    profit_protect_level: str = ""
    profit_protect_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "action": self.action,
            "score": round(self.score, 2),
            "reasons": list(self.reasons),
            "add_allowed": self.add_allowed,
            "entry_reentry_ok": self.entry_reentry_ok,
            "trend_decay_score": round(self.trend_decay_score, 2),
            "add_setup": self.add_setup,
            "add_confirmation": self.add_confirmation,
            "add_signal": self.add_signal,
            "add_setup_class": self.add_setup_class,
            "add_size_pct": round(self.add_size_pct, 3),
            "add_reason": self.add_reason,
            "sector_source": self.sector_source,
            "rs_source": self.rs_source,
            "high_volume_class": self.high_volume_class,
            "high_volume_reason": self.high_volume_reason,
            "next_day_guard_break_vwap": self.next_day_guard_break_vwap,
            "next_day_guard_vwap": self.next_day_guard_vwap,
            "next_day_guard_high": self.next_day_guard_high,
            "target_price_1": self.target_price_1,
            "target_price_2": self.target_price_2,
            "profit_protect_price": self.profit_protect_price,
            "profit_protect_level": self.profit_protect_level,
            "profit_protect_reason": self.profit_protect_reason,
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
    fundamental_info: Optional[FundamentalState] = None
    market_sentiment_state: Optional[MarketSentimentState] = None
    hot_money_state: Optional[HotMoneyState] = None

    def to_dict(self) -> Dict[str, Any]:
        factor = self.technical_factor or {}
        price_context = {
            "close": factor.get("close"),
            "atr": factor.get("atr"),
            "atr_pct": factor.get("atr_pct"),
            "ma20": factor.get("ma20"),
            "ma20_deviation_pct": factor.get("ma20_deviation_pct"),
        }
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
            "pre_score": round(self.entry_score, 2),
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "price_context": price_context,
            "technical_factor": self.technical_factor,
            "market_regime_state": self.market_regime_state.to_dict() if self.market_regime_state else None,
            "trend_state_info": self.trend_state_info.to_dict() if self.trend_state_info else None,
            "trend_quality_info": self.quality_info.to_dict() if self.quality_info else None,
            "sector_state": self.sector_info.to_dict() if self.sector_info else None,
            "catalyst_state": self.catalyst_info.to_dict() if self.catalyst_info else None,
            "fundamental_state": self.fundamental_info.to_dict() if self.fundamental_info else None,
            "market_sentiment_state": self.market_sentiment_state.to_dict() if self.market_sentiment_state else None,
            "hot_money_state": self.hot_money_state.to_dict() if self.hot_money_state else None,
        }


@dataclass
class MTFDiscovery:
    """当日常规扫描池。"""
    trade_date: str = ""
    all_candidates: List[MTFCandidate] = field(default_factory=list)
    eligible: List[MTFCandidate] = field(default_factory=list)
    universe_count: int = 0
    market_regime: Optional[MarketRegimeState] = None
    market_sentiment: Optional[MarketSentimentState] = None
    context_string: str = ""
    scan_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "candidates": [c.to_dict() for c in self.all_candidates],
            "eligible": [c.to_dict() for c in self.eligible],
            "universe_count": self.universe_count,
            "market_regime": self.market_regime.to_dict() if self.market_regime else None,
            "market_sentiment": self.market_sentiment.to_dict() if self.market_sentiment else None,
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
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0
    reference_price: Optional[float] = None
    initial_stop: Optional[float] = None
    trailing_stop: Optional[float] = None
    current_stop: Optional[float] = None
    theme: str = ""
    pre_score: Optional[float] = None
    t1_state: str = "WAIT"
    technical_factor: Dict[str, Any] = field(default_factory=dict)
    sector_state: Optional[Dict[str, Any]] = None
    trend_quality_info: Optional[Dict[str, Any]] = None
    hot_money_state: Optional[Dict[str, Any]] = None
    market_sentiment_state: Optional[Dict[str, Any]] = None
    fundamental_state: Optional[Dict[str, Any]] = None
    relative_strength_cross_section_pct: Optional[float] = None
    relative_strength_score: Optional[float] = None
    sector_rank: Optional[float] = None

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
            "reference_price": self.reference_price,
            "initial_stop": self.initial_stop,
            "trailing_stop": self.trailing_stop,
            "current_stop": self.current_stop,
            "theme": self.theme,
            "pre_score": self.pre_score,
            "t1_state": self.t1_state,
            "technical_factor": self.technical_factor,
            "sector_state": self.sector_state,
            "trend_quality_info": self.trend_quality_info,
            "hot_money_state": self.hot_money_state,
            "market_sentiment_state": self.market_sentiment_state,
            "fundamental_state": self.fundamental_state,
            "relative_strength_cross_section_pct": self.relative_strength_cross_section_pct,
            "relative_strength_score": self.relative_strength_score,
            "sector_rank": self.sector_rank,
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
    ma10: Optional[float] = None                # V2.0: MA10为主导持有轨道，Close>MA10坚定持有
    ma20: Optional[float] = None                # V2.0: MA20为强制清仓硬约束
    prev_ma20: Optional[float] = None           # 保留兼容旧报告；V2.0不再需要双日确认
    highest_close: Optional[float] = None       # 持有期间最高收盘价，用于 trailing stop
    event_catalyst: Optional[Dict[str, Any]] = None  # 极端事件/利空快照（Catalyst=EXTREME/NEGATIVE）
    realtime_quote: Dict[str, Any] = field(default_factory=dict)
    order_flow_score: float = 50.0
    trend_state: str = ""
    trend_state_info: Optional[Dict[str, Any]] = None
    previous_trend_state: str = ""
    trend_state_streak: int = 0
    trend_state_as_of: str = ""
    trend_state_changed_at: str = ""
    trend_reason_code: str = ""
    trend_confidence: float = 0.0
    fundamental_state: str = "FU"
    fundamental_state_info: Optional[Dict[str, Any]] = None


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
    add_setup: bool = False
    add_confirmation: bool = False
    add_signal: str = ""
    add_setup_class: str = ""
    add_size_pct: float = 0.0
    add_reason: str = ""
    sector_source: str = ""
    rs_source: str = ""
    state: str = "HOLD"
    position_state: str = "HOLD"
    decay_score: float = 0.0
    atr_trailing_stop_triggered: bool = False
    recapture_triggered: bool = False
    exit_level: str = ""          # P0/P1/P2/P3/P4
    exit_class: str = ""          # SELL_NOW / SELL_CONFIRM / SELL_TRAILING / REDUCE / HOLD
    reduce_pct: float = 0.0
    ma20_confirm_days: int = 0
    highest_close: Optional[float] = None
    trailing_stop_price: Optional[float] = None
    decay_signals: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    high_volume_class: str = ""              # extension / rejection / neutral
    high_volume_reason: str = ""
    trend_state: str = ""
    trend_state_reason: str = ""
    previous_trend_state: str = ""
    trend_state_streak: int = 0
    trend_reason_code: str = ""
    trend_confidence: float = 0.0
    trend_state_as_of: str = ""
    trend_state_changed_at: str = ""
    trend_state_info: Optional[Dict[str, Any]] = None
    fundamental_state: str = "FU"
    fundamental_state_info: Optional[Dict[str, Any]] = None
    holding_health: str = ""                 # HEALTHY / WEAKENING / BROKEN / UNKNOWN
    holding_health_score: float = 0.0
    holding_health_signals: List[str] = field(default_factory=list)
    next_day_guard_break_vwap: bool = False
    next_day_guard_vwap: Optional[float] = None
    next_day_guard_high: Optional[float] = None
    target_price_1: Optional[float] = None
    target_price_2: Optional[float] = None
    profit_protect_price: Optional[float] = None
    profit_protect_level: str = ""
    profit_protect_reason: str = ""

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
            "add_setup": self.add_setup,
            "add_confirmation": self.add_confirmation,
            "add_signal": self.add_signal,
            "add_setup_class": self.add_setup_class,
            "add_size_pct": round(self.add_size_pct, 3),
            "add_reason": self.add_reason,
            "sector_source": self.sector_source,
            "rs_source": self.rs_source,
            "state": self.state,
            "position_state": self.position_state,
            "decay_score": round(self.decay_score, 2),
            "atr_trailing_stop_triggered": self.atr_trailing_stop_triggered,
            "recapture_triggered": self.recapture_triggered,
            "exit_level": self.exit_level,
            "exit_class": self.exit_class,
            "reduce_pct": self.reduce_pct,
            "ma20_confirm_days": self.ma20_confirm_days,
            "highest_close": self.highest_close,
            "trailing_stop_price": self.trailing_stop_price,
            "decay_signals": list(self.decay_signals),
            "reasons": list(self.reasons),
            "high_volume_class": self.high_volume_class,
            "high_volume_reason": self.high_volume_reason,
            "trend_state": self.trend_state,
            "trend_state_reason": self.trend_state_reason,
            "previous_trend_state": self.previous_trend_state,
            "trend_state_streak": self.trend_state_streak,
            "trend_reason_code": self.trend_reason_code,
            "trend_confidence": round(self.trend_confidence, 4),
            "trend_state_as_of": self.trend_state_as_of,
            "trend_state_changed_at": self.trend_state_changed_at,
            "trend_state_info": self.trend_state_info or {},
            "fundamental_state": self.fundamental_state,
            "fundamental_state_info": self.fundamental_state_info or {},
            "holding_health": self.holding_health,
            "holding_health_score": round(self.holding_health_score, 2),
            "holding_health_signals": list(self.holding_health_signals),
            "next_day_guard_break_vwap": self.next_day_guard_break_vwap,
            "next_day_guard_vwap": self.next_day_guard_vwap,
            "next_day_guard_high": self.next_day_guard_high,
            "target_price_1": self.target_price_1,
            "target_price_2": self.target_price_2,
            "profit_protect_price": self.profit_protect_price,
            "profit_protect_level": self.profit_protect_level,
            "profit_protect_reason": self.profit_protect_reason,
        }
