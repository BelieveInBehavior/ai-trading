"""First Board Continue 策略包独立数据结构。

首板后延续（C类机会）：
  - first_board_event: 严格首板（前一交易日未涨停 + 今日涨停）
  - first_board_quality_score: 首板质量
  - first_board_continuation_confirmed: T+1 继续性确认
  - first_board_continuation_score: T+1 延续强度
  - entry_quality_score: 当前买点质量
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol_code": self.symbol_code,
            "symbol_name": self.symbol_name,
            "trade_date": self.trade_date,
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
            "first_board_continuation_score": self.first_board_continuation_score,
            "first_board_quality_score": self.first_board_quality_score,
            "first_board_quality_grade": self.first_board_quality_grade,
            "first_board_continuation_confirmed": self.first_board_continuation_confirmed,
            "first_board_event": self.first_board_event,
            "first_board_continuation_reasons": list(self.first_board_continuation_reasons),
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
