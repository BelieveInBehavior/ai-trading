"""First Board Continue 策略包独立数据结构。

目标：P(MFE[T+1,T+3] >= +3%) 最大化；不再是“大而全的强度评分”。

对齐“候选 = FIRST_BOARD_CONTINUATION，Gate 逐项 PASS 才 BUY”：
  - first_board_quality: 首板质量（Gate）
  - sector_breadth: 板块共振（Gate）
  - upside_room: +3% 上行空间（Gate）
  - market_regime: 市场环境（Gate）
  - T+1 confirmation: 正常承接/确认（Gate）
  - entry_quality: 买点质量（Gate）
  - risk_gate: 风险控制（Gate）
  - BUY <=> gates 全部 PASS（或按 config 容忍部分硬 Gate 缺失）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GateResult:
    """单个 Gate 的结果，替代“一个总分来决定买不买”。"""
    name: str = ""
    passed: bool = False
    score: float = 0.0
    reason: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "score": round(self.score, 2),
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass
class OutcomeMetrics:
    """回测标签：Entry + MFE/MAE/CloseReturn。

    注意：MFE/MAE 必须相对实际买点（entry_price）计算，不能用首板后最高价直接代替。"""
    symbol_code: str = ""
    entry_date: str = ""
    entry_price: Optional[float] = None
    close_t1: Optional[float] = None
    close_t2: Optional[float] = None
    close_t3: Optional[float] = None
    mfe_t1: Optional[float] = None
    mfe_t2: Optional[float] = None
    mfe_t3: Optional[float] = None
    mae_t1: Optional[float] = None
    mae_t2: Optional[float] = None
    mae_t3: Optional[float] = None
    close_return_t1: Optional[float] = None
    close_return_t2: Optional[float] = None
    close_return_t3: Optional[float] = None
    positive_pct: float = 3.0
    target_3: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol_code": self.symbol_code,
            "entry_date": self.entry_date,
            "entry_price": self.entry_price,
            "futures_t1_close": self.close_t1,
            "futures_t2_close": self.close_t2,
            "futures_t3_close": self.close_t3,
            "MFE_T1": _round_opt(self.mfe_t1),
            "MFE_T2": _round_opt(self.mfe_t2),
            "MFE_T3": _round_opt(self.mfe_t3),
            "MAE_T1": _round_opt(self.mae_t1),
            "MAE_T2": _round_opt(self.mae_t2),
            "MAE_T3": _round_opt(self.mae_t3),
            "CloseReturn_T1": _round_opt(self.close_return_t1),
            "CloseReturn_T2": _round_opt(self.close_return_t2),
            "CloseReturn_T3": _round_opt(self.close_return_t3),
            "target_pct": self.positive_pct,
            "Target_3": self.target_3,
        }


def _round_opt(value: Optional[float]) -> Optional[float]:
    try:
        return None if value is None else round(float(value), 4)
    except (TypeError, ValueError):
        return None


@dataclass
class FirstBoardCandidate:
    symbol_code: str
    symbol_name: str
    trade_date: str
    first_board_event: bool = False
    first_board_date: str = ""
    first_board_close: Optional[float] = None
    first_board_quality_score: float = 0.0
    first_board_quality_grade: str = ""
    first_board_quality_reasons: List[str] = field(default_factory=list)
    first_board_continuation_confirmed: bool = False
    first_board_continuation_gate_detail: Dict[str, Any] = field(default_factory=dict)
    first_board_continuation_score: float = 0.0
    first_board_continuation_reasons: List[str] = field(default_factory=list)
    entry_quality_score: float = 0.0
    buy_ready: bool = False
    factor: Dict[str, Any] = field(default_factory=dict)
    technical_factor: Dict[str, Any] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)

    candidate_type: str = "FIRST_BOARD_CONTINUATION"
    gates: Dict[str, Any] = field(default_factory=dict)
    sector_breadth_score: float = 0.0
    sector_breadth_passed: bool = False
    sector_breadth_reason: str = ""
    upside_room_score: float = 0.0
    upside_room_passed: bool = False
    upside_room_reason: str = ""
    market_regime_score: float = 0.0
    market_regime_passed: bool = False
    market_regime_reason: str = ""
    risk_gate_passed: bool = False
    risk_gate_reason: str = ""
    entry_quality_passed: bool = False
    first_failed_gate: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol_code": self.symbol_code,
            "symbol_name": self.symbol_name,
            "trade_date": self.trade_date,
            "candidate": self.candidate_type,
            "first_board_event": self.first_board_event,
            "first_board_date": self.first_board_date,
            "first_board_close": self.first_board_close,
            "first_board_quality_score": self.first_board_quality_score,
            "first_board_quality_grade": self.first_board_quality_grade,
            "first_board_quality_reasons": list(self.first_board_quality_reasons),
            "first_board_continuation_confirmed": self.first_board_continuation_confirmed,
            "first_board_continuation_gate_detail": self.first_board_continuation_gate_detail,
            "first_board_continuation_score": self.first_board_continuation_score,
            "first_board_continuation_reasons": list(self.first_board_continuation_reasons),
            "entry_quality_score": self.entry_quality_score,
            "entry_quality_passed": self.entry_quality_passed,
            "sector_breadth_score": self.sector_breadth_score,
            "sector_breadth_passed": self.sector_breadth_passed,
            "sector_breadth_reason": self.sector_breadth_reason,
            "upside_room_score": self.upside_room_score,
            "upside_room_passed": self.upside_room_passed,
            "upside_room_reason": self.upside_room_reason,
            "market_regime_score": self.market_regime_score,
            "market_regime_passed": self.market_regime_passed,
            "market_regime_reason": self.market_regime_reason,
            "risk_gate_passed": self.risk_gate_passed,
            "risk_gate_reason": self.risk_gate_reason,
            "first_failed_gate": self.first_failed_gate,
            "gates": self.gates,
            "buy_ready": self.buy_ready,
            "factor": self.factor,
            "technical_factor": self.technical_factor,
            "reasons": list(self.reasons),
        }


@dataclass
class FirstBoardDiscovery:
    trade_date: str = ""
    candidates: List[FirstBoardCandidate] = field(default_factory=list)
    universe_count: int = 0
    context_string: str = ""
    market_temperature: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WatchlistItem:
    symbol_code: str
    symbol_name: str
    trade_date: str
    factors: List[Dict[str, Any]] = field(default_factory=list)
    first_board_event: bool = False
    first_board_date: str = ""
    first_board_close: Optional[float] = None
    first_board_quality_score: float = 0.0
    first_board_quality_grade: str = ""
    first_board_quality_reasons: List[str] = field(default_factory=list)
    first_board_continuation_confirmed: bool = False
    first_board_continuation_gate_detail: Dict[str, Any] = field(default_factory=dict)
    first_board_continuation_score: float = 0.0
    first_board_continuation_reasons: List[str] = field(default_factory=list)
    entry_quality_score: float = 0.0
    buy_ready: bool = False
    state: str = "观察中"

    candidate: str = "FIRST_BOARD_CONTINUATION"
    gates: Dict[str, Any] = field(default_factory=dict)
    sector_breadth_score: float = 0.0
    sector_breadth_passed: bool = False
    sector_breadth_reason: str = ""
    upside_room_score: float = 0.0
    upside_room_passed: bool = False
    upside_room_reason: str = ""
    market_regime_score: float = 0.0
    market_regime_passed: bool = False
    market_regime_reason: str = ""
    risk_gate_passed: bool = False
    risk_gate_reason: str = ""
    entry_quality_passed: bool = False
    first_failed_gate: str = ""

    def latest_factor(self) -> Dict[str, Any]:
        return self.factors[-1] if self.factors else {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol_code": self.symbol_code,
            "symbol_name": self.symbol_name,
            "trade_date": self.trade_date,
            "state": self.state,
            "factor_count": len(self.factors),
            "latest_factor": self.latest_factor(),
            "candidate": self.candidate,
            "first_board_event": self.first_board_event,
            "first_board_date": self.first_board_date,
            "first_board_close": self.first_board_close,
            "first_board_quality_score": self.first_board_quality_score,
            "first_board_quality_grade": self.first_board_quality_grade,
            "first_board_quality_reasons": list(self.first_board_quality_reasons),
            "first_board_continuation_confirmed": self.first_board_continuation_confirmed,
            "first_board_continuation_gate_detail": self.first_board_continuation_gate_detail,
            "first_board_continuation_score": self.first_board_continuation_score,
            "first_board_continuation_reasons": list(self.first_board_continuation_reasons),
            "entry_quality_score": self.entry_quality_score,
            "entry_quality_passed": self.entry_quality_passed,
            "sector_breadth_score": self.sector_breadth_score,
            "sector_breadth_passed": self.sector_breadth_passed,
            "sector_breadth_reason": self.sector_breadth_reason,
            "upside_room_score": self.upside_room_score,
            "upside_room_passed": self.upside_room_passed,
            "upside_room_reason": self.upside_room_reason,
            "market_regime_score": self.market_regime_score,
            "market_regime_passed": self.market_regime_passed,
            "market_regime_reason": self.market_regime_reason,
            "risk_gate_passed": self.risk_gate_passed,
            "risk_gate_reason": self.risk_gate_reason,
            "first_failed_gate": self.first_failed_gate,
            "gates": self.gates,
            "buy_ready": self.buy_ready,
        }


@dataclass
class BuySignal:
    symbol_code: str
    symbol_name: str
    trade_date: str
    lifecycle_state: str = "首板延续观察"
    pool_type: str = "首板"
    divergence_mode: str = "first_board"
    divergence_score: float = 0.0
    entry_quality_score: float = 0.0
    weak_to_strong_score: float = 0.0
    first_board_continuation_score: float = 0.0
    first_board_quality_score: float = 0.0
    first_board_quality_grade: str = ""
    first_board_continuation_confirmed: bool = False
    first_board_event: bool = False
    first_board_continuation_reasons: List[str] = field(default_factory=list)
    t1_buy_score: float = 0.0
    buy_ready: bool = False
    reasons: List[str] = field(default_factory=list)

    candidate: str = "FIRST_BOARD_CONTINUATION"
    gates: Dict[str, Any] = field(default_factory=dict)
    sector_breadth_passed: bool = False
    upside_room_passed: bool = False
    market_regime_passed: bool = False
    risk_gate_passed: bool = False
    entry_quality_passed: bool = False
    first_failed_gate: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol_code": self.symbol_code,
            "symbol_name": self.symbol_name,
            "trade_date": self.trade_date,
            "lifecycle_state": self.lifecycle_state,
            "pool_type": self.pool_type,
            "divergence_mode": self.divergence_mode,
            "divergence_score": self.divergence_score,
            "candidate": self.candidate,
            "entry_quality_score": self.entry_quality_score,
            "entry_quality_passed": self.entry_quality_passed,
            "weak_to_strong_score": self.weak_to_strong_score,
            "first_board_continuation_score": self.first_board_continuation_score,
            "first_board_quality_score": self.first_board_quality_score,
            "first_board_quality_grade": self.first_board_quality_grade,
            "first_board_continuation_confirmed": self.first_board_continuation_confirmed,
            "first_board_event": self.first_board_event,
            "first_board_continuation_reasons": list(self.first_board_continuation_reasons),
            "gates": self.gates,
            "sector_breadth_passed": self.sector_breadth_passed,
            "sector_breadth_passed_gate": self.sector_breadth_passed,
            "upside_room_passed": self.upside_room_passed,
            "market_regime_passed": self.market_regime_passed,
            "risk_gate_passed": self.risk_gate_passed,
            "first_failed_gate": self.first_failed_gate,
            "t1_buy_score": self.t1_buy_score,
            "buy_ready": self.buy_ready,
            "reasons": list(self.reasons),
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
    signal_tier: str = "C"
    candidate: str = "FIRST_BOARD_CONTINUATION"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol_code": self.symbol_code,
            "symbol_name": self.symbol_name,
            "entry_date": self.entry_date,
            "entry_price": self.entry_price,
            "quantity": self.quantity,
            "holding_days": self.holding_days,
            "highest_price": self.highest_price,
            "current_price": self.current_price,
            "buy_score": self.buy_score,
            "signal_tier": self.signal_tier,
            "candidate": self.candidate,
        }


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol_code": self.symbol_code,
            "symbol_name": self.symbol_name,
            "action": self.action,
            "reason": self.reason,
            "urgency": self.urgency,
            "exit_score": self.exit_score,
            "current_return_pct": self.current_return_pct,
            "stop_loss_triggered": self.stop_loss_triggered,
            "take_profit_triggered": self.take_profit_triggered,
        }
