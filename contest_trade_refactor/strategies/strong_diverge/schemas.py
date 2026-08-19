"""Strong Diverge 策略包独立数据结构（不依赖旧 agents/signal_schema）。

核心设计：
- 强势股发现阶段按“连板型 / 突破型 / 趋势启动型”分流，各自评分；
- 进入观察池的分数称为 strength_watch_score（谁值得等分歧），
  而不是 buy_score（谁现在可买）；
- setup_score 表示分歧/弱转强潜力，在观察池进一步评估；
- 生命周期是“状态机 + 评分”：必须先发生真正的 divergence_event，
  再通过 weak_to_strong 硬条件 Gate，最后才看 entry_quality 是否值得买。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StrongStockCandidate:
    """强势股票发现池候选（可进入观察池）"""
    symbol_code: str
    symbol_name: str
    trade_date: str
    pool_type: str = "连板"                # 连板 / 突破 / 趋势启动 / 观察
    strong_tags: List[str] = field(default_factory=list)
    strength_watch_score: float = 0.0      # 进入观察池资格分
    setup_score: float = 0.0               # 分歧/弱转强准备度（观察期用）
    strong_structure: Dict[str, Any] = field(default_factory=dict)  # 连板/突破/趋势行为明细
    limit_snapshot: Dict[str, Any] = field(default_factory=dict)     # 涨停封单快照
    technical_factor: Dict[str, Any] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol_code": self.symbol_code,
            "symbol_name": self.symbol_name,
            "trade_date": self.trade_date,
            "pool_type": self.pool_type,
            "strong_tags": list(self.strong_tags),
            "strength_watch_score": self.strength_watch_score,
            "setup_score": self.setup_score,
            "strong_structure": self.strong_structure,
            "limit_snapshot": self.limit_snapshot,
            "technical_factor": self.technical_factor,
            "reasons": list(self.reasons),
        }


@dataclass
class DiscoveryPool:
    """发现阶段输出：三类候选池 + 合并图层。"""
    trade_date: str = ""
    lianban: List[StrongStockCandidate] = field(default_factory=list)
    tupo: List[StrongStockCandidate] = field(default_factory=list)
    qushi: List[StrongStockCandidate] = field(default_factory=list)
    all_candidates: List[StrongStockCandidate] = field(default_factory=list)
    universe_count: int = 0
    context_string: str = ""
    scan_errors: List[str] = field(default_factory=list)
    market_temperature: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "lian": [c.to_dict() for c in self.lianban],
            "tupo": [c.to_dict() for c in self.tupo],
            "qushi": [c.to_dict() for c in self.qushi],
            "universe_count": self.universe_count,
            "context_string": self.context_string,
            "scan_errors": self.scan_errors,
            "market_temperature": self.market_temperature,
        }


@dataclass
class DiscoveryResult:
    """兼容旧 discover() 返回结构的包装。"""
    trade_date: str
    candidates: List[StrongStockCandidate]
    pool: Any | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "candidates": [c.to_dict() for c in self.candidates],
        }


@dataclass
class WatchlistQuota:
    """观察池分层配额。"""
    pool_type: str = "连板"
    max_count: int = 20
    min_strength_watch_score: float = 50.0
    max_per_concept: int = 3


@dataclass
class WatchlistItem:
    """强势观察池记录。

    状态机字段用于跨日跟踪“强势 -> 真正分歧 -> 确认 -> 再确认”：
      - strong_phase_enter_date: 进入强势生命周期日期
      - consecutive_board_count: 进入观察池时的连板数 / 强势阶段连板数
      - last_board_date / price / close: 上一次涨停日信息
      - first_non_board_date: 强势阶段第一次“不涨停”日期
      - first_negative_date: 强势阶段第一次收阴日期（首阴）
      - divergence_event: 只有满足“强势中 + 首次不涨停/首次收阴”时才为 True
      - divergence_quality: 该次分歧的质量评分 / 等级
      - weak_to_strong_confirmed: 是否通过 weak-to-strong 硬条件
      - weak_to_strong_gate_detail: 5 个硬条件明细
    """
    symbol_code: str
    symbol_name: str
    trade_date: str
    pool_type: str = "连板"
    strong_tags: List[str] = field(default_factory=list)
    strength_watch_score: float = 0.0
    setup_score: float = 0.0
    strong_structure: Dict[str, Any] = field(default_factory=dict)
    limit_snapshot: Dict[str, Any] = field(default_factory=dict)
    factors: List[Dict[str, Any]] = field(default_factory=list)
    # 状态机字段：用于跨日跟踪 "强势 -> 分歧 -> 确认 -> 再确认"
    # state: 强势观察池 / 首次分歧 / 确认观察 / T+1买入候选 / 分歧失败 / 已确认 / 已过期
    state: str = "强势观察池"
    divergence_dates: List[str] = field(default_factory=list)   # 出现过分歧的日期
    confirmation_dates: List[str] = field(default_factory=list)  # 确认转强日期
    state_reasons: List[str] = field(default_factory=list)
    last_reasons: List[str] = field(default_factory=list)

    # 生命周期元数据 / 严格分歧定义
    strong_phase_enter_date: str = ""
    consecutive_board_count: int = 0
    last_board_date: str = ""
    last_board_price: Optional[float] = None
    last_board_close: Optional[float] = None
    first_non_board_date: str = ""
    first_negative_date: str = ""
    divergence_event: bool = False
    divergence_mode: str = "none"          # 首阴 / 断板 / none
    divergence_class: str = ""              # 健康分歧 / 中性分歧 / 弱分歧 / none
    divergence_grade: str = ""               # 分歧质量等级 A类健康 / B类中性 / C类弱
    divergence_quality_score: float = 0.0
    divergence_quality_reasons: List[str] = field(default_factory=list)
    # weak-to-strong 硬条件
    weak_to_strong_confirmed: bool = False
    weak_to_strong_gate_detail: Dict[str, Any] = field(default_factory=dict)
    weak_to_strong_reasons: List[str] = field(default_factory=list)

    def latest_factor(self) -> Dict[str, Any]:
        return self.factors[-1] if self.factors else {}

    @property
    def first_negative_after_strength(self) -> str:
        """Backward-compatible alias for first_negative_date."""
        return self.first_negative_date

    @first_negative_after_strength.setter
    def first_negative_after_strength(self, value: str) -> None:
        self.first_negative_date = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol_code": self.symbol_code,
            "symbol_name": self.symbol_name,
            "trade_date": self.trade_date,
            "pool_type": self.pool_type,
            "strong_tags": list(self.strong_tags),
            "strength_watch_score": self.strength_watch_score,
            "setup_score": self.setup_score,
            "strong_structure": self.strong_structure,
            "limit_snapshot": self.limit_snapshot,
            "factor_count": len(self.factors),
            "latest_factor": self.latest_factor(),
            "state": self.state,
            "divergence_dates": list(self.divergence_dates),
            "confirmation_dates": list(self.confirmation_dates),
            "state_reasons": list(self.state_reasons),
            "last_reasons": list(self.last_reasons),
            "strong_phase_enter_date": self.strong_phase_enter_date,
            "consecutive_board_count": self.consecutive_board_count,
            "last_board_date": self.last_board_date,
            "last_board_price": self.last_board_price,
            "last_board_close": self.last_board_close,
            "first_non_board_date": self.first_non_board_date,
            "first_negative_date": self.first_negative_date,
            "divergence_event": self.divergence_event,
            "divergence_mode": self.divergence_mode,
            "divergence_class": self.divergence_class,
            "divergence_grade": self.divergence_grade,
            "divergence_quality_score": self.divergence_quality_score,
            "divergence_quality_reasons": list(self.divergence_quality_reasons),
            "weak_to_strong_confirmed": self.weak_to_strong_confirmed,
            "weak_to_strong_gate_detail": self.weak_to_strong_gate_detail,
            "weak_to_strong_reasons": list(self.weak_to_strong_reasons),
        }


@dataclass
class DivergenceSignal:
    """等待分歧后的首阴 / 断板信号（新增 divergence_event 语义）。

    divergence_event 与“今天是不是跌/不涨停”分离：
      - factor 记录今天涨跌
      - 只有满足生命周期阶段（强势 -> 首次断板/首次阴线）才产生 Event
    """
    symbol_code: str
    symbol_name: str
    trade_date: str
    pool_type: str = "连板"
    divergence_mode: str = "none"      # 首阴 / 断板 / none
    divergence_score: float = 0.0      # 兼容旧字段，等于 divergence_quality_score
    divergence_pass: bool = False
    divergence_reasons: List[str] = field(default_factory=list)
    strength_watch_score: float = 0.0
    setup_score: float = 0.0
    factor: Dict[str, Any] = field(default_factory=dict)
    # 新字段
    divergence_event: bool = False
    divergence_class: str = ""
    divergence_grade: str = ""
    consecutive_board_count: int = 0
    first_non_board: bool = False
    first_negative_date: bool = False
    divergence_quality_score: float = 0.0
    divergence_quality_reasons: List[str] = field(default_factory=list)

    @property
    def first_negative_after_strength(self) -> bool:
        return self.first_negative_date

    @first_negative_after_strength.setter
    def first_negative_after_strength(self, value: bool) -> None:
        self.first_negative_date = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol_code": self.symbol_code,
            "symbol_name": self.symbol_name,
            "trade_date": self.trade_date,
            "pool_type": self.pool_type,
            "divergence_mode": self.divergence_mode,
            "divergence_score": self.divergence_score,
            "divergence_pass": self.divergence_pass,
            "divergence_reasons": list(self.divergence_reasons),
            "strength_watch_score": self.strength_watch_score,
            "setup_score": self.setup_score,
            "factor": self.factor,
            "divergence_event": self.divergence_event,
            "divergence_class": self.divergence_class,
            "divergence_grade": self.divergence_grade,
            "consecutive_board_count": self.consecutive_board_count,
            "first_non_board": self.first_non_board,
            "first_negative_date": self.first_negative_date,
            "divergence_quality_score": self.divergence_quality_score,
            "divergence_quality_reasons": list(self.divergence_quality_reasons),
        }


@dataclass
class BuySignal:
    """T+1 买入判断候选。"""
    symbol_code: str
    symbol_name: str
    trade_date: str
    lifecycle_state: str = "观察池"
    pool_type: str = "连板"
    divergence_mode: str = "none"
    divergence_score: float = 0.0
    entry_quality_score: float = 0.0
    weak_to_strong_score: float = 0.0
    t1_buy_score: float = 0.0
    buy_ready: bool = False
    reasons: List[str] = field(default_factory=list)
    suggested_position_size_pct: float = 0.0
    stop_loss_pct: float = -6.0
    take_profit_pct: float = 6.0
    # gate / 职责分离新字段
    divergence_event: bool = False
    divergence_class: str = ""
    divergence_grade: str = ""
    divergence_quality_reasons: List[str] = field(default_factory=list)
    weak_to_strong_confirmed: bool = False
    weak_to_strong_gate_detail: Dict[str, Any] = field(default_factory=dict)
    weak_to_strong_reasons: List[str] = field(default_factory=list)
    entry_quality_reasons: List[str] = field(default_factory=list)

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
            "t1_buy_score": self.t1_buy_score,
            "buy_ready": self.buy_ready,
            "reasons": list(self.reasons),
            "suggested_position_size_pct": self.suggested_position_size_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "divergence_event": self.divergence_event,
            "divergence_class": self.divergence_class,
            "divergence_grade": self.divergence_grade,
            "divergence_quality_reasons": list(self.divergence_quality_reasons),
            "weak_to_strong_confirmed": self.weak_to_strong_confirmed,
            "weak_to_strong_gate_detail": self.weak_to_strong_gate_detail,
            "weak_to_strong_reasons": list(self.weak_to_strong_reasons),
            "entry_quality_reasons": list(self.entry_quality_reasons),
        }


@dataclass
class Holding:
    """T+1 买入后的持仓。"""
    symbol_code: str
    symbol_name: str
    entry_date: str
    entry_price: float
    quantity: int = 0
    holding_days: int = 0
    highest_price: float = 0.0
    current_price: Optional[float] = None
    buy_score: float = 0.0
    divergence_mode: str = ""
    signal_tier: str = "B"
    trade_plan: Dict[str, Any] = field(default_factory=dict)
    stop_loss_price: Optional[float] = None

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
            "divergence_mode": self.divergence_mode,
            "signal_tier": self.signal_tier,
            "trade_plan": self.trade_plan,
            "stop_loss_price": self.stop_loss_price,
        }


@dataclass
class WatchlistPool:
    """分层观察池：连板 / 突破 / 趋势各配比。"""
    lian: List[WatchlistItem] = field(default_factory=list)
    tupo: List[WatchlistItem] = field(default_factory=list)
    qushi: List[WatchlistItem] = field(default_factory=list)
    all_items: List[WatchlistItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lian": [w.to_dict() for w in self.lian],
            'tupo': [w.to_dict() for w in self.tupo],
            'qushi': [w.to_dict() for w in self.qushi],
            'all_items': [w.to_dict() for w in self.all_items],
        }


@dataclass
class ExitDecision:
    """持仓管理决策：T+1~T+3 期间可输出 hold / reduce / sell。"""
    symbol_code: str
    symbol_name: str
    action: str = "hold"          # hold / reduce / sell
    reason: str = ""
    urgency: str = "normal"
    exit_score: float = 0.0
    current_return_pct: float = 0.0
    stop_loss_triggered: bool = False
    take_profit_triggered: bool = False
    reduce_triggered: bool = False
    reasons: List[str] = field(default_factory=list)

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
            "reduce_triggered": self.reduce_triggered,
            "reasons": list(self.reasons),
        }
