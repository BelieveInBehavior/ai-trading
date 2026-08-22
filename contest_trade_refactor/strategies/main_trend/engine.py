"""Main Trend Following Engine - 主升浪趋势跟踪系统（MTF）独立策略引擎。

对齐最终落地架构：
  Layer 0 DataQuality（硬过滤）
  -> Layer 1 MarketRegime（A/B/C/D）
  -> Layer 2 TrendState（S0~S5，S1/S2/S3 才可新增候选）
  -> Layer 3 TrendQuality（A/B/C，不做“总分”，只做仓位质量乘数）
  -> Layer 4 SectorState（Ex-Self 板块与广度）
  -> Layer 5 CatalystState（LLM 结构化 -> Engine 确定性 Gate）
  -> T+1 ExecutionState（Gap/Auction/Index/Sector/VWAP/OrderFlow）
  -> Layer 6 RiskState（风险预算决定买多少）
  -> Layer 7 持仓状态机（HOLD/ADD/DECAY/REDUCE/EXIT + MA20/ATR 双轨退出）

本策略完全独立，不依赖旧 momentum/swing / Research Agent 链路。
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
from utils.sector_enrichment import build_sector_snapshot, build_sector_snapshot_from_factor_store, enrich_factor_with_sector

from strategies.main_trend.schemas import (
    BuySignal,
    CatalystState,
    DataQualityState,
    ExitDecision,
    GateResult,
    Holding,
    MarketRegimeState,
    MTFCandidate,
    MTFDiscovery,
    PositionState,
    RiskState,
    SectorState,
    TrendQuality,
    TrendState,
)

try:
    _BASE_DIR = Path(__file__).resolve().parent
except Exception:
    _BASE_DIR = Path("strategies/main_trend")


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
        result = int(float(value))
        return result
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


def _fmt_pct(value: Optional[float], digits: int = 2) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}%"


def _enrich_residual_rs(factor: Dict[str, Any]) -> Dict[str, Any]:
    """在 factor 上补全残差 RS 原始因子（金融口径）。

    - vs Index：优先使用 true OLS residual（technical factor 里已基于日收益回归 alpha+beta*bench+eps 算好）。
      若没有（如外部注入 factor），退回简单超额收益，并标记为 excess 而不是 residual。
    - vs Sector：当前没有板块日线序列，无法做时间序列回归；只输出超额收益，并显式命名为
      excess_rs_vs_sector_* 以避免名不副实。
    """
    if not factor:
        return factor

    # ---- vs Index：真正 OLS 残差优先 ----
    resid_index_20 = _num(factor.get("residual_rs_vs_index_20d"))
    if resid_index_20 is None:
        stock20 = _num(factor.get("stock_return_20d_pct"))
        bench20 = _num(factor.get("benchmark_return_20d_pct"))
        if stock20 is not None and bench20 is not None:
            factor["excess_rs_vs_index_20d"] = round(stock20 - bench20, 4)
            factor["residual_rs_vs_index_20d"] = round(stock20 - bench20, 4)  # 兼容降级
    resid_index_60 = _num(factor.get("residual_rs_vs_index_60d"))
    if resid_index_60 is None:
        stock60 = _num(factor.get("stock_return_60d_pct"))
        bench60 = _num(factor.get("benchmark_return_60d_pct"))
        if stock60 is not None and bench60 is not None:
            factor["excess_rs_vs_index_60d"] = round(stock60 - bench60, 4)
            factor["residual_rs_vs_index_60d"] = round(stock60 - bench60, 4)  # 兼容降级

    # ---- vs Sector：优先使用 sector enrichment 里算出 OLS 残差；缺失时输出超额并命名清楚 ----
    if _num(factor.get("residual_rs_vs_sector_20d")) is not None:
        pass
    elif _num(factor.get("residual_rs_vs_sector_60d")) is not None:
        factor["residual_rs_vs_sector_20d"] = factor.get("residual_rs_vs_sector_60d")
    for lookback in (1, 3, 5, 10):
        stock_col = "change_pct" if lookback == 1 else f"ret_{lookback}d_pct"
        sector_col = f"sector_{lookback}d_return"
        stock_v = _num(factor.get(stock_col))
        sector_v = _num(factor.get(sector_col))
        if stock_v is not None and sector_v is not None:
            factor[f"excess_rs_vs_sector_{lookback}d"] = round(stock_v - sector_v, 4)

    # 兼容字段（尽量用真正残差，缺则用超额）
    factor["residual_rs_vs_index"] = factor.get("residual_rs_vs_index_20d")
    factor["residual_rs_vs_sector"] = (
        factor.get("residual_rs_vs_sector_20d")
        or factor.get("residual_rs_vs_sector_60d")
        or factor.get("excess_rs_vs_sector_5d")
    )
    return factor


def _is_limit_pct(symbol_code: str, change_pct: Optional[float]) -> bool:
    if change_pct is None:
        return False
    code = "".join(ch for ch in str(symbol_code or "") if ch.isdigit())
    if code.startswith(("300", "301", "688", "689")):
        return bool(change_pct >= 19.0)
    return bool(change_pct >= 9.0)


def _is_limit_up_change(symbol_code: str, change_pct: Optional[float]) -> bool:
    return _is_limit_pct(symbol_code, change_pct)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
@dataclass
class MainTrendConfig:
    id: str = "main_trend"
    universe: Dict[str, Any] = field(default_factory=dict)
    market: Dict[str, Any] = field(default_factory=dict)
    trend: Dict[str, Any] = field(default_factory=dict)
    quality: Dict[str, Any] = field(default_factory=dict)
    sector: Dict[str, Any] = field(default_factory=dict)
    catalyst: Dict[str, Any] = field(default_factory=dict)
    execution: Dict[str, Any] = field(default_factory=dict)
    risk: Dict[str, Any] = field(default_factory=dict)
    holding: Dict[str, Any] = field(default_factory=dict)
    backtest: Dict[str, Any] = field(default_factory=dict)
    benchmark_symbol: str = "sh000300"
    quantitative_concurrency: int = 4

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "MainTrendConfig":
        return cls(
            id=str(cfg.get("id") or "main_trend"),
            universe=dict(cfg.get("universe") or {}),
            market=dict(cfg.get("market") or {}),
            trend=dict(cfg.get("trend") or {}),
            quality=dict(cfg.get("quality") or {}),
            sector=dict(cfg.get("sector") or {}),
            catalyst=dict(cfg.get("catalyst") or {}),
            execution=dict(cfg.get("execution") or {}),
            risk=dict(cfg.get("risk") or {}),
            holding=dict(cfg.get("holding") or {}),
            backtest=dict(cfg.get("backtest") or {}),
            benchmark_symbol=str(cfg.get("benchmark_symbol") or cfg.get("benchmark") or "sh000300"),
            quantitative_concurrency=int(cfg.get("quantitative_screen_concurrency", 4) or 4),
        )

    @classmethod
    def from_yaml(cls) -> "MainTrendConfig":
        import yaml
        with open(_BASE_DIR / "strategy.yaml", "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------
class MainTrendEngine:
    def __init__(self, config: "MainTrendConfig" | None = None):
        self.config = config or MainTrendConfig.from_yaml()

    # ================= 主入口 =================
    async def run_day(
        self,
        trigger_time: str,
        watchlist: Optional[List[Any]] = None,
        holdings: Optional[List[Holding]] = None,
        output_dir: Optional[str] = None,
        max_symbols: int = 0,
    ) -> Dict[str, Any]:
        trade_date = get_latest_completed_trading_date(trigger_time)
        discovery = await self.discover(trigger_time, max_symbols=max_symbols)
        # 合并历史候选/观察池：这里可简化，保留当日候选即可。
        eligible = discovery.eligible
        buy_signals = self.build_buy_signals(eligible, trade_date)
        exits = self.evaluate_exits(holdings or [])
        result = {
            "trade_date": trade_date,
            "trigger_time": trigger_time,
            "discovery": discovery.to_dict() if hasattr(discovery, "to_dict") else {},
            "buy_signals": [s.to_dict() for s in buy_signals],
            "candidate_pool_t1": [s.to_dict() for s in buy_signals],
            "exit_decisions": [e.to_dict() for e in exits],
        }
        if output_dir:
            self._write_result(result, output_dir)
        return result

    async def discover(self, trigger_time: str, max_symbols: int = 0) -> MTFDiscovery:
        trade_date = get_latest_completed_trading_date(trigger_time)
        start_date, end_date = get_trading_date_range(end_date=trade_date, count=260, include_end=True)
        universe = await asyncio.to_thread(self._load_universe, max_symbols)
        benchmark = await asyncio.to_thread(self._load_benchmark, self.config.benchmark_symbol, start_date, end_date)
        sector_snapshot = await asyncio.to_thread(self._build_sector_snapshot, trade_date)
        market = self.evaluate_market_regime(trade_date, sector_snapshot=sector_snapshot)

        sem = asyncio.Semaphore(max(1, int(self.config.quantitative_concurrency) or 4))
        candidates: List[MTFCandidate] = []
        errors: List[str] = []

        async def _score(row: Dict[str, Any], median_out: List[float]) -> None:
            async with sem:
                try:
                    # 单遍：先计算完整技术因子（同时拿到 median_amount_20d）
                    factor = self._factor_for_row(row, start_date, end_date, trade_date, benchmark)
                    med = _num(factor.get("median_amount_20d")) if factor else None
                    if med is not None and med > 0:
                        median_out.append(med)
                    if not factor:
                        return
                    cand = self._candidate_from_factor(
                        row, factor, trade_date, market, sector_snapshot
                    )
                    if cand:
                        candidates.append(cand)
                except Exception as exc:
                    errors.append(str(exc))

        total = len(universe)
        if not market.allow_new:
            context = (
                f"MarketRegime={market.regime} (score={market.score:.1f}); "
                + ("; ".join(market.reasons) if market.reasons else "数据不足")
                + " -> 不允许新仓"
            )
            return MTFDiscovery(
                trade_date=trade_date,
                all_candidates=[],
                eligible=[],
                universe_count=total,
                market_regime=market,
                context_string=context,
                scan_errors=errors,
            )

        liquidity_p20 = None
        all_median_amounts: List[float] = []

        batch_size = max(1, int(self.config.quantitative_concurrency) * 3)
        for offset in range(0, total, batch_size):
            batch = universe[offset: offset + batch_size]
            await asyncio.gather(*[_score(row, all_median_amounts) for row in batch])

        # 全市场横截面 P20（单遍扫描收集所有股票的 20D Median Turnover）
        if len(all_median_amounts) >= 10:
            all_median_amounts.sort()
            idx = max(0, int(round(len(all_median_amounts) * 0.20)) - 1)
            liquidity_p20 = all_median_amounts[idx]

        for c in candidates:
            self.apply_hard_filter(c, market, liquidity_p20)

        eligible = [c for c in candidates if c.eligible]
        context = f"主升浪扫描：universe={total}, candidates={len(candidates)}, eligible={len(eligible)}; errors={len(errors)}"
        return MTFDiscovery(
            trade_date=trade_date,
            all_candidates=candidates,
            eligible=eligible,
            universe_count=total,
            market_regime=market,
            context_string=context,
            scan_errors=errors,
        )

    # ================= 1. 数据 & 工具 =================
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
        rows = []
        for _, row in raw.iterrows():
            code = _normalize_code(row.get(code_col))
            if not code:
                continue
            name = str(row.get(name_col) if name_col else row.get(code_col)).strip()
            if not name or name.upper().find("ST") >= 0 or "退" in name:
                continue
            rec = {"symbol_code": code, "symbol_name": name, "amount": 0.0}
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

    def _build_sector_snapshot(self, trade_date: str) -> Dict[str, Dict[str, float]]:
        snapshot = {}
        try:
            snapshot.update(build_sector_snapshot_from_factor_store(trade_date=trade_date))
        except Exception:
            pass
        try:
            snapshot.update(build_sector_snapshot())
        except Exception:
            pass
        return snapshot

    def evaluate_market_regime(
        self,
        trade_date: str,
        index_data: Optional[pd.DataFrame] = None,
        market_context: Optional[Dict[str, Any]] = None,
        sector_snapshot: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> MarketRegimeState:
        """Layer 1 Market Regime：A/B/C/D 七维综合市场环境。

        七维输入：
          1. Index Trend       指数趋势（Close vs MA5 vs MA20）
          2. Index Momentum   指数动量（5日收益）
          3. Market Breadth   个股上涨广度（上涨家数占比）
          4. New High / New Low 创新高/创新低（net 新高-新低占全市场比例）
          5. Market Turnover  市场成交额变化
          6. Sector Breadth   板块广度（上涨板块占比）
          7. Market Volatility 市场波动（20日指数波动率；高波需结合方向不宜直接奖励）
        """
        context = dict(market_context or {})
        score = 0.0
        reasons: List[str] = []
        detail: Dict[str, Any] = {}

        # ---- 1. Index Trend (max +25 / -25)
        index_trend_score = 0.0
        if index_data is not None and not index_data.empty and "close" in index_data:
            closes = pd.to_numeric(index_data["close"], errors="coerce").dropna()
            if len(closes) >= 20:
                latest = float(closes.iloc[-1])
                ma5 = float(closes.tail(5).mean())
                ma20 = float(closes.tail(20).mean())
                if latest > ma5 > ma20:
                    index_trend_score += 22
                    reasons.append("指数位于5日/20日均线上方")
                elif latest < ma5 < ma20:
                    index_trend_score -= 22
                    reasons.append("指数位于5日/20日均线下方")
                elif latest > ma20:
                    index_trend_score += 8
                    reasons.append("指数站上20日线")
                else:
                    index_trend_score -= 8
                    reasons.append("指数位于20日线下方")
                detail["index_ma5"] = round(ma5, 4)
                detail["index_ma20"] = round(ma20, 4)
        score += index_trend_score
        detail["index_trend"] = round(index_trend_score, 2)

        # ---- 2. Index Momentum (5日收益, max +15)
        index_momentum_score = 0.0
        if index_data is not None and not index_data.empty and "close" in index_data:
            closes = pd.to_numeric(index_data["close"], errors="coerce").dropna()
            if len(closes) >= 6:
                latest = float(closes.iloc[-1])
                ret5 = (latest / float(closes.iloc[-6]) - 1.0) * 100.0
                if ret5 > 1.5:
                    index_momentum_score = 10
                    reasons.append(f"指数5日{ret5:.2f}%")
                elif ret5 < -1.5:
                    index_momentum_score = -10
                    reasons.append(f"指数5日{ret5:.2f}%")
                elif ret5 > 0:
                    index_momentum_score = 4
                else:
                    index_momentum_score = -4
                detail["index_momentum_5d"] = round(ret5, 3)
        score += index_momentum_score
        detail["index_momentum"] = round(index_momentum_score, 2)

        # ---- 3. Market Breadth - max +20
        breadth = _num(context.get("advance_ratio")) or _num(context.get("breadth_pct"))
        if breadth is None:
            breadth = _num(context.get("market_breadth_pct"))
        breadth_score = 0.0
        if breadth is not None:
            breadth_val = breadth / 100.0 if breadth > 1 else breadth
            breadth_score = (breadth_val - 0.5) * 40.0
            reasons.append(f"上涨家数占比{breadth_val * 100:.1f}%")
            detail["breadth_pct"] = round(breadth_val * 100.0, 1)
        score += breadth_score
        detail["breadth"] = round(breadth_score, 2)

        # ---- 4. New High / New Low - max +15
        nh_score = 0.0
        new_high = _num(context.get("new_high_count")) or _num(context.get("new_high_ratio"))
        new_low = _num(context.get("new_low_count")) or _num(context.get("new_low_ratio"))
        universe_count = _num(context.get("universe_count"))
        if new_high is not None or new_low is not None:
            # 若只给了 counts 且给 universe，则转成比例
            if new_high is not None and universe_count and new_high <= universe_count:
                new_high = new_high / universe_count
            if new_low is not None and universe_count and new_low <= universe_count:
                new_low = new_low / universe_count
            if new_high is not None and new_high > 1:
                new_high = new_high / 100.0
            if new_low is not None and new_low > 1:
                new_low = new_low / 100.0
            # 默认新低为0
            low_eff = 0.0 if new_low is None else new_low
            nh_score = ((new_high or 0.0) - low_eff) * 20.0
            reasons.append(f"新高{new_high or 0:.0%}/新低{low_eff:.0%}")
            detail["new_high_ratio"] = new_high if new_high is not None else 0.0
            detail["new_low_ratio"] = low_eff
        score += nh_score
        detail["new_high_low"] = round(nh_score, 2)

        # ---- 5. Market Turnover - max +10
        turnover_score = 0.0
        turnover = _num(context.get("market_turnover_change_pct"))
        trend = str(context.get("market_trend") or "neutral").lower()
        if turnover is not None:
            direction = 1.0 if trend == "up" else -1.0 if trend == "down" else 0.0
            turnover_score = max(-10.0, min(10.0, turnover * 0.5 * direction))
            reasons.append(f"成交额变化{turnover:+.1f}%")
            detail["turnover_change"] = round(turnover, 3)
        score += turnover_score
        detail["turnover"] = round(turnover_score, 2)

        # ---- 6. Sector Breadth - max +10
        sector_breadth_score = 0.0
        if sector_snapshot:
            sector_returns = [float(v.get("sector_1d_return") or 0.0) for v in sector_snapshot.values() if isinstance(v, dict)]
            if sector_returns:
                up_ratio = sum(1 for x in sector_returns if x > 0) / max(1, len(sector_returns))
                sector_breadth_score = (up_ratio - 0.5) * 20.0
                reasons.append(f"板块广度{up_ratio * 100:.0f}%上涨")
                detail["sector_breadth_pct"] = round(up_ratio * 100.0, 1)
        score += sector_breadth_score
        detail["sector_breadth"] = round(sector_breadth_score, 2)

        # ---- 7. Market Volatility - max +5
        vol_score = 0.0
        market_vol = _num(context.get("market_volatility_20d_pct"))
        if market_vol is None and index_data is not None and not index_data.empty and "close" in index_data:
            closes = pd.to_numeric(index_data["close"], errors="coerce").dropna()
            rets = closes.pct_change().dropna().tail(20)
            if len(rets) >= 10:
                market_vol = float(rets.std(ddof=0) * 100.0)
        if market_vol is not None:
            detail["market_volatility_20d_pct"] = round(market_vol, 3)
            # 波动不是天然风险：放量上升趋势中允许高波动，但持续高波且方向不明减分
            if market_vol <= 1.0:
                vol_score = 3
                reasons.append("波动较低")
            elif market_vol >= 3.0:
                vol_score = -3
                reasons.append("市场波动偏高")
        score += vol_score
        detail["volatility"] = round(vol_score, 2)

        # 额外风控：risk_off 减分
        risk_sentiment = str(context.get("risk_sentiment") or "neutral").lower()
        if risk_sentiment == "risk_on":
            score += 1.5
            reasons.append("风险偏好上升")
        elif risk_sentiment == "risk_off":
            score -= 1.5
            reasons.append("风险偏好下降")

        # 归一化到 0~100：七维输入已分配相对权重，1.1 系数让综合分能跨 A/B/C/D 阈值
        score_norm = _clamp(50 + score * 1.1)
        if score_norm >= 70:
            regime = "A"
        elif score_norm >= 55:
            regime = "B"
        elif score_norm >= 40:
            regime = "C"
        else:
            regime = "D"

        risk_mult = 1.0 if regime in ("A", "B") else (0.5 if regime == "C" else 0.0)
        allow = regime in ("A", "B", "C")
        detail["raw_score"] = round(score, 2)
        detail["regime"] = regime
        return MarketRegimeState(
            regime=regime,
            score=round(score_norm, 2),
            reasons=reasons,
            risk_multiplier=risk_mult,
            allow_new=allow,
            detail=detail,
        )

    def _factor_for_row(
        self,
        row: Dict[str, Any],
        start_date: str,
        end_date: str,
        trade_date: str,
        benchmark: pd.DataFrame,
    ) -> Optional[Dict[str, Any]]:
        symbol = str(row.get("symbol_code") or "")[:6]
        if not symbol:
            return None
        hist = get_stock_zh_a_hist(symbol, start_date, end_date, adjust="qfq", verbose=False)
        factor = compute_stock_technical_factor_from_history(
            hist_df=hist,
            symbol_code=symbol,
            symbol_name=str(row.get("symbol_name") or ""),
            trade_date=trade_date,
            relative_strength_benchmark=self.config.benchmark_symbol,
            benchmark_frame=benchmark,
        )
        return factor

    def _candidate_from_factor(
        self,
        row: Dict[str, Any],
        factor: Dict[str, Any],
        trade_date: str,
        market: MarketRegimeState,
        sector_snapshot: Dict[str, Dict[str, float]],
    ) -> Optional[MTFCandidate]:
        factor = enrich_factor_with_sector(factor, sector_snapshot)
        factor = _enrich_residual_rs(factor) if factor else factor
        quality = self.assess_data_quality(factor)
        if not quality.valid:
            return None
        trend = self.assess_trend_state(factor)
        if not trend.tradeable:
            return None
        trend_quality = self.assess_trend_quality(factor, trend, market)
        sector = self.assess_sector_state(factor, trade_date, market, sector_snapshot)
        catalyst = self.assess_catalyst(factor)
        cand = MTFCandidate(
            symbol_code=str(factor.get("symbol_code") or _normalize_code(row.get("symbol_code"))),
            symbol_name=str(factor.get("symbol_name") or row.get("symbol_name") or ""),
            trade_date=trade_date,
            trend_state=trend.state,
            trend_quality=trend_quality.grade,
            market_regime=market.regime,
            sector_name=sector.sector_name,
            catalyst_score=round(catalyst.score, 2),
            risk_multiplier=market.risk_multiplier,
            eligible=True,
            technical_factor=factor,
            market_regime_state=market,
            trend_state_info=trend,
            quality_info=trend_quality,
            sector_info=sector,
            catalyst_info=catalyst,
            reasons=list(trend.reasons) + list(trend_quality.reasons) + list(sector.reasons) + list(catalyst.reasons),
        )
        cand.entry_score = self._candidate_entry_score(cand)
        if not sector.passed:
            cand.eligible = False
            cand.reasons.append(f"Sector未通过:{sector.grade}")
        return cand

    # ================= 2. 主升浪识别 =================
    def _discover_one(
        self,
        row: Dict[str, Any],
        start_date: str,
        end_date: str,
        trade_date: str,
        benchmark: pd.DataFrame,
        sector_snapshot: Dict[str, Dict[str, float]],
        market: MarketRegimeState,
    ) -> Optional[MTFCandidate]:
        symbol = str(row.get("symbol_code") or "")[:6]
        if not symbol:
            return None
        hist = get_stock_zh_a_hist(symbol, start_date, end_date, adjust="qfq", verbose=False)
        factor = compute_stock_technical_factor_from_history(
            hist_df=hist,
            symbol_code=symbol,
            symbol_name=str(row.get("symbol_name") or ""),
            trade_date=trade_date,
            relative_strength_benchmark=self.config.benchmark_symbol,
            benchmark_frame=benchmark,
        )
        if not factor:
            return None
        # 板块富化（常规实现：先看快照，如缺失使用默认放行）
        factor = enrich_factor_with_sector(factor, sector_snapshot)
        factor = _enrich_residual_rs(factor) if factor else factor
        quality = self.assess_data_quality(factor)
        if not quality.valid:
            return None

        trend = self.assess_trend_state(factor)
        if not trend.tradeable:
            return None

        trend_quality = self.assess_trend_quality(factor, trend, market)
        sector = self.assess_sector_state(factor, trade_date, market, sector_snapshot)
        catalyst = self.assess_catalyst(factor)

        cand = MTFCandidate(
            symbol_code=str(factor.get("symbol_code") or _normalize_code(row.get("symbol_code"))),
            symbol_name=str(factor.get("symbol_name") or row.get("symbol_name") or ""),
            trade_date=trade_date,
            trend_state=trend.state,
            trend_quality=trend_quality.grade,
            market_regime=market.regime,
            sector_name=sector.sector_name,
            catalyst_score=round(catalyst.score, 2),
            risk_multiplier=market.risk_multiplier,
            eligible=True,
            technical_factor=factor,
            market_regime_state=market,
            trend_state_info=trend,
            quality_info=trend_quality,
            sector_info=sector,
            catalyst_info=catalyst,
            reasons=list(trend.reasons) + list(trend_quality.reasons) + list(sector.reasons) + list(catalyst.reasons),
        )
        cand.entry_score = self._candidate_entry_score(cand)
        if not sector.passed:
            cand.eligible = False
            cand.reasons.append(f"Sector未通过:{sector.grade}")
        return cand

    def assess_data_quality(self, factor: Dict[str, Any]) -> DataQualityState:
        reasons = []
        detail = {}
        valid = _bool(factor.get("data_quality_valid", True))
        status = str(factor.get("data_quality_status") or "")
        if not valid or (status and status != "ok"):
            reasons.append("data_quality_invalid")
        close = _num(factor.get("close"))
        vol = _num(factor.get("volume_ratio"))
        amount = _num(factor.get("amount_ratio"))
        if close is None or close <= 0:
            valid = False
            reasons.append("price_invalid")
        if vol is None or vol <= 0:
            valid = False
            reasons.append("volume_missing")
        if (amount or 0) <= 0:
            reasons.append("amount_missing")
        detail["close"] = close
        detail["volume_ratio"] = vol
        detail["amount_ratio"] = amount
        # 流动性硬过滤：成交额缺失不算 fail，若存在且过小则 fail
        amount_abs = _num(factor.get("amount"))
        if amount_abs is not None and amount_abs > 0 and amount_abs < 5_000_000:
            valid = False
            reasons.append("liquidity_below_min")
        return DataQualityState(valid=valid, reasons=reasons, detail=detail)

    def apply_hard_filter(self, cand: MTFCandidate, market: MarketRegimeState, liquidity_p20: Optional[float] = None) -> bool:
        """最终 8 条 T 日硬过滤。
        1) MarketRegime != D 已由 discover 闸门保证
        2) 非ST/非停牌 已在 _load_universe 过滤 + 此处检查 name/status
        3) trading_days >= 120
        4) 流动性 median_amount_20d >= P20
        5) close > ma20
        6) ma20 > ma60
        7) ma60_5d_slope_pct > 0
        8) trend_state ∈ S1/S2/S3
        """
        f = cand.technical_factor or {}
        reasons = list(cand.reasons)
        ok = True
        # 上市时间
        cfg = self.config.trend or {}
        min_days = int(cfg.get("min_trading_days", 120) or 120)
        trading_days = _int(f.get("trading_days"), 0)
        if trading_days < min_days:
            ok = False
            reasons.append(f"trading_days<{min_days}:{trading_days}")
        # Close > MA20: use ma20_deviation_pct > 0 (close/ma20 -1)
        ma20_dev = _num(f.get("ma20_deviation_pct"))
        if ma20_dev is None or ma20_dev <= 0:
            ok = False
            reasons.append(f"close<=ma20:dev={ma20_dev}")
        # MA20 > MA60
        ma20_ge_ma60 = f.get("ma20_ge_ma60")
        if ma20_ge_ma60 is not True:
            ok = False
            reasons.append(f"ma20<=ma60:{ma20_ge_ma60}")
        # MA60 normalized 5-day LR slope > 0
        slope = _num(f.get("ma60_5d_slope_pct"))
        if slope is None or slope <= 0:
            ok = False
            reasons.append(f"ma60_slope<=0:{slope}")
        # Trend state
        if cand.trend_state not in ("S1", "S2", "S3"):
            ok = False
            reasons.append(f"trend_state:{cand.trend_state}")
        # Liquidity P20
        if liquidity_p20 is not None:
            med = _num(f.get("median_amount_20d"))
            if med is None or med < liquidity_p20:
                ok = False
                reasons.append(f"liquidity<{liquidity_p20}:{med}")
        cand.reasons = [r for r in reasons if r not in cand.reasons] + [r for r in reasons if r in cand.reasons]
        cand.reasons = list(dict.fromkeys(cand.reasons))
        cand.eligible = ok
        return ok

    def assess_trend_state(self, factor: Dict[str, Any]) -> TrendState:
        """S0~S5 主升浪状态机。S1/S2/S3 才允许新增候选。

        设计要点：
          - S1：平台突破 + 量扩张 + 均线转强 + 站上关键成本区 + RS增强。
            筹码/成本仅作辅助加分，不硬条件（不同数据源筹码算法不稳定）。
          - S2：MA5>MA20>MA60 多头、创新高、RS 强、量价健康、板块强。
          - S3：上涨→横盘→缩量→MA20 继续上行→重新突破。不因未创新高判死。
          - S4：主升末端，不预测顶；只记录趋势质量下降维度（创新高减速/RS回调/ATR异常/量异常/板块转弱）。
          - S5：趋势破坏硬退出 Close<MA20+RSI 弱；ATR trailing stop/次日无法站回在持仓状态机处理。
        """
        cfg = self.config.trend or {}
        score = 50.0
        reasons = []
        close = _num(factor.get("close"))
        ma20_dev = _num(factor.get("ma20_deviation_pct"))  # close/ma20-1
        ma20 = None
        if close is not None and close > 0 and ma20_dev is not None:
            ma20 = close / (1 + ma20_dev / 100.0)
        ma20_ge_ma60 = factor.get("ma20_ge_ma60")
        ma5_slope = _num(factor.get("ma5_slope_pct"))
        breakout20 = _bool(factor.get("breakout_20d"))
        breakout60 = _bool(factor.get("breakout_60d"))
        close_above_ma5 = _bool(factor.get("close_above_ma5"))
        volume_ratio = _num(factor.get("volume_ratio"))
        ret5 = _num(factor.get("ret_5d_pct"))
        ret20 = _num(factor.get("ret_20d_pct"))
        rsi = _num(factor.get("rsi"))
        atr_pct = _num(factor.get("atr_pct"))
        close_vs_high20 = _num(factor.get("close_vs_20d_high_pct"))
        weekly = _num(factor.get("weekly_trend_score"))
        rs = _num(factor.get("relative_strength_score"))
        rs20 = _num(factor.get("relative_strength_20d_pct"))
        rs60 = _num(factor.get("relative_strength_60d_pct"))
        new_high = close_vs_high20 is not None and close_vs_high20 >= -0.5
        detail = {}

        # 关键成本区：不把筹码分布当绝对真值，用 MA20/VWAP20 作为成本代理，且只辅助加分。
        vwap20 = _num(factor.get("vwap_20")) or _num(factor.get("vwap"))
        cost_proxy = ma20 if ma20 is not None else vwap20
        cost_strength: Optional[float] = None
        if cost_proxy and cost_proxy > 0 and close is not None and close > 0:
            cost_strength = (close / cost_proxy - 1.0) * 100.0
        cost_ok = bool(
            cost_strength is not None
            and cost_strength > float(cfg.get("min_s1_cost_strength", 0.0) or 0.0)
        )
        use_cost_aux = bool(cfg.get("s1_cost_strength_aux", True))

        min_s1_vol = float(cfg.get("min_s1_breakout_volume", 1.1) or 1.1)
        min_s1_rs = float(cfg.get("min_s1_rs", 55) or 55)
        min_s2_rs = float(cfg.get("min_s2_rs", 58) or 58)
        min_s2_vol = float(cfg.get("min_s2_volume", 0.9) or 0.9)
        s3_max_vol = float(cfg.get("s3_max_volume_for_consolidation", 1.0) or 1.0)

        # S1：平台突破 + 量扩张 + 均线转强 + RS增强（筹码只辅助，不硬条件）
        is_s1 = bool(
            breakout20
            and (volume_ratio or 0) >= min_s1_vol
            and (ma5_slope or 0) >= 0
            and (rs is None or rs >= min_s1_rs)
        )
        s1_cost_hit = bool(use_cost_aux and cost_ok)

        # S2：创新高 + RS 强 + 量价健康 + MA 多头结构（MA5>MA20>MA60）
        # 优先直接使用已计算的绝对 MA 比较字段；缺失时退化为旧近似（close>MA5 + slope>=0 + MA20>MA60）。
        ma5_gt_ma20 = factor.get("ma5_gt_ma20")
        if ma5_gt_ma20 is None:
            ma5_gt = bool(close_above_ma5 and (ma5_slope is None or ma5_slope >= 0))
        else:
            ma5_gt = bool(ma5_gt_ma20 is True)
        if ma20_ge_ma60 is None:
            ma_ok = bool(ma20_dev is not None and ma20_dev > 0)
        else:
            ma_ok = bool(ma20_dev is not None and ma20_dev > 0 and ma20_ge_ma60 is True)
        is_s2_general = bool(
            new_high
            and (rs or 50) >= min_s2_rs
            and (volume_ratio or 1) >= min_s2_vol
            and ma_ok
            and ma5_gt
        )

        # S3：MA20 上行 + 缩量后重新突破；不因“未创新高”直接判死
        is_s3 = bool(
            (ma20_dev is not None and ma20_dev >= 0)
            and (volume_ratio or 0) <= s3_max_vol
            and (breakout20 or breakout60)
        )

        # ATR 与位置联合判断（原则⑧）
        atr_quality_ok = True
        if atr_pct is not None and (volume_ratio or 0) >= 1.5 and not new_high:
            atr_quality_ok = False
            score -= 18
            detail["atr_quality"] = "不创新高+ATR放大 -> Trend Decay"
        elif atr_pct is not None and new_high:
            score += 8
            detail["atr_quality"] = "创新高+ATR升 -> 上涨加速"

        # --- 优先判断坏状态 ---
        below_ma20 = ma20_dev is not None and ma20_dev < 0
        s5_rsi_th = float(cfg.get("s5_break_rsi_below", 45) or 45)
        breakdown = bool(below_ma20 and (rsi if rsi is not None else 50) < s5_rsi_th)
        if breakdown:
            detail["break_reason"] = "close_below_ma20_rsi_weak"
            return TrendState(
                state="S5", score=max(0.0, round(score, 2)),
                reasons=["趋势破坏: 跌破MA20+RS弱"], tradeable=False,
                action_hint="EXIT", atr_quality_ok=atr_quality_ok, detail=detail,
            )

        # S4 主升末端：多维度趋势质量下降，不预测顶
        s4_min_hits = int(cfg.get("s4_min_quality_hits", 2) or 2)
        s4_hits = []
        s4_min_rsi = float(cfg.get("s4_min_rsi", 70) or 70)
        s4_min_vol = float(cfg.get("s4_min_volume_surge", 1.5) or 1.5)
        s4_min_ret20 = float(cfg.get("s4_min_ret20", 30) or 30)
        if cfg.get("s4_enable_rs_decline", True) and rs20 is not None and rs60 is not None:
            if rs20 < rs60:
                s4_hits.append("RS下降")
        if cfg.get("s4_enable_volume_anomaly", True) and (volume_ratio or 0) >= s4_min_vol and not new_high:
            s4_hits.append("放量不创新高")
        if (rsi or 50) >= s4_min_rsi and (volume_ratio or 0) >= s4_min_vol and not new_high and (ret20 or 0) > s4_min_ret20:
            s4_hits.append("RSI超买+放量+高涨幅")
        if cfg.get("s4_enable_sector_weak", True):
            sector_1d = _num(factor.get("sector_1d_return"))
            sector_rank = _num(factor.get("sector_rank"))
            if sector_1d is not None and sector_1d < -1.0:
                s4_hits.append("板块转弱")
            elif sector_rank is not None and sector_rank >= 30:
                s4_hits.append("板块排名走弱")
        # S4 只在确已走出主升阶段后才有意义：至少 MA20 上方且有一定涨幅，避免把普通弱势股标成“末端”
        s4_experienced_trend = bool(
            (ma20_dev is not None and ma20_dev >= 0)
            and (ret20 is not None and ret20 > 5)  # 近20日已经有正收益，近似走过主升
        )
        if len(s4_hits) >= s4_min_hits and s4_experienced_trend:
            detail["s4_hits"] = list(s4_hits)
            return TrendState(
                state="S4", score=max(5.0, round(score, 2)),
                reasons=["主升末端: " + "、".join(s4_hits)],
                tradeable=False, action_hint="不新增",
                atr_quality_ok=atr_quality_ok, detail=detail,
            )

        if not (is_s1 or is_s2_general or is_s3):
            reasons.append("S0: 尚未形成有效主升浪")
            return TrendState(
                state="S0", score=round(max(score, 5.0), 2), reasons=reasons,
                tradeable=False, action_hint="PASS",
                atr_quality_ok=atr_quality_ok, detail=detail,
            )

        # --- 有效主升状态 ---
        if is_s2_general:
            score += 45
            reasons.append("S2加速：创新高+RS强+量价健康")
        elif is_s1:
            score += 30
            reasons.append("S1启动：突破+量+均线转强")
            if s1_cost_hit:
                score += 5
                reasons.append("站上关键成本区(辅助)")
            if cost_strength is not None:
                detail["cost_strength_pct"] = round(cost_strength, 2)
        elif is_s3:
            score += 32
            reasons.append("S3中继：MA20上行+回调后重新突破")

        score += (ma5_slope or 0) if ma5_slope is not None else 0
        if close_above_ma5:
            score += 5
        if (rs or 50) >= 60:
            score += 10
            reasons.append(f"RS={rs:.1f}")
        if (volume_ratio or 0) >= 1.2:
            score += 8
            reasons.append(f"放量{volume_ratio:.2f}")
        if ret5 is not None and 0 <= ret5 <= 30:
            score += 6
        if weekly and weekly >= 60:
            score += 5
        score = _clamp(score)
        # 状态由“形态条件”优先决定，而不是只按总分重排：
        # S2 加速 > S3 中继 > S1 启动。
        if is_s2_general:
            state = "S2"
            action = "BUY/ADD 主升浪"
        elif is_s3:
            state = "S3"
            action = "候选池"
        elif is_s1:
            state = "S1"
            action = "候选池"
        else:
            # 防御性兜底，正常不会走到这里
            state = "S0"
            action = "PASS"
            return TrendState(
                state=state, score=round(score, 2), reasons=reasons, tradeable=False,
                action_hint=action, atr_quality_ok=atr_quality_ok, detail=detail,
            )
        return TrendState(
            state=state, score=round(score, 2), reasons=reasons, tradeable=True,
            action_hint=action, atr_quality_ok=atr_quality_ok, detail=detail,
        )

    # ================= 3. 趋势质量（因子族去重，不重复计权） =================
    def assess_trend_quality(self, factor: Dict[str, Any], trend: TrendState, market: MarketRegimeState) -> TrendQuality:
        cfg = self.config.quality or {}
        # 因子族去重：每个族内取代表性指标，不简单叠同源因子。
        trend_struct = 0.5 * (0 if (factor.get("ma20_deviation_pct") is None) else 1)
        breakout = 1.0 if _bool(factor.get("breakout_20d")) or _bool(factor.get("breakout_60d")) else 0.0
        momentum = 0.0
        ret5 = _num(factor.get("ret_5d_pct"))
        ret10 = _num(factor.get("ret_10d_pct"))
        if ret5 is not None:
            momentum += 0.6 if 1 <= ret5 <= 25 else 0.2
        if ret10 is not None:
            momentum += 0.4 if ret10 > 0 else 0.0
        rs = _num(factor.get("relative_strength_score"))
        rs_val = (rs / 100.0) if rs is not None else 0.5
        volume = 0.0
        vol = _num(factor.get("volume_ratio"))
        if vol is not None:
            volume = 1.0 if 1.0 <= vol <= 3.0 else 0.4 if vol > 0.8 else 0.2
        volatility = 0.0
        atr_pct = _num(factor.get("atr_pct"))
        if atr_pct is not None:
            volatility = 1.0 if 2 <= atr_pct <= 12 else 0.5
        structure = 1.0 if _bool(factor.get("hh_hl_strict")) else 0.4

        family = {
            "trend_structure": round(trend_struct, 3),
            "breakout_quality": round(breakout, 3),
            "momentum_quality": round(min(1.0, momentum), 3),
            "relative_strength": round(rs_val, 3),
            "volume_price": round(volume, 3),
            "volatility_state": round(volatility, 3),
            "structure": round(structure, 3),
        }
        # 残差RS：优先使用 _enrich_residual_rs() 已算好的原始因子字段；缺失时兜底计算
        residual_index = (
            _num(factor.get("residual_rs_vs_index_20d"))
            or _num(factor.get("residual_rs_vs_index"))
            or (
                (ret20 - bench) if (ret20 := _num(factor.get("ret_20d_pct"))) is not None
                and (bench := _num(factor.get("benchmark_return_20d_pct"))) is not None else None
            )
        )
        # 板块有日线时优先 OLS 真残差，否则退化为超额
        residual_sector = (
            _num(factor.get("residual_rs_vs_sector_20d"))
            or _num(factor.get("residual_rs_vs_sector_60d"))
            or _num(factor.get("residual_rs_vs_sector"))
            or _num(factor.get("excess_rs_vs_sector_5d"))
            or _num(factor.get("excess_rs_vs_sector_3d"))
            or (
                (ret5 - sec1d) if ret5 is not None
                and (sec1d := _num(factor.get("sector_1d_return"))) is not None else None
            )
        )

        score = 45.0
        score += (trend_struct * 12) + (breakout * 12) + (rs_val * 10) + (momentum * 10) + (volume * 8) + (volatility * 6) + (structure * 5)
        # Risk multiplier: A/B/C
        if score >= 65:
            grade = "A"
            mult = 1.0
        elif score >= 45:
            grade = "B"
            mult = 0.75
        else:
            grade = "C"
            mult = 0.5
        reasons = [
            f"趋势结构{family['trend_structure']:.1f}/突破{family['breakout_quality']:.1f}/动量{family['momentum_quality']:.1f}/RS{family['relative_strength']:.1f}",
            f"量价{family['volume_price']:.1f}/波动{family['volatility_state']:.1f}/结构{family['structure']:.1f}",
            f"TrendQuality={grade}",
        ]
        if market.regime == "C":
            mult *= 0.5
            reasons.append("Regime=C, 质量乘数再降半")
        return TrendQuality(grade=grade, score=round(score, 2), family=family, reasons=reasons, multiplier=mult, residual_rs_vs_index=residual_index, residual_rs_vs_sector=residual_sector)

    # ================= 4. 板块（Ex-Self ≈ 板块自身 + 个股跑赢板块） =================
    def assess_sector_state(
        self,
        factor: Dict[str, Any],
        trade_date: str,
        market: MarketRegimeState,
        sector_snapshot: Dict[str, Dict[str, float]],
    ) -> SectorState:
        cfg = self.config.sector or {}
        sector_name = str(factor.get("sector_name") or factor.get("industry_name") or "").strip()
        sector_1d = _num(factor.get("sector_1d_return"))
        sector_rank = _num(factor.get("sector_rank"))
        stock_vs = _num(factor.get("stock_vs_sector_strength"))
        stock_ret = _num(factor.get("change_pct"))
        # 若无板块强度数据，默认不因缺失而杀掉（与既有策略一致）
        if not sector_name or sector_1d is None:
            # 如果连板块名都没有，则板块质量只作低分但不严格拒绝
            return SectorState(sector_name=sector_name, sector_strength_pct=0.0, score=50.0, grade="B", passed=True, reasons=["板块数据缺失，默认放行"])
        # 计算 Ex-Self 近似：如果板块涨幅高但个股涨幅更高说明板块没纯靠个股
        ex_self_ok = True
        if stock_ret is not None and sector_1d is not None:
            # 若板块大涨 3% 而个股贡献 > 板块 (个股涨幅远超板块涨幅) => 视为 Ex-Self 被腐蚀
            if sector_1d >= 3.0 and stock_ret > sector_1d + 5:
                score_ex = 40.0
                ex_self = False
                ex_self_detail = {"note": "个股涨幅远超板块，Ex-Self可能被腐蚀", "stock_ret": stock_ret, "sector_1d": sector_1d}
            else:
                score_ex = 55.0
                ex_self = True
                ex_self_detail = {"stock_ret": stock_ret, "sector_1d": sector_1d, "ex_self": True}
        else:
            score_ex = 50.0
            ex_self = True
            ex_self_detail = {"no_data": True}
        score = 50.0
        if sector_1d >= 2:
            score += 15
        elif sector_1d >= 0:
            score += 8
        elif sector_1d < -2:
            score -= 15
        if sector_rank is not None and sector_rank <= 10:
            score += 12
        elif sector_rank is not None and sector_rank <= 30:
            score += 6
        if stock_vs is not None and stock_vs >= 0:
            score += 8
        score = _clamp(score)
        passed = bool(score >= float(cfg.get("min_sector_score", 45) or 45))
        grade = "A" if score >= 65 else "B" if score >= 45 else "C"
        reasons = [f"板块涨幅{sector_1d:.2f}%"]
        if sector_rank:
            reasons.append(f"板块排名{sector_rank}")
        if not ex_self:
            reasons.append("Ex-Self不足")
        return SectorState(
            sector_name=sector_name,
            sector_strength_pct=round(sector_1d, 3),
            breadth_pct=_num(factor.get("sector_breadth_score")),
            rank=sector_rank,
            ex_self=ex_self,
            ex_self_detail=ex_self_detail,
            score=round(score, 2),
            grade=grade,
            passed=passed,
            reasons=reasons,
        )

    # ================= 5. 催化（LLM 只输出结构化；这里用 factor 里可用的结构化字段） =================
    def assess_catalyst(self, factor: Dict[str, Any]) -> CatalystState:
        cfg = self.config.catalyst or {}
        catalyst = factor.get("catalyst") or {}
        freshness = _num(catalyst.get("freshness"), 0.0) or 0.0
        company_specific = _bool(catalyst.get("company_specific"))
        event_type = str(catalyst.get("event_type") or "")
        level = str(catalyst.get("event_level") or "")
        reaction = str(catalyst.get("price_reaction") or "")
        has_event = bool(event_type or level)
        score = 0.0
        reasons = []
        if has_event:
            score += 25
            reasons.append(f"事件:{event_type or level}")
            if reaction == "positive":
                score += 30
                reasons.append("价格正面反应")
            elif reaction == "negative":
                score -= 25
                reasons.append("价格负面反应")
            if company_specific:
                score += 20
                reasons.append("公司特异性")
            score += min(25.0, freshness * 25.0)
            reasons.append(f"新鲜度{freshness * 100:.0f}%")
        # 若无催化，默认中性 50 分，不要求必须有催化（催化是增强不是准入）。
        score = 50.0 if not has_event else _clamp(score)
        return CatalystState(has_event=has_event, event_type=event_type, event_level=level, freshness=freshness, company_specific=company_specific, price_reaction=reaction, score=round(score, 2), reasons=reasons)

    def _candidate_entry_score(self, cand: MTFCandidate) -> float:
        score = 50.0
        if cand.quality_info:
            score += (cand.quality_info.score - 50) * 0.8
        if cand.sector_info:
            score += (cand.sector_info.score - 50) * 0.5
        if cand.catalyst_info:
            score += (cand.catalyst_info.score - 50) * 0.5
        if cand.trend_state == "S2":
            score += 5
        return round(_clamp(score), 2)

    # ================= 6. T+1 执行 & 风险预算 =================
    def build_buy_signals(self, eligible: List[MTFCandidate], trade_date: str) -> List[BuySignal]:
        cfg = self.config.execution or {}
        out = []
        for cand in eligible:
            factor = cand.technical_factor or {}
            # T 日只产生候选；T+1 执行打分属于以后才可知的确认信息，这里只做运行态打分。
            exec_state = self.evaluate_execution_from_factor(cand, factor)
            risk = self.compute_risk_state(cand, factor, exec_state)
            ok = bool(cand.eligible and exec_state.confirmed and risk.pass_or_wait)
            reasons = list(cand.reasons)
            reasons.extend(exec_state.reasons)
            reasons.append(f"风险仓位: {risk.suggested_position_pct or 0:.1f}%")
            gates = {
                "market_regime": GateResult(name="market_regime", passed=cand.market_regime in ("A", "B", "C"), score=cand.market_regime_state.score if cand.market_regime_state else 0, reason=f"regime={cand.market_regime}", detail={}),
                "trend_state": GateResult(name="trend_state", passed=cand.trend_state in ("S1", "S2", "S3"), score=cand.trend_state_info.score if cand.trend_state_info else 0, reason=cand.trend_state, detail={}),
                "trend_quality": GateResult(name="trend_quality", passed=cand.quality_info.grade in ("A", "B"), score=cand.quality_info.score if cand.quality_info else 0, reason=f"quality={cand.trend_quality}", detail={}),
                "sector": GateResult(name="sector", passed=cand.sector_info.passed if cand.sector_info else True, score=cand.sector_info.score if cand.sector_info else 50, reason=cand.sector_info.grade if cand.sector_info else "default", detail={}),
                "execution": GateResult(name="execution", passed=exec_state.confirmed, score=exec_state.order_flow_score, reason="T+1 execution", detail=exec_state.to_dict()),
                "risk": GateResult(name="risk", passed=risk.pass_or_wait, score=0, reason=risk.reason, detail=risk.to_dict()),
            }
            out.append(BuySignal(
                symbol_code=cand.symbol_code,
                symbol_name=cand.symbol_name,
                trade_date=trade_date,
                lifecycle_state="T+1买入候选" if ok else ("WAIT" if cand.eligible else "PASS"),
                pool_type="主升浪",
                divergence_mode="mtf",
                divergence_score=round(cand.entry_score, 2),
                entry_quality_score=round(cand.entry_score, 2),
                weak_to_strong_score=round(cand.quality_info.score if cand.quality_info else 0, 2),
                t1_buy_score=round(cand.entry_score, 2),
                buy_ready=ok,
                reasons=reasons,
                candidate="MainTrend",
                gates=gates,
                trend_state=cand.trend_state,
                trend_quality=cand.trend_quality,
                market_regime=cand.market_regime,
                suggested_position_pct=risk.suggested_position_pct,
                stop_loss_pct=float((self.config.holding or {}).get("stop_loss_pct", -6.0)),
                take_profit_pct=float((self.config.holding or {}).get("take_profit_pct", 6.0)),
            ))
        return out

    def evaluate_execution_from_factor(self, cand: MTFCandidate, factor: Dict[str, Any]) -> "ExecutionState":
        from strategies.main_trend.schemas import ExecutionState
        # 在执行引擎里保留抽象对象以兼容未来 T+1 实时数据。
        # 回测阶段没有盘中T+1，我们使用日线 factor 里的 vwap/open/close 近似。
        close = _num(factor.get("close"))
        vwap = _num(factor.get("vwap_20")) or _num(factor.get("vwap"))
        open_ = _num(factor.get("open"))
        high = _num(factor.get("high"))
        low = _num(factor.get("low"))
        gap_pct = (open_ / close - 1.0) * 100.0 if open_ and close and open_ != close else None
        # 简化：close >= vwap 视为 VWAP 承担； order_flow用量比/日内结构代理
        vwap_hold = close is not None and vwap is not None and close >= vwap
        order_flow = 50.0
        if _bool(factor.get("rising_volume")):
            order_flow += 20
        if _num(factor.get("pullback_near_vwap")):
            order_flow += 15
        vol = _num(factor.get("volume_ratio"))
        if vol is not None and 1.0 <= vol <= 3.0:
            order_flow += 10
        structure = 50.0
        if _bool(factor.get("hh_hl_strict")):
            structure += 20
        if close is not None and low is not None and low < close:
            structure += 10
        # Gap 动态：A级+强趋势+催化 高开允许；C级无催化高开 -> WAIT。
        gap_penalty = 0.0
        gap_reason = ""
        if gap_pct is not None:
            if gap_pct >= 5.0:
                if cand.market_regime == "A" and cand.trend_state == "S2" and cand.catalyst_info.has_event:
                    gap_penalty = 0.0
                    gap_reason = "A级/S2/催化剂高开允许"
                else:
                    gap_penalty = -15
                    gap_reason = "高开进入成本过高，WAIT"
            elif gap_pct <= -3.0:
                gap_penalty = -10
                gap_reason = "低开体现弱势"
            else:
                gap_reason = "Gap可控"
        score = 40.0 + (15.0 if vwap_hold else 0.0) + (order_flow - 50) * 0.3 + (structure - 50) * 0.3 + gap_penalty
        confirmed = bool(score >= 60 and (gap_reason != "低开体现弱势" if gap_reason else True))
        reasons = []
        if vwap_hold:
            reasons.append("价格>=VWAP")
        else:
            reasons.append("价格低于VWAP")
        reasons.append(f"OrderFlow={order_flow:.1f}")
        reasons.append(f"IntradayStructure={structure:.1f}")
        if gap_reason:
            reasons.append(gap_reason)
        return ExecutionState(
            opening_gap_pct=gap_pct,
            auction_score=0.0,
            index_state=cand.market_regime,
            sector_state=cand.sector_info.grade if cand.sector_info else "",
            vwap_state=vwap_hold,
            order_flow_score=round(order_flow, 2),
            intraday_structure_score=round(structure, 2),
            confirmed=confirmed,
            abandon_reason="" if confirmed else (gap_reason or "执行未确认"),
            reasons=reasons,
        )

    def compute_risk_state(self, cand: MTFCandidate, factor: Dict[str, Any], exec_state: "ExecutionState") -> RiskState:
        cfg = self.config.risk or {}
        risk_budget = float(cfg.get("risk_budget_pct", 1.0) or 1.0)
        account_risk = risk_budget * float(cand.market_regime_state.risk_multiplier if cand.market_regime_state else 1.0)
        quality_mult = float(cand.quality_info.multiplier if cand.quality_info else 1.0)
        stop_pct = float(cfg.get("stop_atr_mult", 2.5) or 2.5)
        atr_pct = _num(factor.get("atr_pct"))
        if atr_pct:
            stop_distance_pct = atr_pct * stop_pct
        else:
            stop_distance_pct = 6.0
        max_pos = float(cfg.get("max_position_pct", 50) or 50)
        if stop_distance_pct and stop_distance_pct > 0:
            suggested = account_risk / stop_distance_pct * 100.0 * quality_mult
        else:
            suggested = 0.0
        suggested = min(suggested, max_pos)
        pass_ok = bool(suggested > 0.1 and cand.market_regime != "D")
        reason = f"account_risk={account_risk:.2f}% / stop_distance={stop_distance_pct:.2f}% * Q{quality_mult:.2f} -> pos={suggested:.1f}%"
        return RiskState(
            account_risk_pct=account_risk,
            stop_distance_pct=round(stop_distance_pct, 2),
            stop_distance_abs=_num(factor.get("atr")) * stop_pct if _num(factor.get("atr")) else None,
            quality_multiplier=round(quality_mult, 2),
            suggested_position_pct=round(suggested, 2),
            max_position_pct=max_pos,
            pass_or_wait=pass_ok,
            reason=reason,
            detail={"market_regime": cand.market_regime, "trend_state": cand.trend_state},
        )

    # ================= 7. 持仓状态机 =================
    def evaluate_exits(self, holdings: List[Holding]) -> List[ExitDecision]:
        cfg = self.config.holding or {}
        stop_pct = float(cfg.get("stop_loss_pct", -6.0) or -6.0)
        trailing_mult = float(cfg.get("atr_trailing_mult", 3.0) or 3.0)
        max_days = int(cfg.get("horizon_days", 10) or 10)
        out = []
        for h in holdings:
            current = _num(h.current_price) or h.entry_price
            highest = _num(h.highest_price) or max(current, h.entry_price)
            ret_pct = (current / h.entry_price - 1.0) * 100.0 if h.entry_price else 0.0
            reasons = []
            decay = self._trend_decay_score(current, highest, h, cfg)
            pos = PositionState(
                state="HOLD",
                action="hold",
                score=100 - decay,
                reasons=reasons,
                add_allowed=bool(ret_pct > 0 and decay < 30),
                trend_decay_score=decay,
            )
            action = "hold"
            reason_list = []
            atr_trail_triggered = False
            recapture_triggered = False

            # 硬性优先：固定止损
            if ret_pct <= stop_pct:
                action = "sell"
                reason_list.append("跌破止损")
            # ATR trailing stop（若持有数据里已有 precomputed stop 则直接触发）
            elif h.atr_trailing_stop is not None and h.atr_trailing_stop > 0 and current < h.atr_trailing_stop:
                atr_trail_triggered = True
                action = "exit"
                reason_list.append("ATR Trailing Stop触发")
            # 趋势严重衰减
            elif decay >= float(cfg.get("severe_decay_threshold", 70) or 70):
                action = "exit"
                reason_list.append("趋势严重衰减")
            elif h.holding_days >= max_days:
                action = "exit"
                reason_list.append("超期退出")
            # S5 recapture：Close<MA20 后“次日无法重新站回”由调用方把 prev_close/prefecture 信息传入。
            # 这里用 prev_close 与 current 近似判断：“前一日跌破后，当前仍未站回”即退出。
            elif (
                h.prev_close is not None
                and h.current_price is not None
                and h.prev_close < (h.stop_loss_price or h.entry_price)  # 简化为上一日已在关键线下
                and current <= h.prev_close * (1 + float(cfg.get("recapture_allowance_pct", 0.01) or 0.01))
            ):
                recapture_triggered = True
                action = "exit"
                reason_list.append("跌破关键线且次日无法站回")
            elif decay >= float(cfg.get("reduce_decay_threshold", 45) or 45):
                action = "reduce"
                reason_list.append("趋势衰减减仓")
            elif ret_pct > 0 and decay < 30:
                action = "add_hint"
                reason_list.append("盈利趋势再确认可加仓")

            if action == "add_hint":
                pos.state = "ADD"
                pos.action = "add"
            elif action == "reduce":
                pos.state = "REDUCE"
                pos.action = "reduce"
            elif action in ("exit", "sell"):
                pos.state = "EXIT"
                pos.action = "exit" if action == "exit" else "sell"
                pos.reasons = reason_list[:]
            elif decay >= 45:
                pos.state = "DECAY"
                pos.action = "decay"
                pos.reasons = reason_list[:]
            else:
                pos.state = "HOLD"
                pos.action = "hold"

            out.append(ExitDecision(
                symbol_code=h.symbol_code,
                symbol_name=h.symbol_name,
                action=pos.action,
                reason="; ".join(reason_list) if reason_list else "继续持有",
                urgency="high" if pos.action == "exit" or pos.action == "sell" else "normal",
                exit_score=round(100 - decay, 2),
                current_return_pct=round(ret_pct, 2),
                stop_loss_triggered=bool(ret_pct <= stop_pct),
                take_profit_triggered=False,
                reduce_triggered=bool(pos.action == "reduce"),
                add_allowed=pos.add_allowed,
                state=pos.state,
                position_state=pos.state,
                decay_score=round(decay, 2),
                atr_trailing_stop_triggered=atr_trail_triggered,
                recapture_triggered=recapture_triggered,
                reasons=pos.reasons,
            ))
        return out

    def _trend_decay_score(self, current_price: float, highest_price: float, holding: Holding, cfg: Dict[str, Any]) -> float:
        """原则⑧：ATR高不天然风险；这里用“离高点深度 + 持仓时长 + ATR trailing 接近度”作 decay。

        不用 ATR 绝对值直接惩罚；ATR trailing 只在给定 stop 被击穿时触发退出。
        """
        score = 0.0
        if highest_price and highest_price > 0:
            drawdown = (highest_price - current_price) / highest_price * 100.0
            if drawdown > 5:
                score += 40
            elif drawdown > 2:
                score += 25
            else:
                score += 5
        if holding.atr_trailing_stop and holding.atr_trailing_stop > 0 and holding.entry_price > 0:
            stop_dist = (holding.atr_trailing_stop - current_price) / holding.entry_price * 100.0
            # 越接近 trailing stop，衰减分越高，但仅在击穿时触发 exit。
            if stop_dist > 0:
                score += min(35.0, max(0.0, stop_dist * 2.0))
        if holding.holding_days >= int(cfg.get("horizon_days", 5) or 5):
            score += 30
        return round(_clamp(score), 2)

    # ================= 工具 =================
    def _write_result(self, result: Dict[str, Any], output_dir: str) -> None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
