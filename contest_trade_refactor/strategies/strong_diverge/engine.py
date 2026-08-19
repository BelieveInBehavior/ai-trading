"""Strong Diverge 强势分歧龙头战法 - 独立策略引擎（v3）。

v3 从“单日评分”升级为“状态机 + 评分”：
  - 严格定义首次断板 / 首阴（first_non_board / first_negative_date）
  - divergence_event 与 divergence_quality 分离
  - weak_to_strong 必须有硬条件 Gate 确认，而不是加权分可直接买入
  - 四个模块各自职责独立（strength / divergence / weak_to_strong / entry_quality）

第一版更强调“单一 strong score 排序”。本版改为：

  全市场
    -> 过滤
    -> 260日K线
    -> 强势行为计算
    -> 连板型 / 突破型 / 趋势启动型 三池分流
    -> 各自 strength_watch_score 评分
    -> 分层 Top K + 简单板块去重
    -> 强势观察池

后续阶段（v3 改为状态机 + Gate）：
  - 严格首阴 / 断板：只有强势生命周期内第一次不涨停 / 第一次收阴才产生 divergence_event
  - divergence_event 与 divergence_quality 分离；断板按 A/B/C 分级（健康/中性/弱）
  - weak_to_strong Gate：5 条件 ≥4 才允许进入 T+1 候选
  - entry_quality_score：只判断该价格值不值得买
  - T+1~T+3 管理卖出
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from data_source.technical_indicators_akshare import compute_stock_technical_factor_from_history
from utils.akshare_utils import akshare_cached
from utils.cn_price_provider import get_index_daily, get_stock_zh_a_hist
from utils.date_utils import get_latest_completed_trading_date, get_trading_date_range
from utils.factor_store import ZT_SEAL_STORE
from utils.market_manager import GLOBAL_MARKET_MANAGER

from strategies.strong_diverge.schemas import (
    BuySignal,
    DiscoveryPool,
    DivergenceSignal,
    ExitDecision,
    Holding,
    StrongStockCandidate,
    WatchlistItem,
    WatchlistPool,
)

try:
    _BASE_DIR = Path(__file__).resolve().parent
except Exception:
    _BASE_DIR = Path("strategies/strong_diverge")


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.strip().replace("%", "")
        result = float(value)
        if result != result:
            return default
        return result
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.strip()
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "是", "有", "ok", "passed"}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _normalize_code(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) < 6:
        return ""
    code = digits[-6:]
    suffix = ".SH" if code.startswith("6") else ".SZ"
    return f"{code}{suffix}"


def _reasons(items) -> List[str]:
    return [str(item).strip() for item in items or [] if str(item).strip()]


def _is_limit_pct(symbol_code: str, change_pct: Optional[float]) -> bool:
    """A股板块阈值判断：主板~10%，创业板/科创板~20%。"""
    if change_pct is None:
        return False
    code = "".join(ch for ch in str(symbol_code or "") if ch.isdigit())
    if code.startswith(("300", "301", "688", "689")):
        return bool(change_pct >= 19.0)
    return bool(change_pct >= 9.0)

def _max_duanban_up(symbol_code: str, default: float = 8.0) -> float:
    """断板当日最大正涨幅阈值；创业板/科创板放宽为约 16% 以便识别 20cm 断板。"""
    code = "".join(ch for ch in str(symbol_code or "") if ch.isdigit())
    if code.startswith(("300", "301", "688", "689")):
        return 16.0
    return float(default)


def _is_limit_up_change(symbol_code: str, change_pct: Optional[float]) -> bool:
    return _is_limit_pct(symbol_code, change_pct)


def _concept_key(cand) -> str:
    """简单概念去重 key：优先看 technical_factor 里的行业/概念，否则按 pool_type+首字母分组。"""
    factor = cand.technical_factor or {}
    sector = str(factor.get("sector_name") or factor.get("industry_name") or "").strip()
    if sector:
        return sector
    # 暂无概念映射时，用一个代码段近似（前 3 位），避免同板块过密
    return cand.symbol_code[:3]


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
@dataclass
class StrongDivergeConfig:
    id: str = "strong_diverge"
    discovery: Dict[str, Any] = field(default_factory=dict)
    watchlist: Dict[str, Any] = field(default_factory=dict)
    divergence: Dict[str, Any] = field(default_factory=dict)
    confirmation: Dict[str, Any] = field(default_factory=dict)
    t1_buy: Dict[str, Any] = field(default_factory=dict)
    holding: Dict[str, Any] = field(default_factory=dict)
    market: Dict[str, Any] = field(default_factory=dict)
    backtest: Dict[str, Any] = field(default_factory=dict)
    quantitative_concurrency: int = 4
    benchmark_symbol: str = "sh000300"

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "StrongDivergeConfig":
        return cls(
            id=str(cfg.get("id") or "strong_diverge"),
            discovery=dict(cfg.get("discovery") or {}),
            watchlist=dict(cfg.get("watchlist") or {}),
            divergence=dict(cfg.get("divergence") or {}),
            confirmation=dict(cfg.get("confirmation") or {}),
            t1_buy=dict(cfg.get("t1_buy") or {}),
            holding=dict(cfg.get("holding") or {}),
            market=dict(cfg.get("market") or {}),
            backtest=dict(cfg.get("backtest") or {}),
            quantitative_concurrency=int(cfg.get("quantitative_screen_concurrency", 4) or 4),
            benchmark_symbol=str(cfg.get("benchmark_symbol") or cfg.get("benchmark") or "sh000300"),
        )

    @classmethod
    def from_yaml(cls) -> "StrongDivergeConfig":
        import yaml
        with open(_BASE_DIR / "strategy.yaml", "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------
class StrongDivergeEngine:
    def __init__(self, config: StrongDivergeConfig | None = None):
        self.config = config or StrongDivergeConfig.from_yaml()

    # ================= 主入口 =================
    async def run_day(
        self,
        trigger_time: str,
        watchlist: Optional[List[WatchlistItem]] = None,
        holdings: Optional[List[Holding]] = None,
        output_dir: Optional[str] = None,
        max_symbols: int = 0,
    ) -> Dict[str, Any]:
        trade_date = get_latest_completed_trading_date(trigger_time)
        discovery = await self.discover(trigger_time, max_symbols=max_symbols)
        watch_pool = self.merge_watchlist(
            discovery, prev_watchlist=watchlist, trade_date=trade_date
        )
        divergences = self.detect_divergence(watch_pool, trade_date)
        self.advance_lifecycle_states(watch_pool, trade_date)
        # 状态机 + 评分：真正把 “强势->分歧->确认->再确认” 作为候选条件。
        # confirm_buy 仍基于单日评分，仅作兼容；state_signals 是新链路用于 T+1。
        state_signals_raw = self.apply_state_machine(watch_pool, trade_date)
        state_signals = self._build_buy_signals_from_state(state_signals_raw, trade_date)
        clarified = [s for s in state_signals if s.buy_ready]  # only state-validated ready
        buy_signals = self.build_t1_buy_plan(clarified)
        confirmed = buy_signals
        exits = self.evaluate_exits(holdings or [])
        result = {
            "trade_date": trade_date,
            "trigger_time": trigger_time,
            "discovery": discovery,
            "watchlist": watch_pool,
            "divergence_signals": divergences,
            "confirmed_signals": confirmed,
            "buy_signals": buy_signals,
            "state_signals": state_signals,
            "exit_decisions": exits,
        }
        if output_dir:
            self._write_result(result, output_dir)
        return result

    # ================= 1. 强势股票发现池（三类型分流） =================
    async def discover(
        self,
        trigger_time: str,
        max_symbols: int = 0,
    ) -> DiscoveryPool:
        trade_date = get_latest_completed_trading_date(trigger_time)
        start_date, end_date = get_trading_date_range(
            end_date=trade_date, count=260, include_end=True
        )
        universe = await asyncio.to_thread(self._load_universe, max_symbols)
        benchmark = await asyncio.to_thread(
            self._load_benchmark, self.config.benchmark_symbol, start_date, end_date
        )
        zt_snapshot = self._safe_zt_snapshot(trade_date)
        mrkt_temp = self._market_temperature(trade_date)

        sem = asyncio.Semaphore(max(1, int(self.config.quantitative_concurrency) or 4))
        candidates: List[StrongStockCandidate] = []
        errors: List[str] = []

        async def _score(row: Dict[str, Any]) -> None:
            async with sem:
                try:
                    cand = await asyncio.to_thread(
                        self._discover_one,
                        row,
                        start_date,
                        end_date,
                        trade_date,
                        benchmark,
                        zt_snapshot,
                    )
                    if cand:
                        candidates.append(cand)
                except Exception as exc:
                    errors.append(str(exc))

        total = len(universe)
        market_enabled = _bool((self.config.market or {}).get("enabled", True))
        if market_enabled and not mrkt_temp.get("passed", True):
            # 退潮期前置闸门：全市场直通空仓，不进 strength_watch，避免补涨末段。
            context = (
                "市场情绪温度计：温度=" + str(mrkt_temp.get('temperature', 0))
                + "，退潮期闸门不过，不进入强势发现；"
                + "；".join(mrkt_temp.get("reasons") or [])
            )
            return DiscoveryPool(
                trade_date=trade_date,
                lianban=[],
                tupo=[],
                qushi=[],
                all_candidates=[],
                universe_count=total,
                context_string=context,
                scan_errors=errors,
                market_temperature=dict(mrkt_temp),
            )
        batch_size = max(1, int(self.config.quantitative_concurrency) * 30)
        for offset in range(0, total, batch_size):
            batch = universe[offset: offset + batch_size]
            await asyncio.gather(*[_score(row) for row in batch])

        # 分池
        lianban = [c for c in candidates if c.pool_type == "连板"]
        tupo = [c for c in candidates if c.pool_type == "突破"]
        qushi = [c for c in candidates if c.pool_type == "趋势启动"]

        # 各自排序
        lianban.sort(key=lambda c: c.strength_watch_score, reverse=True)
        tupo.sort(key=lambda c: c.strength_watch_score, reverse=True)
        qushi.sort(key=lambda c: c.strength_watch_score, reverse=True)

        # 分层 Top K + 简单板块去重
        top_lian = self._top_n_dedup(lianban, "连板")
        top_tupo = self._top_n_dedup(tupo, "突破")
        top_qushi = self._top_n_dedup(qushi, "趋势")

        all_candidates = top_lian + top_tupo + top_qushi
        context = self._discovery_context(top_lian, top_tupo, top_qushi, total)
        return DiscoveryPool(
            trade_date=trade_date,
            lianban=top_lian,
            tupo=top_tupo,
            qushi=top_qushi,
            all_candidates=all_candidates,
            universe_count=total,
            context_string=context,
            scan_errors=errors,
            market_temperature=dict(mrkt_temp),
        )

    def _top_n_dedup(
        self,
        candidates: List[StrongStockCandidate],
        pool_type: str,
        max_hard: Optional[int] = None,
    ) -> List[StrongStockCandidate]:
        cfg = self.config.watchlist or {}
        max_default = {
            "连板": int(cfg.get("max_lianban", 20) or 20),
            "突破": int(cfg.get("max_tupo", 15) or 15),
            "趋势": int(cfg.get("max_qushi", 10) or 10),
        }.get(pool_type, 10)
        max_count = int(max_hard if max_hard is not None else max_default)
        max_per_concept = int(cfg.get("max_per_concept", 3) or 3)

        out: List[StrongStockCandidate] = []
        concept_counts: Dict[str, int] = {}
        for cand in sorted(candidates, key=lambda c: c.strength_watch_score, reverse=True):
            if len(out) >= max_count:
                break
            key = _concept_key(cand)
            if concept_counts.get(key, 0) >= max_per_concept:
                continue
            concept_counts[key] = concept_counts.get(key, 0) + 1
            out.append(cand)
        return out

    def _discover_one(
        self,
        row: Dict[str, Any],
        start_date: str,
        end_date: str,
        trade_date: str,
        benchmark: pd.DataFrame,
        zt_snapshot: Dict[str, Dict[str, Any]],
    ) -> StrongStockCandidate | None:
        code = str(row.get("symbol_code") or "").strip()
        hist = get_stock_zh_a_hist(
            symbol=code[:6],
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
            verbose=False,
        )
        factor = compute_stock_technical_factor_from_history(
            hist_df=hist,
            symbol_code=code,
            symbol_name=str(row.get("symbol_name") or code[:6]),
            trade_date=trade_date,
            relative_strength_benchmark=self.config.benchmark_symbol,
            benchmark_frame=benchmark,
        )
        if not factor:
            return None
        return self._classify_candidate(factor, zt_snapshot)

    def _load_universe(self, max_symbols: int = 0) -> list:
        try:
            raw = akshare_cached.run("stock_zh_a_spot_em", {}, False)
        except Exception:
            raw = akshare_cached.run("stock_info_a_code_name", {}, False)
        if raw is None or raw.empty:
            return []
        code_col = next((c for c in ("代码", "code", "ts_code") if c in raw.columns), None)
        name_col = next((c for c in ("名称", "name") if c in raw.columns), None)
        amount_col = next((c for c in ("成交额", "amount") if c in raw.columns), None)
        if not code_col:
            return []
        rows: list[Dict[str, Any]] = []
        for _, row in raw.iterrows():
            code = _normalize_code(row.get(code_col))
            if not code:
                continue
            name = str(row.get(name_col) if name_col else row.get(code_col)).strip()
            if not name or name.upper().find("ST") >= 0 or "退" in name:
                continue
            if code.startswith(("4", "8", "920")):
                continue
            rec = {"symbol_code": code, "symbol_name": name}
            rec["amount"] = 0.0
            if amount_col:
                try:
                    rec["amount"] = float(row.get(amount_col) or 0.0)
                except Exception:
                    pass
            rows.append(rec)
        if max_symbols and max_symbols > 0:
            rows.sort(key=lambda r: r.get("amount", 0.0), reverse=True)
            rows = rows[:max_symbols]
        return rows

    def _load_benchmark(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        try:
            raw = get_index_daily(symbol, start, end, False)
            from data_source.technical_indicators_akshare import _prepare_price_frame
            return _prepare_price_frame(raw, date_columns=("date",), close_columns=("close",))
        except Exception:
            return pd.DataFrame()

    def _safe_zt_snapshot(self, trade_date: str) -> Dict[str, Dict[str, Any]]:
        if not trade_date:
            return {}
        try:
            df = ZT_SEAL_STORE.load(trade_date)
        except Exception:
            return {}
        if df is None or df.empty:
            return {}
        snapshot: Dict[str, Dict[str, Any]] = {}
        for _, row in df.iterrows():
            code = _normalize_code(row.get("symbol_code"))
            if not code:
                continue
            meta: Dict[str, Any] = {}
            try:
                meta = json.loads(row.get("metadata_json") or "{}")
            except Exception:
                meta = {}
            factor_value = _num(row.get("factor_value"), 0.0) or 0.0
            board = _int(meta.get("continuous_board", meta.get("limit_times", 1)), 1)
            breaks = _int(meta.get("break_count", meta.get("open_times", 0)), 0)
            amount = _num(meta.get("seal_amount"), 0.0) or 0.0
            turnover = _num(meta.get("turnover"), 0.0) or 0.0
            one_word = _bool(meta.get("one_word_limit_up")) or (
                board >= 1 and breaks == 0 and factor_value >= 5.0 and turnover <= 1.0
            )
            snapshot[code] = {
                "symbol_code": code,
                "seal_strength": round(factor_value, 3),
                "continuous_board": board,
                "break_count": breaks,
                "seal_amount": round(amount, 3),
                "turnover": round(turnover, 3),
                "one_word_limit_up": one_word,
            }
            snapshot[code.split(".")[0]] = snapshot[code]
        return snapshot

    # ================= 1.1 三类强势行为评分 =================
    def _classify_candidate(
        self,
        factor: Dict[str, Any],
        zt_snapshot: Dict[str, Dict[str, Any]],
    ) -> StrongStockCandidate | None:
        code = _normalize_code(factor.get("symbol_code"))
        if not code:
            return None
        zt = (zt_snapshot.get(code) or zt_snapshot.get(code.split(".")[0])) if code else None

        # 共性硬过滤
        if not _bool(factor.get("data_quality_valid", True)) or str(factor.get("data_quality_status") or "ok") != "ok":
            return None
        if str(factor.get("symbol_name") or "").upper().find("ST") >= 0:
            return None
        ma20_dev = _num(factor.get("ma20_deviation_pct"))
        breakout60 = _bool(factor.get("breakout_60d"))
        if ma20_dev is not None and ma20_dev > 45 and not breakout60:
            return None

        # 连板型（第一优先级）
        cand_lian = self._assess_lianban(factor, zt)
        if cand_lian:
            return cand_lian

        # 突破型（第二优先级）
        cand_tupo = self._assess_tupo(factor, zt)
        if cand_tupo:
            return cand_tupo

        # 趋势启动型（第三优先级 / 降权）
        return self._assess_trend_start(factor, zt)

    def _assess_lianban(
        self,
        factor: Dict[str, Any],
        zt: Dict[str, Any] | None,
    ) -> StrongStockCandidate | None:
        board = _int((zt or {}).get("continuous_board", factor.get("continuous_board")), 0)
        seal = _num((zt or {}).get("seal_strength", factor.get("seal_strength")), 0.0) or 0.0
        break_count = _int((zt or {}).get("break_count", factor.get("break_count")), 0)
        one_word = _bool((zt or {}).get("one_word_limit_up", factor.get("one_word_limit_up")))

        # 连板型核心：涨停结构
        strong_structure = {
            "board_count": board,
            "seal_strength": round(seal, 3),
            "break_count": break_count,
            "one_word_limit_up": one_word,
        }
        reasons: List[str] = []
        score = 0.0
        if board >= 3:
            score += 55 + min(20, (board - 3) * 7)
            reasons.append(f"{board}连板")
        elif board == 2:
            score += 50
            reasons.append("2连板")
        elif board == 1 and seal >= 2.0:
            score += 35
            reasons.append(f"首板封单{seal:.1f}%")
        else:
            return None

        # 涨停/封单质量
        if seal >= 8:
            score += 18
            reasons.append("封单强")
        elif seal >= 4:
            score += 12
            reasons.append("封单较好")
        if break_count <= 1:
            score += 12
        else:
            score -= 12
        if one_word:
            score += 5
        # 缩量/分歧潜力：首阴观察前不要求放量，但量比健康加分
        vol = _num(factor.get("volume_ratio"))
        if vol is not None and 0.8 <= vol <= 1.8:
            score += 6
        if _bool(factor.get("close_above_ma5")):
            score += 6

        setup = min(100.0, score * 0.55 + (80 if board >= 2 else 45))
        return StrongStockCandidate(
            symbol_code=_normalize_code(factor.get("symbol_code")),
            symbol_name=str(factor.get("symbol_name") or ""),
            trade_date=str(factor.get("report_date") or ""),
            pool_type="连板",
            strong_tags=["连板"],
            strength_watch_score=round(_clamp(score), 2),
            setup_score=round(_clamp(setup), 2),
            strong_structure=strong_structure,
            limit_snapshot=strong_structure,
            technical_factor=factor,
            reasons=reasons,
        )

    def _assess_tupo(
        self,
        factor: Dict[str, Any],
        zt: Dict[str, Any] | None,
    ) -> StrongStockCandidate | None:
        breakout20 = _bool(factor.get("breakout_20d"))
        breakout60 = _bool(factor.get("breakout_60d"))
        if not (breakout20 or breakout60):
            return None
        score = 0.0
        reasons: List[str] = []
        if breakout60:
            score += 45
            reasons.append("60日新高突破")
        elif breakout20:
            score += 35
            reasons.append("20日新高突破")

        close_vs_20 = _num(factor.get("close_vs_20d_high_pct"))
        close_vs_60 = _num(factor.get("close_vs_60d_high_pct"))
        if close_vs_20 is not None and -2 <= close_vs_20 <= 5:
            score += 8
            reasons.append("突破幅度温和")
        elif close_vs_20 is not None and close_vs_20 > 12:
            score -= 8
            reasons.append("突破过快")

        vol = _num(factor.get("volume_ratio"))
        amount = _num(factor.get("amount_ratio"))
        if vol is not None and vol >= 1.2:
            score += 10
            reasons.append(f"量比{vol:.2f}")
        if amount is not None and amount >= 1.2:
            score += 8
            reasons.append("成交额放大")
        if _bool(factor.get("close_above_ma5")):
            score += 5

        # 趋势辅助但不强权重
        weekly = _num(factor.get("weekly_trend_score"))
        if weekly is not None and weekly >= 62:
            score += 6
        ma20_dev = _num(factor.get("ma20_deviation_pct"))
        if ma20_dev is not None and ma20_dev > 25 and not breakout60:
            score -= 8

        score = _clamp(score)
        if score < 45:
            return None
        return StrongStockCandidate(
            trade_date=str(factor.get("report_date") or ""),
            symbol_code=_normalize_code(factor.get("symbol_code")),
            symbol_name=str(factor.get("symbol_name") or ""),
            pool_type="突破",
            strong_tags=["突破"],
            strength_watch_score=round(score, 2),
            setup_score=round(_clamp(score * 0.75), 2),
            strong_structure={
                "breakout_20d": breakout20,
                "breakout_60d": breakout60,
                "close_vs_20d_high_pct": close_vs_20,
                "close_vs_60d_high_pct": close_vs_60,
            },
            technical_factor=factor,
            reasons=reasons,
        )

    def _assess_trend_start(
        self,
        factor: Dict[str, Any],
        zt: Dict[str, Any] | None,
    ) -> StrongStockCandidate | None:
        weekly = _num(factor.get("weekly_trend_score"), 0.0) or 0.0
        rs = _num(factor.get("relative_strength_score"), 0.0) or 0.0
        if weekly < 56 or rs < 52:
            return None
        ma20_dev = _num(factor.get("ma20_deviation_pct"))
        score = 0.0
        reasons: List[str] = []
        if weekly >= 65 and rs >= 60:
            score += 35
            reasons.append("周线/RS 强")
        elif weekly >= 58 and rs >= 52:
            score += 25
            reasons.append("趋势初步确认")
        # 趋势型降权：位置越高越减分，防止追已经走远的股票
        if ma20_dev is not None:
            if ma20_dev <= 8:
                score += 15
                reasons.append("贴20日线")
            elif ma20_dev <= 15:
                score += 6
                reasons.append("偏离合理")
            else:
                score -= 25
                reasons.append("已高估/追高段")
        if _bool(factor.get("breakout_60d")):
            score += 8
        vol = _num(factor.get("volume_ratio"))
        if vol is not None and vol >= 1.2:
            score += 8
        score = _clamp(score)
        if score < 45:
            return None
        return StrongStockCandidate(
            trade_date=str(factor.get("report_date") or ""),
            symbol_code=_normalize_code(factor.get("symbol_code")),
            symbol_name=str(factor.get("symbol_name") or ""),
            pool_type="趋势",
            strong_tags=["趋势启动"],
            strength_watch_score=round(score, 2),
            setup_score=round(_clamp(score * 0.5), 2),
            strong_structure={
                "weekly_trend_score": weekly,
                "relative_strength_score": rs,
                "ma20_deviation_pct": ma20_dev,
            },
            technical_factor=factor,
            reasons=reasons,
        )

    def _discovery_context(
        self,
        lianban: List[StrongStockCandidate],
        tupo: List[StrongStockCandidate],
        qushi: List[StrongStockCandidate],
        total: int,
    ) -> str:
        lines = [
            f"强势股票发现池（扫描 {total} 只）：",
            f"  连板型 {len(lianban)} 只",
            f"  突破型 {len(tupo)} 只",
            f"  趋势启动型 {len(qushi)} 只",
            "",
        ]
        for title, pool in (("连板型", lianban), ("突破型", tupo), ("趋势启动型", qushi)):
            if not pool:
                continue
            lines.append(f"  【{title}】")
            for c in pool[:12]:
                lines.append(
                    f"    - {c.symbol_name}({c.symbol_code}) watch={c.strength_watch_score} "
                    f"setup={c.setup_score} reasons={';'.join(c.reasons)}"
                )
        return "\n".join(lines)

    # ================= 1.2 市场情绪温度计/周期前置闸门 =================
    def _market_temperature(self, trade_date: str) -> Dict[str, Any]:
        """A股情绪温度计：退潮期直接空仓，不进 strength_watch。

        量化口径（全部可配置）：
          - 涨停家数（来自 ZT_SEAL_STORE 当日 row 数 / hot_money_akshare）
          ——退潮期：涨停家数 < market.min_limit_up_count（默认 40）
          ——炸板率过高：break_count>0 的涨停股占比 >= market.max_break_ratio（默认 0.35）
          ——连板高度受压制：最高连板数 < market.min_top_limit (默认 4)
          ——实体涨停率过低：非一字板占比 < market.min_real_zt_ratio（默认 0.4）
        返回 temperature=0~100；pass=True 代表可以进入下一阶段。
        """
        cfg = self.config.market or {}
        min_zt = int(cfg.get("min_limit_up_count", 40) or 40)
        max_break_ratio = float(cfg.get("max_break_ratio", 0.35) or 0.35)
        min_top_limit = int(cfg.get("min_top_limit", 3) or 3)
        min_ratio_zt = float(cfg.get("min_ratio_zt", 0.4) or 0.4)
        reasons: list[str] = []
        available = True
        zt_count = 0
        top_limit = 0
        zt_break = 0
        one_word = 0
        try:
            df = ZT_SEAL_STORE.load(trade_date)
            # 防未来泄漏：因子库没有当日数据时，不用原始涨停池兜底。
            # 原始 stock_zt_pool_em 可能拉到“当前/最近”日期，会把未来涨停信息带进回测。
            if df is None or df.empty:
                available = False
            if df is not None and not df.empty:
                zt_count = int(len(df))
                for _, row in df.iterrows():
                    meta = {}
                    try:
                        meta = json.loads(row.get("metadata_json") or "{}")
                    except Exception:
                        meta = {}
                    b = _int(meta.get("continuous_board", 0), 0)
                    top_limit = max(top_limit, b)
                    brk = _int(meta.get("break_count", 0), 0)
                    if brk > 0:
                        zt_break += 1
                    if _bool(meta.get("one_word_limit_up", False)) or (b >= 1 and brk == 0 and float(_num(meta.get("turnover"), 99.0) or 99.0) <= 1.0):
                        one_word += 1
        except Exception:
            available = False
        if zt_count == 0:
            # 没有涨停池说明数据缺失；在回测/无数据时不强制空仓，只做提示。避免今天全市场全被误杀。
            available = False
            reasons.append("涨停池数据缺失")
        if available:
            if zt_count < min_zt:
                reasons.append(f"涨停家数{zt_count}<{min_zt}，退潮期")
            else:
                reasons.append(f"涨停家数{zt_count}>={min_zt}")
            if zt_count > 0 and zt_break / zt_count >= max_break_ratio:
                reasons.append(f"炸板率{zt_break/zt_count:.0%}>={max_break_ratio:.0%}，情绪弱")
            if top_limit < min_top_limit:
                reasons.append(f"最高板{top_limit}<{min_top_limit}，空间被压制")
            if zt_count > 0 and (1 - one_word / zt_count) < min_ratio_zt:
                reasons.append(f"一字板占比过高，接力不健康")
        # 前置闸门：只有有数据且同时通过所有硬阈值才 temperature>=50；缺数据时保持放行（避免回测误杀）。
        passed = (
            not available
            or not (
                zt_count < min_zt
                or zt_break / max(1, zt_count) >= max_break_ratio
                or top_limit < min_top_limit
                or (1 - one_word / max(1, zt_count)) < min_ratio_zt
            )
        )
        # 更细的温度分：100 起步，每项不达标扣分；但任一硬闸不过就压到 40 以下，确保“温度<50 → 空仓”。
        score = 100.0
        if available:
            if zt_count < min_zt:
                score -= 40
            if zt_break / max(1, zt_count) >= max_break_ratio:
                score -= 10
            if top_limit < min_top_limit:
                score -= 20
            if (1 - one_word / max(1, zt_count)) < min_ratio_zt:
                score -= 10
        if not passed:
            score = min(score, 40.0)
        score = max(0.0, min(100.0, score))
        return {
            "temperature": round(score, 1),
            "passed": passed,
            "available": available,
            "limit_up_count": zt_count,
            "break_count": zt_break,
            "max_board": top_limit,
            "one_word_limit_up_count": one_word,
            "break_ratio": round(zt_break / max(1, zt_count), 3),
            "min_limit_up_count": min_zt,
            "max_break_ratio": max_break_ratio,
            "min_top_limit": min_top_limit,
            "min_ratio_zt": min_ratio_zt,
            "reasons": reasons,
        }

    def _limit_up_pool(self, trade_date: str) -> pd.DataFrame:
        """获取涨停池日频数据（含连板数/炸板次数/换手率）。"""
        try:
            return akshare_cached.run(
                func_name="stock_zt_pool_em",
                func_kwargs={"date": trade_date},
                verbose=False,
            )
        except Exception:
            return pd.DataFrame()

    # ================= 2. 强势观察池（分层配额 + 概念去重） =================
    def merge_watchlist(
        self,
        discovery: DiscoveryPool,
        prev_watchlist: Optional[List[WatchlistItem]],
        trade_date: str,
    ) -> WatchlistPool:
        by_code: Dict[str, WatchlistItem] = {}
        for item in prev_watchlist or []:
            by_code[item.symbol_code] = item

        def _upsert(cand: StrongStockCandidate):
            item = by_code.get(cand.symbol_code)
            if item:
                if cand.technical_factor:
                    item.factors.append(cand.technical_factor)
                    del item.factors[:-5]
                if cand.strength_watch_score > item.strength_watch_score:
                    item.strength_watch_score = cand.strength_watch_score
                    item.setup_score = cand.setup_score
                    item.pool_type = cand.pool_type
                item.strong_tags = sorted(set(item.strong_tags).union(cand.strong_tags))
            else:
                by_code[cand.symbol_code] = WatchlistItem(
                    symbol_code=cand.symbol_code,
                    symbol_name=cand.symbol_name,
                    trade_date=trade_date,
                    pool_type=cand.pool_type,
                    strong_tags=list(cand.strong_tags),
                    strength_watch_score=cand.strength_watch_score,
                    setup_score=cand.setup_score,
                    strong_structure=cand.strong_structure,
                    limit_snapshot=cand.limit_snapshot,
                    factors=[cand.technical_factor],
                )

        for cand in discovery.all_candidates:
            _upsert(cand)

        # 分层配额
        lian = sorted(
            [x for x in by_code.values() if x.pool_type == "连板"],
            key=lambda x: x.strength_watch_score, reverse=True,
        )[: self._quota("连板")]
        tupo = sorted(
            [x for x in by_code.values() if x.pool_type == "突破"],
            key=lambda x: x.strength_watch_score, reverse=True,
        )[: self._quota("突破")]
        qushi = sorted(
            [x for x in by_code.values() if x.pool_type == "趋势"],
            key=lambda x: x.strength_watch_score, reverse=True,
        )[: self._quota("趋势")]
        all_items = lian + tupo + qushi
        return WatchlistPool(lian=lian, tupo=tupo, qushi=qushi, all_items=all_items)

    def _quota(self, pool_type: str) -> int:
        w = self.config.watchlist or {}
        key = {
            "连板": "max_lianban",
            "突破": "max_tupo",
            "趋势": "max_qushi",
        }.get(pool_type, "max_qushi")
        return int(w.get(key, 15 if pool_type == "突破" else 10) or (15 if pool_type == "突破" else 10))

    # ================= 2.5 统一生命周期状态机：强势 -> 分歧事件 -> 质量 -> 确认 -> Gate =================

    # ---------------- 2.5.1 严格生命周期元数据 ----------------
    def _load_intraday_vwap(self, symbol: str, factor: Dict[str, Any]) -> Optional[float]:
        """Try EastMoney minute-level VWAP; fallback to daily vwap_20/vwap.

        This is the T+1/real-time confirmation for weak_to_strong gate;
        when intraday data is unavailable we degrade to daily VWAP proxy.
        """
        existing = _num(factor.get("vwap_intraday"))
        if existing is not None:
            return existing
        code = "".join(ch for ch in str(symbol or "") if ch.isdigit())
        code6 = code[-6:] if len(code) >= 6 else code.zfill(6)
        if not code6:
            return _num(factor.get("vwap_20")) or _num(factor.get("vwap"))
        try:
            df = akshare_cached.run(
                "stock_zh_a_hist_min_em",
                {"symbol": code6, "period": "5", "adjust": "", "start_date": factor.get("report_date") or "", "end_date": factor.get("report_date") or ""},
                verbose=False,
            )
            if df is not None and not df.empty:
                if "成交额" in df.columns and "成交量" in df.columns:
                    amount = pd.to_numeric(df["成交额"], errors="coerce")
                    vol = pd.to_numeric(df["成交量"], errors="coerce")
                    price_col = next((c for c in ("收盘", "最新价", "close") if c in df.columns), None)
                    price = pd.to_numeric(df[price_col], errors="coerce") if price_col else pd.Series(dtype=float)
                    mask = (vol > 0) & price.notna() & (price > 0)
                    if int(mask.sum()) >= 5:
                        vwap = float((price[mask] * vol[mask]).sum() / vol[mask].sum())
                        factor["vwap_intraday"] = round(vwap, 3)
                        return vwap
        except Exception:
            pass
        vwap = _num(factor.get("vwap_20")) or _num(factor.get("vwap"))
        if vwap is not None:
            factor["vwap_intraday"] = vwap
        return vwap

    def refresh_lifecycle_metadata(self, watch_pool: WatchlistPool) -> None:
        """根据 factors 历史序列刷新所有观察池股票的生命周期元数据。

        严格区分：
          - “今天跌了” != “首阴”；只有强势阶段结束后第一次收阴才算 first_negative
          - “今天没涨停” != “断板”；只有强势阶段第一次不涨停才算 first_non_board
        """
        for item in watch_pool.all_items:
            self._refresh_lifecycle(item)

    def _refresh_lifecycle(self, item: WatchlistItem) -> None:
        """从 factors 序列重建强势生命周期字段。"""
        if not item.strong_phase_enter_date and item.factors:
            first_date = item.factors[0].get("report_date") or item.trade_date
            if first_date:
                item.strong_phase_enter_date = str(first_date)

        # 若 strong_structure 提供连板快照，用 trade_date 作为最后一次涨停日，保证生命周期可推导
        structural_board = _int(item.strong_structure.get("board_count"), _int(item.limit_snapshot.get("continuous_board"), 0))
        if structural_board >= 1 and not item.last_board_date:
            item.last_board_date = item.trade_date
            item.consecutive_board_count = max(item.consecutive_board_count, structural_board)

        last_board_date = item.last_board_date
        last_board_close = item.last_board_close
        first_non_board = item.first_non_board_date or ""
        first_negative = item.first_negative_date or ""

        # 用历史序列重新推导（若已有值则保留最早，不主动清空）
        for i, factor in enumerate(item.factors):
            report_date = str(factor.get("report_date") or "")
            if not report_date:
                # 测试/回放中 technical_factor 有时未带 report_date；退化为 trade_date
                report_date = item.trade_date if i == len(item.factors) - 1 else ""
            if not report_date:
                continue
            board_in_factor = _int(factor.get("continuous_board"), 0)
            change = _num(factor.get("change_pct"))
            is_limit_up = bool(board_in_factor and board_in_factor >= 1)
            if not is_limit_up and _is_limit_up_change(item.symbol_code, change):
                is_limit_up = True
            close = _num(factor.get("close")) or _num(factor.get("close_price"))

            if is_limit_up:
                item.consecutive_board_count = max(
                    item.consecutive_board_count,
                    board_in_factor,
                )
                last_board_date = report_date
                last_board_close = close
                if not item.strong_phase_enter_date:
                    item.strong_phase_enter_date = report_date
                continue

            if not last_board_date:
                continue

            if not first_non_board:
                first_non_board = report_date
            if change is not None and change < 0 and not first_negative:
                first_negative = report_date

        # 写入 / 保留
        if last_board_date:
            item.last_board_date = last_board_date
            item.last_board_close = last_board_close
        if first_non_board:
            item.first_non_board_date = first_non_board
        if first_negative:
            item.first_negative_date = first_negative

    def _detect_divergence_event_on_item(self, item: WatchlistItem, trade_date: str) -> Dict[str, Any]:
        """确定今天是否是一个真正 divergence event，并把分歧质量分级。

        divergence_event(成立条件):
          strong_phase=True
          AND (第一次不涨停 或 第一次收阴)
          特别地：+5% 正涨幅的健康断板仍可产生 Event（值得观察）。
        divergence_quality(评分/分级): 只回答这次分歧健不健康。
          - 断板 A类=健康断板（正涨幅 + 缩量 + 收盘位置高）
          - 断板 B类=中性断板（平/微涨 + 量正常）
          - 断板 C类=弱断板（大跌 + 放量 + 跌破关键位）
        """
        cfg = self.config.divergence or {}
        min_score = float(cfg.get("min_score", 60) or 60)
        allow_shouyin = _bool(cfg.get("allow_shouyin", True))
        allow_anban = _bool(cfg.get("allow_duanban", True))
        max_shouyin_down = float(cfg.get("max_first_break_down_pct", -5.0) or -5.0)
        max_anban_up = _max_duanban_up(item.symbol_code, float(cfg.get("max_duanban_gain_pct", 8.0) or 8.0))
        max_break = int(cfg.get("max_break_count", 1) or 1)
        latest = item.latest_factor()
        change = _num(latest.get("change_pct"))
        vol = _num(latest.get("volume_ratio"))
        board = _int(item.strong_structure.get("board_count"), _int(item.limit_snapshot.get("continuous_board"), 0))
        break_count = _int(item.strong_structure.get("break_count"), _int(item.limit_snapshot.get("break_count"), 0))
        close_above_ma5 = _bool(latest.get("close_above_ma5"))

        strong_phase = bool(
            item.last_board_date
            or item.consecutive_board_count >= 1
            or item.strong_phase_enter_date
            or item.pool_type == "连板"
        )
        # 炸板失败：强结构快照中的炸板次数 >0，表示当日曾尝试涨停失败/破板
        failed_board = bool(
            break_count >= 1
            and _bool(item.strong_structure.get("failed_board", item.limit_snapshot.get("failed_board")))
        )
        today_is_non_board = bool(change is not None and not _is_limit_up_change(item.symbol_code, change))
        today_is_negative = bool(change is not None and change < 0)
        # refresh_lifecycle 可能已把今天记录为 first_non/first_negative，
        # 所以这里同时允许“未记录”或“正好等于今天”，保证事件当天能触发。
        first_non_board = bool(
            strong_phase
            and item.last_board_date
            and today_is_non_board
            and (not item.first_non_board_date or item.first_non_board_date == trade_date)
        )
        first_negative_date = bool(
            strong_phase
            and today_is_negative
            and (not item.first_negative_date or item.first_negative_date == trade_date)
        )
        if first_non_board and not item.first_non_board_date:
            item.first_non_board_date = trade_date
        if first_negative_date and not item.first_negative_date:
            item.first_negative_date = trade_date

        # ---- 明确的分歧成立条件 ----
        # Divergence Event 必须来自强势生命周期内的“第一次不涨停 / 第一次收阴”。
        # 质量分单独计算，不再用“今天是不是跌了”充当分歧本身。
        # 注意：先保留强势后第一根非涨停阳线（A例 +5%）为可观察断板，因此 Event 以 first_non_board 为准，
        # 同时用 failed_board 炸板失败作为 C 类弱分歧的强化证据。
        lifecycle_divergence_ok = bool(strong_phase and (first_non_board or first_negative_date))
        event_divergence_ok = bool(lifecycle_divergence_ok)

        mode = "none"
        score = 0.0
        reason_list: List[str] = []
        if event_divergence_ok:
            if change is not None and change <= 0:
                if allow_shouyin and (board >= 1 or item.pool_type == "连板"):
                    mode = "首阴"
                    score = 45
                    reason_list.append("强势后首次阴线(严格首阴)")
                elif allow_anban:
                    mode = "断板"
                    score = 40
                    reason_list.append("断板(首次不涨停)")
            elif change is not None and 0 < change <= max_anban_up:
                # 正涨幅断板：若炸板失败则明确给出炸板证据
                if allow_anban and (first_non_board or item.first_non_board_date):
                    mode = "断板"
                    score = 40
                    if failed_board:
                        reason_list.append("断板(首次不涨停,正涨幅,炸板失败)")
                    else:
                        reason_list.append("断板(首次不涨停,正涨幅)")
                else:
                    mode = "none"
                    score = 0.0
            else:
                mode = "none"
                score = 0.0

            # ---- 质量分与分级（这次分歧健不健康，而不是今天是不是跌了） ----
            if mode == "首阴":
                if change is not None and change >= max_shouyin_down:
                    score += 12
                else:
                    score -= 12
                if close_above_ma5:
                    score += 10
                if vol is not None and vol < 1.0:
                    score += 8
                    reason_list.append("缩量")
                if _bool(latest.get("ma5_slope_pct") is not None and _num(latest.get("ma5_slope_pct")) > 0):
                    score += 6
            elif mode == "断板":
                if board >= 2:
                    score += 10
                    reason_list.append(f"连续{board}板后断板")
                if break_count <= max_break:
                    score += 8
                else:
                    score -= 8
                seal = _num(item.limit_snapshot.get("seal_strength"))
                if seal is not None and seal >= 5:
                    score += 12
                if (change or 0) <= (6 if _max_duanban_up(item.symbol_code) <= 8 else 12):
                    score += 8
                if vol is not None and 0.7 <= vol <= 1.4:
                    score += 6
                # 创业板/科创板 20cm 断板，正涨幅空间更大，给一点权重避免被 min_score 卡死
                if _max_duanban_up(item.symbol_code) > 8:
                    score += 6

        score = _clamp(score)
        # 入门必须同时满足：生命周期条件 + 价格/炸板条件 + 品质分线
        is_event = bool(event_divergence_ok and score >= min_score)

        # ---- 质量等级：首阴与断板分开 ----
        divergence_class = ""
        divergence_grade = ""
        if is_event:
            if mode == "首阴":
                # 健康分歧：缩量 + 跌幅不大 + 收盘位置高
                if vol is not None and vol < 1.0 and (change or 0) >= -4 and close_above_ma5:
                    divergence_class = "健康分歧"
                    divergence_grade = "A"
                elif (change or 0) <= max_shouyin_down or not close_above_ma5:
                    divergence_class = "弱分歧"
                    divergence_grade = "C"
                else:
                    divergence_class = "中性分歧"
                    divergence_grade = "B"
            else:
                # 断板分级：A=健康断板、B=中性断板、C=弱断板
                key_broken = self._close_key_level_broken(item, latest, change)
                a_min = float(cfg.get("break_grade_A_min_change_pct", 1.0) or 1.0)
                a_max_vol = float(cfg.get("break_grade_A_max_volume_ratio", 1.0) or 1.0)
                b_min = float(cfg.get("break_grade_B_min_change_pct", -3.0) or -3.0)
                b_max = float(cfg.get("break_grade_B_max_change_pct", 1.0) or 1.0)
                b_vol_min = float(cfg.get("break_grade_B_min_volume_ratio", 0.8) or 0.8)
                b_vol_max = float(cfg.get("break_grade_B_max_volume_ratio", 1.8) or 1.8)
                if (change or 0) > a_min and vol is not None and vol < a_max_vol and close_above_ma5 and not key_broken:
                    divergence_class = "健康断板"
                    divergence_grade = "A"
                elif (change or 0) > b_min and (change or 0) <= b_max and vol is not None and b_vol_min <= vol <= b_vol_max and not key_broken:
                    divergence_class = "中性断板"
                    divergence_grade = "B"
                else:
                    divergence_class = "弱断板"
                    divergence_grade = "C"

        # 适配旧字段：只保留三条旧分类字符串（健康分歧/中性分歧/弱分歧），再补充 grade
        if divergence_class == "健康断板":
            divergence_class = "健康分歧"
        elif divergence_class == "中性断板":
            divergence_class = "中性分歧"
        elif divergence_class == "弱断板":
            divergence_class = "弱分歧"

        return {
            "mode": mode,
            "score": round(score, 2),
            "recommended": is_event,
            "reasons": reason_list,
            "class": divergence_class,
            "grade": divergence_grade,
            "first_non_board": first_non_board,
            "first_negative_date": first_negative_date,
            "board": board,
            "break_count": break_count,
        }

    def _close_key_level_broken(self, item: WatchlistItem, factor: Dict[str, Any], change: Optional[float]) -> bool:
        """收盘跌破关键位：跌破20日前高/重要均线/涨停开盘等，视为弱分歧。"""
        close_vs_20h = _num(factor.get("close_vs_20d_high_pct"))
        ma5 = _num(factor.get("ma5"))
        close = _num(factor.get("close"))
        if close_vs_20h is not None and close_vs_20h <= -8:
            return True
        if ma5 is not None and close is not None and close < ma5:
            return True
        return False

    def detect_divergence(
        self,
        watch_pool: WatchlistPool,
        trade_date: str,
    ) -> List[DivergenceSignal]:
        """检测真正 divergence event，而不是简单按当日涨跌判断。"""
        self.refresh_lifecycle_metadata(watch_pool)
        cfg = self.config.divergence
        min_score = float(cfg.get("min_score", 60) or 60)
        signals: List[DivergenceSignal] = []
        for item in watch_pool.all_items:
            ev = self._detect_divergence_event_on_item(item, trade_date)
            mode = ev["mode"]
            score = ev["score"]
            is_event = ev["recommended"]
            # 一旦形成事件，记录到 state / divergence_dates
            if is_event:
                item.divergence_event = True
                item.divergence_mode = mode
                item.divergence_class = ev["class"]
                item.divergence_grade = ev.get("grade", "")
                item.divergence_quality_score = score
                item.divergence_quality_reasons = list(ev["reasons"])
                if trade_date not in item.divergence_dates:
                    item.divergence_dates.append(trade_date)
                if item.state == "强势观察池":
                    item.state = "首次"
                    item.state_reasons = ["状态机：真正分歧事件触发首次分歧"]
            signals.append(DivergenceSignal(
                symbol_code=item.symbol_code,
                symbol_name=item.symbol_name,
                trade_date=trade_date,
                pool_type=item.pool_type,
                divergence_mode=mode,
                divergence_score=score,
                divergence_pass=is_event,
                divergence_reasons=list(ev["reasons"]),
                strength_watch_score=item.strength_watch_score,
                setup_score=item.setup_score,
                factor=item.latest_factor(),
                divergence_event=is_event,
                divergence_class=ev["class"],
                divergence_grade=ev.get("grade", ""),
                consecutive_board_count=item.consecutive_board_count,
                first_non_board=ev["first_non_board"],
                first_negative_date=ev["first_negative_date"],
                divergence_quality_score=score,
                divergence_quality_reasons=list(ev["reasons"]),
            ))
        return signals

    def advance_lifecycle_states(
        self,
        watch_pool: WatchlistPool,
        trade_date: str,
    ) -> None:
        """推进 state，但与 detect_divergence 共用同一套严格生命周期定义。"""
        self.refresh_lifecycle_metadata(watch_pool)
        for item in watch_pool.all_items:
            factor = item.latest_factor()
            if not factor:
                continue
            # 恶性分歧（C级）：基本淘汰，不进入 WAIT_CONFIRM。
            # 只有尚未确认的首次分歧才标记 EXIT；已确认/已买入的情况由 holding 阶段处理。
            if item.divergence_grade == "C" and item.state not in {"T+1买入候选", "已确认"}:
                item.state = "分歧失败"
                item.state_reasons = ["状态机：C级恶性分歧 -> 基本淘汰，不进入等待确认"]
                item.last_reasons = list(item.state_reasons or [])
                continue
            close_above_ma5 = _bool(factor.get("close_above_ma5"))
            ma5_slope = _num(factor.get("ma5_slope_pct"))
            vol = _num(factor.get("volume_ratio"))
            if item.state in {"T+1买入候选", "已确认"}:
                continue

            if item.state == "强势观察池":
                # detect_divergence 已设置真实 divergence_dates；这里只做防御性兜底
                if not item.divergence_dates and item.first_non_board_date and trade_date >= item.first_non_board_date:
                    item.state = "首次"
                    if trade_date not in item.divergence_dates:
                        item.divergence_dates.append(trade_date)
                    item.state_reasons = ["状态机：第一次断板/首阴产生首次分歧"]
            elif item.state == "首次" and item.divergence_dates:
                last_div = item.divergence_dates[-1]
                same_day_div = last_div == trade_date
                if same_day_div:
                    continue
                gate = self._check_weak_to_strong_gates(item, trade_date)
                if gate["confirmed"]:
                    item.weak_to_strong_confirmed = True
                    item.weak_to_strong_gate_detail = gate
                    item.weak_to_strong_reasons = list(gate["reasons"])
                    item.state = "确认观察"
                    item.confirmation_dates.append(trade_date)
                    item.state_reasons = ["状态机：弱转强Gate通过 -> 确认观察"]
                elif item.divergence_grade == "C":
                    item.state = "分歧失败"
                    item.state_reasons = ["状态机：C级弱分歧且未通过弱转强Gate -> 基本淘汰"]
                else:
                    item.state_reasons = ["分歧后尚未通过弱转强Gate"]
            elif item.state == "确认观察" and item.confirmation_dates:
                last_conf = item.confirmation_dates[-1]
                if last_conf == trade_date:
                    continue
                if close_above_ma5 and ma5_slope is not None and ma5_slope > 0:
                    gate = self._check_weak_to_strong_gates(item, trade_date)
                    if gate["confirmed"]:
                        item.weak_to_strong_confirmed = True
                        item.weak_to_strong_gate_detail = gate
                        item.weak_to_strong_reasons = list(gate["reasons"])
                        item.state = "T+1买入候选"
                        item.state_reasons = ["状态机：确认后再次走强且Gate通过"]
                    else:
                        item.state_reasons = ["确认后次日未通过弱转强Gate"]
                else:
                    item.state_reasons = ["确认后未再次走强"]
                if item.divergence_grade == "C" and not item.weak_to_strong_confirmed:
                    item.state = "分歧失败"
                    item.state_reasons = ["状态机：C级弱分歧确认失败 -> 基本淘汰"]
            item.last_reasons = list(item.state_reasons or [])

    def _check_weak_to_strong_gates(self, item: WatchlistItem, trade_date: str) -> Dict[str, Any]:
        """Weak-to-Strong 硬条件（严格 Gate）：5 个条件 ≥ 4 才返回 confirmed=True。

        Gate 1 站上开盘价：收盘 >= 开盘
        Gate 2 站上VWAP：收盘 >= VWAP
        Gate 3 回踩VWAP成功：盘中回踩 VWAP 附近（low<=VWAP 且 收盘>=VWAP 且 low 距 VWAP <= 容差）
        Gate 4 HI/HL 短线结构：最近两个已完成交易日 高点抬高 AND 低点抬高
        Gate 5 量价确认：上涨放量 OR 回踩缩量+站上MA5
        """
        cfg = self.config.confirmation or {}
        required = int(cfg.get("weak_to_strong_gates_required", 4) or 4)
        factor = item.latest_factor()
        if not factor:
            return {"confirmed": False, "passed_count": 0, "required": required, "gates": {}, "reasons": ["无当日因子"]}
        close = _num(factor.get("close")) or _num(factor.get("close_price"))
        open_price = _num(factor.get("open")) or _num(factor.get("open_price"))
        vwap = _num(factor.get("vwap_intraday")) or _num(factor.get("vwap_20")) or _num(factor.get("vwap")) or _num(factor.get('vwap20'))
        if vwap is None:
            vwap = self._load_intraday_vwap(item.symbol_code, factor)
        change = _num(factor.get("change_pct"))
        vol = _num(factor.get("volume_ratio"))
        close_above_ma5 = _bool(factor.get("close_above_ma5"))
        ma5_slope = _num(factor.get("ma5_slope_pct"))
        low = _num(factor.get("low"))
        hh_strict = _bool(factor.get("hh_strict"))
        hl_strict = _bool(factor.get("hl_strict"))
        hh_hl_strict = _bool(factor.get("hh_hl_strict"))
        pullback_near_vwap = _bool(factor.get("pullback_near_vwap"))
        pullback_shrink = _bool(factor.get("pullback_shrink"))
        rising_volume = _bool(factor.get("rising_volume"))

        # ---- Gate 1: 站上开盘价（规则是站在开盘价上方；用日线时以收盘>=开盘近似） ----
        if close is not None and open_price is not None:
            above_open = bool(close >= open_price)
        elif change is not None and change > 0:
            above_open = True
        else:
            above_open = False

        # ---- Gate 2: 站上VWAP（严格 close >= VWAP；缺失时不再退化为 MA5） ----
        if vwap is not None and close is not None:
            above_vwap = bool(close >= vwap)
        elif vwap is not None:
            above_vwap = False
        else:
            above_vwap = False

        # ---- Gate 3: 回踩VWAP成功（必须“回踩过” VWAP 且收盘仍站在 VWAP 上方） ----
        # 优先用新出的 pullback_near_vwap（low 接近 VWAP、低破 VWAP、收盘高于 VWAP）；
        # 没有 intraday 时，退化用 daily vwap_20 + low/close 粗略判断，但需保证“回踩”仍存在。
        if pullback_near_vwap:
            pullback_vwap = True
        elif vwap is not None and low is not None and close is not None:
            pullback_vwap = bool(low <= vwap <= close)
        else:
            pullback_vwap = False

        # ---- Gate 4: HH/HL 短线结构（严格比较前两日高点/低点，排除当日避免前视） ----
        if hh_hl_strict:
            hh_hl_structure = True
        else:
            # 兼容手工 factor：若只有 close_above_ma5 + ma5_slope>0，且没有 hh/hl 数据，则仅作弱结构代理，不再视为通过。
            hh = _bool(factor.get("hh_above_prev"))
            hl = _bool(factor.get("hl_above_prev"))
            hh_hl_structure = bool(hh and hl)

        # ---- Gate 5: 量价确认（上涨放量 OR 回调缩量+站上MA5；若给了竞价量/开盘30min额则作为附加证据） ----
        auction_ok = _bool(factor.get("auction_volume_ratio_ok")) or _bool(factor.get("open_amount_ratio_ok"))
        if rising_volume and (change is not None and change > 0):
            volume_price_health = True
        elif auction_ok and (close is not None and open_price is not None and close >= open_price):
            volume_price_health = True
        elif pullback_shrink:
            volume_price_health = True
        elif vol is not None and change is not None and ((vol >= 1.0 and change > 0) or (vol < 1.0 and close_above_ma5)):
            volume_price_health = True
        else:
            volume_price_health = False

        gates = {
            "站上开盘价": above_open,
            "站上VWAP": above_vwap,
            "回踩VWAP成功": pullback_vwap,
            "HH/HL短线结构": hh_hl_structure,
            "量价健康": volume_price_health,
        }
        passed_count = sum(1 for p in gates.values() if p)
        confirmed = bool(passed_count >= required)
        reasons = [f"{name}:{'是' if p else '否'}" for name, p in gates.items()]
        return {
            "confirmed": confirmed,
            "passed_count": passed_count,
            "required": required,
            "gates": gates,
            "reasons": reasons,
        }
    def apply_state_machine(
        self,
        watch_pool: WatchlistPool,
        trade_date: str,
    ) -> List[Dict[str, Any]]:
        """统一生命周期：经过 divergence_event + weak_to_strong Gate + entry_quality Gate。"""
        cfg = self.config.confirmation
        min_entry = float(cfg.get("min_entry_quality_score", 70) or 70)
        min_weak = float(cfg.get("min_weak_to_strong_score", 80) or 80)
        # MA5 is background confirmation only; it should not hard-block a T+1 buy
        # when price already holds Open/VWAP/HH-HL/volume and passes Weak-to-Strong Gate.
        require_ma5 = _bool(cfg.get("min_close_above_ma5", False))
        out: List[Dict[str, Any]] = []
        for item in watch_pool.all_items:
            factor = item.latest_factor()
            if not factor:
                continue
            chain_ok = bool(
                item.state == "T+1买入候选"
                and item.divergence_dates
                and item.confirmation_dates
                and item.weak_to_strong_confirmed
            )
            if not chain_ok:
                continue

            entry = self._compute_entry_quality(item, factor)
            weak = self._compute_weak_to_strong_score(item, factor)
            reasons = list(item.weak_to_strong_reasons)
            if item.divergence_class:
                reasons.append(f"分歧等级:{item.divergence_class}")
            if factor.get("auction_volume_ratio_ok"):
                reasons.append("竞价量能确认")
            if factor.get("open_amount_ratio_ok"):
                reasons.append("开盘30min额确认")
            if item.divergence_grade:
                reasons.append(f"分歧Grade:{item.divergence_grade}")
            reasons.append(f"入场质量{entry:.1f}")
            reasons.append(f"弱转强Gate确认:{item.weak_to_strong_confirmed}")
            if entry >= min_entry:
                reasons.append(f"入场质量{entry:.1f}>= {min_entry}")
            else:
                reasons.append(f"入场{entry:.1f}不足{min_entry}")
            ready = bool(entry >= min_entry)
            if weak < min_weak:
                ready = False
                reasons.append(f"弱转强分数{weak:.1f}<{min_weak}")
            if require_ma5 and not _bool(factor.get("close_above_ma5")):
                reasons.append("未站上MA5")
                ready = False
            elif not _bool(factor.get("close_above_ma5")):
                # 背景确认：不硬性否决，仅提示日线短期结构可能被破坏。
                reasons.append("MA5未站上(背景确认，不作为硬Gate)")
            out.append({
                "symbol_code": item.symbol_code,
                "symbol_name": item.symbol_name,
                "trade_date": trade_date,
                "lifecycle_state": "T+1买入候选" if ready else "等待确认",
                "pool_type": item.pool_type,
                "divergence_mode": item.divergence_mode or "state_machine",
                "divergence_score": item.divergence_quality_score or item.setup_score,
                "entry_quality_score": round(entry, 2),
                "weak_to_strong_score": round(weak, 2),
                "t1_buy_score": round(entry * 0.5 + weak * 0.5, 2),
                "buy_ready": ready,
                "state": item.state,
                "divergence_dates": list(item.divergence_dates),
                "confirmation_dates": list(item.confirmation_dates),
                "reasons": reasons,
                "divergence_event": item.divergence_event,
                "divergence_class": item.divergence_class,
                "divergence_grade": item.divergence_grade,
                "divergence_quality_reasons": list(item.divergence_quality_reasons),
                "weak_to_strong_confirmed": item.weak_to_strong_confirmed,
                "weak_to_strong_gate_detail": item.weak_to_strong_gate_detail,
                "weak_to_strong_reasons": list(item.weak_to_strong_reasons),
                "entry_quality_reasons": [],
            })
        return out

    # ---------------- 3. 独立评分模块：职责分离 ----------------

    def _compute_divergence_quality_score(self, item: WatchlistItem, factor: Dict[str, Any]) -> float:
        """分歧质量：只回答这次分歧健不健康。"""
        mode = item.divergence_mode
        change = _num(factor.get("change_pct"))
        vol = _num(factor.get("volume_ratio"))
        amount = _num(factor.get("amount_ratio"))
        close_above_ma5 = _bool(factor.get("close_above_ma5"))
        break_count = _int(item.limit_snapshot.get("break_count"), 0)
        score = 0.0
        if mode == "首阴":
            score += 45
            if change is not None and -5 <= change <= 0:
                score += 12
            else:
                score -= 10
            if close_above_ma5:
                score += 10
            if vol is not None and vol < 1.0:
                score += 8
            if amount is not None and amount < 1.0:
                score += 4
        elif mode == "断板":
            score += 40
            if item.consecutive_board_count >= 2:
                score += 10
            if break_count <= 1:
                score += 8
            else:
                score -= 8
            if vol is not None and 0.7 <= vol <= 1.4:
                score += 8
            if change is not None and 0 <= change <= 6:
                score += 8
            if close_above_ma5:
                score += 5
        else:
            return 0.0
        return round(_clamp(score), 2)

    def _compute_weak_to_strong_score(self, item: WatchlistItem, factor: Dict[str, Any]) -> float:
        """weak_to_strong 分数：只回答分歧后重新转强的强度；Gate 决定是否可用。"""
        if not item.weak_to_strong_confirmed:
            # 没有通过 Gate，评分再高也不可直接买入
            return 0.0
        close = _num(factor.get("close")) or _num(factor.get("close_price"))
        open_price = _num(factor.get("open")) or _num(factor.get("open_price"))
        vwap = _num(factor.get("vwap_intraday")) or _num(factor.get("vwap_20")) or _num(factor.get("vwap")) or _num(factor.get("vwap20"))
        if vwap is None:
            vwap = self._load_intraday_vwap(item.symbol_code, factor)
        vol = _num(factor.get("volume_ratio"))
        change = _num(factor.get("change_pct"))
        close_above_ma5 = _bool(factor.get("close_above_ma5"))
        ma5_slope = _num(factor.get("ma5_slope_pct"))
        low = _num(factor.get("low"))
        score = 0.0
        if close is not None and open_price is not None and close >= open_price:
            score += 15
        if vwap is not None and close is not None and close >= vwap:
            score += 20
        if vwap is not None and low is not None and close is not None and low <= vwap <= close:
            score += 25
        # MA5 降级为背景确认：可加背景分，但核心仍是 open / VWAP / 回踩 / HH-HL / 量价。
        if close_above_ma5:
            score += 5
        if ma5_slope is not None and ma5_slope > 0:
            score += 5
        if vol is not None and change is not None:
            if vol >= 1.0 and change > 0:
                score += 20
            elif vol < 1.0 and close_above_ma5:
                score += 10
        return round(_clamp(score), 2)

    # ---------------- 4. entry_quality: 回答这个价格值不值得买 ----------------
    def _compute_entry_quality(self, item: WatchlistItem, factor: Dict[str, Any]) -> float:
        """entry_quality：只回答该价格值不值得买（不重复计 VWAP/量比/MA5）。"""
        score = 50.0
        change = _num(factor.get("change_pct"))
        close = _num(factor.get("close")) or _num(factor.get("close_price"))
        open_price = _num(factor.get("open")) or _num(factor.get("open_price"))
        close_vs_20h = _num(factor.get("close_vs_20d_high_pct"))
        ma20_dev = _num(factor.get("ma20_deviation_pct"))
        reason_list: list[str] = []

        if change is not None:
            if 0 <= change <= 7:
                score += 10
            elif 7 < change <= 9.5:
                score -= 5
                reason_list.append("临近涨停再去追")
            elif change < -2:
                score -= 12
        if open_price is not None and close is not None and close < open_price:
            score -= 8
            reason_list.append("收盘低于开盘")
        if close_vs_20h is not None and close_vs_20h <= -8:
            score -= 12
            reason_list.append("距前高过远")
        elif close_vs_20h is not None and close_vs_20h >= -2:
            score += 8
            reason_list.append("贴近前高")
        if ma20_dev is not None:
            if -3 <= ma20_dev <= 18:
                score += 6
            elif ma20_dev > 35:
                score -= 8
        # 不需要再放 VWAP / MA5 / 量比 在这里，避免与 weak_to_strong 重复
        score = _clamp(score)
        return score

    def _build_buy_signals_from_state(self, rows: List[Dict[str, Any]], trade_date: str) -> List[BuySignal]:
        out = []
        for d in rows:
            out.append(BuySignal(
                symbol_code=d["symbol_code"],
                symbol_name=d["symbol_name"],
                trade_date=d["trade_date"],
                lifecycle_state=d["lifecycle_state"],
                pool_type=d["pool_type"],
                divergence_mode=d["divergence_mode"],
                divergence_score=d["divergence_score"],
                entry_quality_score=d["entry_quality_score"],
                weak_to_strong_score=d["weak_to_strong_score"],
                t1_buy_score=d["t1_buy_score"],
                buy_ready=d["buy_ready"],
                reasons=d["reasons"],
                divergence_event=d.get("divergence_event", False),
                divergence_class=d.get("divergence_class", ""),
                divergence_grade=d.get("divergence_grade", ""),
                divergence_quality_reasons=list(d.get("divergence_quality_reasons", [])),
                weak_to_strong_confirmed=d.get("weak_to_strong_confirmed", False),
                weak_to_strong_gate_detail=d.get("weak_to_strong_gate_detail", {}),
                weak_to_strong_reasons=list(d.get("weak_to_strong_reasons", [])),
                entry_quality_reasons=list(d.get("entry_quality_reasons", [])),
            ))
        return out

    # ================= 4. 兼容旧 confirm_buy（仍保持等待 Gate，不能直接买入） =================
    def confirm_buy(self, divergences: List[DivergenceSignal]) -> List[BuySignal]:
        out: List[BuySignal] = []
        for d in divergences:
            if not d.divergence_event or not d.divergence_pass:
                continue
            factor = d.factor or {}
            item_proxy = WatchlistItem(
                symbol_code=d.symbol_code,
                symbol_name=d.symbol_name,
                trade_date=d.trade_date,
                pool_type=d.pool_type,
                strength_watch_score=d.strength_watch_score,
                setup_score=d.setup_score,
            )
            item_proxy.consecutive_board_count = d.consecutive_board_count
            item_proxy.divergence_mode = d.divergence_mode
            item_proxy.divergence_class = d.divergence_class
            item_proxy.divergence_grade = d.divergence_grade
            entry = self._compute_entry_quality(item_proxy, factor)
            weak = 0.0  # confirm_buy 不能一次性买入，必须走状态机 Gate
            reasons = list(d.divergence_quality_reasons or d.divergence_reasons)
            reasons.append("确认路径：触发强分歧Event但需Gate确认后续")
            if d.divergence_class:
                reasons.append(f"分歧等级:{d.divergence_class}")
            out.append(BuySignal(
                symbol_code=d.symbol_code,
                symbol_name=d.symbol_name,
                trade_date=d.trade_date,
                lifecycle_state="等待确认",
                pool_type=d.pool_type,
                divergence_mode=d.divergence_mode,
                divergence_score=d.divergence_quality_score,
                entry_quality_score=round(entry, 2),
                weak_to_strong_score=0.0,
                t1_buy_score=round(entry * 0.5, 2),
                buy_ready=False,
                reasons=reasons,
                divergence_event=True,
                divergence_class=d.divergence_class,
                divergence_grade=d.divergence_grade,
                divergence_quality_reasons=list(d.divergence_quality_reasons),
            ))
        return out

    # ================= 5. T+1 买入计划 =================
    def build_t1_buy_plan(self, confirmed: List[BuySignal]) -> List[BuySignal]:
        t1 = self.config.t1_buy
        min_score = float(t1.get("min_buy_score", 70) or 70)
        max_pos = float(t1.get("max_position_pct", 50) or 50)
        for sig in confirmed:
            if not sig.buy_ready or sig.t1_buy_score < min_score:
                sig.buy_ready = False
                sig.lifecycle_state = "T+1观察"
                sig.reasons.append("T+1买入不足")
                continue
            sig.lifecycle_state = "T+1买入候选"
            sig.suggested_position_size_pct = _clamp(max_pos, 0, 100)
            sig.stop_loss_pct = float((self.config.holding or {}).get("stop_loss_pct", -6.0) or -6.0)
            sig.take_profit_pct = float((self.config.holding or {}).get("take_profit_pct", 6.0) or 6.0)
            sig.reasons.append("T+1买入判断通过")
        return confirmed

    # ================= 6. T+1~T+3 管理 / 卖出 =================
    def evaluate_exits(self, holdings: List[Holding]) -> List[ExitDecision]:
        op = self.config.holding
        stop_loss = float(op.get("stop_loss_pct", -6.0) or -6.0)
        initial_stop = op.get("initial_stop_loss_pct")  # None=未启用
        if initial_stop is not None:
            initial_stop = float(initial_stop)
        take_profit = float(op.get("take_profit_pct", 6.0) or 6.0)
        trailing_trigger = float(op.get("trailing_trigger_pct", 4.0) or 4.0)
        trailing_distance = float(op.get("trailing_distance_pct", 5.0) or 5.0)
        fast_exit = int(op.get("fast_exit_after", 3) or 3)
        reduce_drawdown_pct = float(op.get("reduce_drawdown_pct", -3.0) or -3.0)  # 回撤过大先减仓
        reduce_after_days = int(op.get("reduce_after_days", 2) or 2)
        decisions: List[ExitDecision] = []
        for h in holdings:
            current = h.current_price
            if current is None:
                decisions.append(ExitDecision(symbol_code=h.symbol_code, symbol_name=h.symbol_name, action="hold", reason="价格数据缺失"))
                continue
            ret = (current - h.entry_price) / h.entry_price * 100.0 if h.entry_price else 0.0
            reasons: list[str] = []
            score = 0.0
            urgency = "normal"
            reduce_triggered = False
            # 初始止损位（例如分歧日最低点）无条件执行：跌破立即清仓，优先于 -6% 全局止损。
            # 优先使用持仓带上的 stop_loss_price（例如分歧日最低点）；否则可用 initial_stop_loss_pct（如 -3.0%）。
            _effective_stop_price = h.stop_loss_price
            if _effective_stop_price is None and initial_stop is not None and h.entry_price:
                _effective_stop_price = h.entry_price * (1 + initial_stop / 100.0)
            if _effective_stop_price is not None and current is not None and float(current) <= float(_effective_stop_price):
                score += 50
                urgency = "urgent"
                reasons.append(f"跌破初始止损位({_effective_stop_price:.2f})，无条件清仓")
            if ret <= stop_loss + 1e-9:
                score += 50
                urgency = "urgent"
                reasons.append(f"止损{stop_loss:.1f}%，当前{ret:.1f}%")
            if ret >= take_profit - 1e-9:
                score += 30
                reasons.append(f"止盈{take_profit:.1f}%，当前{ret:.1f}%")
            if h.highest_price and ret > trailing_trigger and (current / h.highest_price - 1.0) * 100.0 <= -trailing_distance:
                score += 40
                urgency = "urgent"
                reasons.append("移动止损触发")
            # T+1~T+3 中途信号转弱：先减仓而非直接清仓
            if h.holding_days >= reduce_after_days and ret <= reduce_drawdown_pct and score < 50:
                score += 20
                reduce_triggered = True
                urgency = "reduce"
                reasons.append(f"回撤过大({reduce_drawdown_pct:.1f}%)：先减仓一半观察")
            if h.holding_days > fast_exit:
                score += min(8, h.holding_days - fast_exit)
                reduce_triggered = True
                reasons.append(f"持有{h.holding_days}天超期")
            if reduce_triggered and score >= 50:
                action = "sell"
            elif reduce_triggered and score < 50:
                action = "reduce"
            elif score >= 50:
                action = "sell"
            else:
                action = "hold"
            decisions.append(ExitDecision(
                symbol_code=h.symbol_code,
                symbol_name=h.symbol_name,
                action=action,
                reason=" | ".join(reasons) if reasons else "继续持有",
                urgency=urgency,
                exit_score=round(score, 2),
                current_return_pct=round(ret, 2),
                stop_loss_triggered=bool((ret <= stop_loss + 1e-9) or (h.stop_loss_price is not None and current is not None and float(current) <= float(h.stop_loss_price))),
                take_profit_triggered=bool(ret >= take_profit - 1e-9),
                reduce_triggered=reduce_triggered,
                reasons=reasons,
            ))
        return decisions

    # ---------------- 导出辅助 ----------------
    def _write_result(self, result: Dict[str, Any], output_dir: str) -> None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        data = {
            "trade_date": result.get('trade_date'),
            'trigger_time': result.get('trigger_time'),
            'discovery': result.get('discovery').to_dict() if hasattr(result.get('discovery'), 'to_dict') else {},
            "watchlist": result.get("watchlist").to_dict() if hasattr(result.get("watchlist"), "to_dict") else {},
            "divergence_signals": [d.to_dict() for d in result.get("divergence_signals", [])],
            "confirmed_signals": [b.to_dict() for b in result.get("confirmed_signals", [])],
            "buy_signals": [b.to_dict() for b in result.get("buy_signals", [])],
            "state_signals": [b.to_dict() for b in result.get("state_signals", [])],
            "exit_decisions": [e.to_dict() for e in result.get("exit_decisions", [])],
        }
        (out / "result.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
