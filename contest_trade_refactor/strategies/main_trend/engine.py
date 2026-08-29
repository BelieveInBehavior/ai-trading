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

核心哲学（Flag Planted）：**盈利不是加仓理由，新的趋势确认才是。**
ADD = SetupLayer(形态/量价/板块/RS) + ConfirmationLayer(盘中确认)；
浮盈只做 RiskEngine 加仓数量输入，不参与能否加仓。
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
from utils.sector_enrichment import (
    build_sector_snapshot,
    build_sector_snapshot_from_factor_store,
    build_code_sector_snapshot,
    load_industry_map,
    enrich_factor_with_sector,
)
from utils.factor_dedup import family_dedup_report as _family_dedup_report, pick_representatives as _pick_factor_rep
from utils.factor_store import LHB_HOT_MONEY_STORE, ZT_SEAL_STORE
from utils.financial_report_utils import enrich_signals_with_financial_report
from utils.tencent_realtime import fetch_realtime_quote as _fetch_realtime_quote, build_quote_payload as _build_quote_payload

from strategies.main_trend.event_logger import log_tday_pool
from strategies.main_trend.scoring import compute_pre_score, compute_profit_protect_price
from strategies.main_trend.tday import build_tday_row, finalize_tday_pool, price_context_from_factor, scoring_weights
from strategies.main_trend.schemas import (
    BuySignal,
    CatalystState,
    DataQualityState,
    ExitDecision,
    FundamentalState,
    GateResult,
    Holding,
    HotMoneyState,
    MarketRegimeState,
    MarketSentimentState,
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


def _json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _amount_to_yi(value: Any) -> float:
    """把金额粗略转成亿元；已是小数亿元时保持温和。"""
    v = _num(value)
    if v is None:
        return 0.0
    av = abs(v)
    if av >= 10_000_000:
        return v / 100_000_000.0
    if av >= 10_000:
        return v / 10_000.0
    return v


def _mavg(series: pd.Series, size: int, ma_mode: str = "ema") -> pd.Series:
    """金融口径均值：EMA 用 ewm(span=size, adjust=False, min_periods=size)。

    SMA -> rolling(size).mean()；EMA -> ewm(span=size, adjust=False).mean()。
    指数均线是策略主升浪默认口径（main_trend.technical.ma_mode=ema）。
    """
    mode = str(ma_mode or "ema").strip().lower()
    if mode == "ema":
        return series.ewm(span=size, adjust=False, min_periods=size).mean()
    return series.rolling(size).mean()


def _normalize_code(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) < 6:
        return ""
    code = digits[-6:]
    suffix = ".SH" if code.startswith("6") else ".SZ"
    return f"{code}{suffix}"


def _fmt_pct(value: Optional[float], digits: int = 2) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}%"


def _percentile_rank_100(value: Optional[float], values: Optional[List[float]]) -> Optional[float]:
    """金融口径横截面百分位排名（0~100）。

    value 处于 all values 中的百分位：小于该值的样本 + 0.5*等于该值的样本数，再归一化。
    仅单股 / 样本不足时返回 None，避免把缺乏截面信息的因子强行变成百分位。
    """
    if value is None or not values:
        return None
    below = sum(1 for x in values if x < value)
    equal = sum(1 for x in values if x == value)
    if len(values) <= 0:
        return None
    return round((below + 0.5 * equal) / len(values) * 100.0, 2)


def _enrich_residual_rs(factor: Dict[str, Any]) -> Dict[str, Any]:
    """在 factor 上补全残差 RS 原始因子（金融口径）。

    - vs Index：technical factor 里已基于日收益 OLS 算出 alpha+beta*bench+eps 的 residual。
      若没有（外部注入/降级），只写 excess_rs_vs_index_*，不再把“简单超额收益”冒充 residual。
    - vs Sector：sector enrichment 有板块日线时会算出 OLS residual；只有板块日线不可用时才
      输出 excess_rs_vs_sector_*，命名明确区分。
    - 兼容字段 residual_rs_vs_index / residual_rs_vs_sector 仅在“真残差”存在时赋值；
      否则对应位置给 None，避免名不副实。
    """
    if not factor:
        return factor

    # ---- vs Index：只在已有 true OLS residual 时写入，否则只记录简单超额 ----
    resid_index_20 = _num(factor.get("residual_rs_vs_index_20d"))
    if resid_index_20 is None:
        stock20 = _num(factor.get("stock_return_20d_pct"))
        bench20 = _num(factor.get("benchmark_return_20d_pct"))
        if stock20 is not None and bench20 is not None:
            factor["excess_rs_vs_index_20d"] = round(stock20 - bench20, 4)
    resid_index_60 = _num(factor.get("residual_rs_vs_index_60d"))
    if resid_index_60 is None:
        stock60 = _num(factor.get("stock_return_60d_pct"))
        bench60 = _num(factor.get("benchmark_return_60d_pct"))
        if stock60 is not None and bench60 is not None:
            factor["excess_rs_vs_index_60d"] = round(stock60 - bench60, 4)

    # ---- vs Sector：优先使用 sector enrichment 已算出的 OLS 真残差；缺失时输出超额并命名清楚 ----
    if _num(factor.get("residual_rs_vs_sector_20d")) is None and _num(factor.get("residual_rs_vs_sector_60d")) is not None:
        factor["residual_rs_vs_sector_20d"] = factor.get("residual_rs_vs_sector_60d")
    for lookback in (1, 3, 5, 10):
        stock_col = "change_pct" if lookback == 1 else f"ret_{lookback}d_pct"
        sector_col = f"sector_{lookback}d_return"
        stock_v = _num(factor.get(stock_col))
        sector_v = _num(factor.get(sector_col))
        if stock_v is not None and sector_v is not None:
            factor[f"excess_rs_vs_sector_{lookback}d"] = round(stock_v - sector_v, 4)

    # 兼容字段：只有“真残差”才写入 residual_rs_vs_*；否则用 excess_rs_vs_* 明确表达超额。
    residual_index_merged = _num(factor.get("residual_rs_vs_index_20d")) or _num(factor.get("residual_rs_vs_index_60d"))
    if residual_index_merged is not None:
        factor["residual_rs_vs_index"] = residual_index_merged
    else:
        factor.pop("residual_rs_vs_index", None)
        excess_index = _num(factor.get("excess_rs_vs_index_20d")) or _num(factor.get("excess_rs_vs_index_60d"))
        if excess_index is not None:
            factor["excess_rs_vs_index"] = excess_index

    residual_sector_merged = _num(factor.get("residual_rs_vs_sector_20d")) or _num(factor.get("residual_rs_vs_sector_60d"))
    if residual_sector_merged is not None:
        factor["residual_rs_vs_sector"] = residual_sector_merged
    else:
        factor.pop("residual_rs_vs_sector", None)
    excess_sector = _num(factor.get("excess_rs_vs_sector_5d")) or _num(factor.get("excess_rs_vs_sector_3d")) or _num(factor.get("excess_rs_vs_sector_1d"))
    if excess_sector is not None:
        factor["excess_rs_vs_sector"] = excess_sector
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
    sentiment: Dict[str, Any] = field(default_factory=dict)
    catalyst: Dict[str, Any] = field(default_factory=dict)
    fundamental: Dict[str, Any] = field(default_factory=dict)
    hot_money: Dict[str, Any] = field(default_factory=dict)
    execution: Dict[str, Any] = field(default_factory=dict)
    technical: Dict[str, Any] = field(default_factory=dict)
    scoring: Dict[str, Any] = field(default_factory=dict)
    portfolio: Dict[str, Any] = field(default_factory=dict)
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
            sentiment=dict(cfg.get("sentiment") or {}),
            catalyst=dict(cfg.get("catalyst") or {}),
            fundamental=dict(cfg.get("fundamental") or {}),
            hot_money=dict(cfg.get("hot_money") or {}),
            execution=dict(cfg.get("execution") or {}),
            technical=dict(cfg.get("technical") or {}),
            scoring=dict(cfg.get("scoring") or {}),
            portfolio=dict(cfg.get("portfolio") or {}),
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

    def _ma_mode(self) -> str:
        mode = str((self.config.technical or {}).get("ma_mode") or "ema").strip().lower()
        if mode not in ("sma", "ema"):
            mode = "ema"
        return mode

    # ================= 主入口 =================
    async def run_day(
        self,
        trigger_time: str,
        watchlist: Optional[List[Any]] = None,
        holdings: Optional[List[Holding]] = None,
        output_dir: Optional[str] = None,
        max_symbols: int = 0,
        phase: str = "tday",
    ) -> Dict[str, Any]:
        trade_date = get_latest_completed_trading_date(trigger_time)
        discovery = await self.discover(trigger_time, max_symbols=max_symbols)
        # 合并历史候选/观察池：这里可简化，保留当日候选即可。
        eligible = discovery.eligible
        tday = self.build_tday_pool(eligible, trade_date)
        # T日默认不跑 T+1 实时确认，避免把收盘价当成买入价
        buy_signals = self.build_buy_signals(eligible, trade_date, phase=phase or "tday", tday_rows=tday.get("pool") or [])
        exits = self.evaluate_exits(holdings or [])
        result = {
            "trade_date": trade_date,
            "trigger_time": trigger_time,
            "phase": phase or "tday",
            "discovery": discovery.to_dict() if hasattr(discovery, "to_dict") else {},
            "tday_pool": tday,
            "buy_signals": [s.to_dict() for s in buy_signals],
            "candidate_pool_t1": [s.to_dict() for s in buy_signals],
            "exit_decisions": [e.to_dict() for e in exits],
        }
        if output_dir:
            self._write_result(result, output_dir)
            log_tday_pool(output_dir, trade_date, tday.get("pool") or [], tday.get("themes") or [])
        return result

    async def discover(self, trigger_time: str, max_symbols: int = 0) -> MTFDiscovery:
        trade_date = get_latest_completed_trading_date(trigger_time)
        start_date, end_date = get_trading_date_range(end_date=trade_date, count=260, include_end=True)
        universe = await asyncio.to_thread(self._load_universe, max_symbols)
        benchmark = await asyncio.to_thread(self._load_benchmark, self.config.benchmark_symbol, start_date, end_date)
        sector_snapshot = await asyncio.to_thread(self._build_sector_snapshot, trade_date)
        sentiment = self.assess_market_sentiment(trade_date)
        market = self.evaluate_market_regime(
            trade_date,
            market_context={"risk_sentiment": sentiment.risk_sentiment, "market_sentiment_score": sentiment.score},
            sector_snapshot=sector_snapshot,
        )

        sem = asyncio.Semaphore(max(1, int(self.config.quantitative_concurrency) or 4))
        candidates: List[MTFCandidate] = []
        raw_factors: List[Dict[str, Any]] = []
        errors: List[str] = []

        async def _score(row: Dict[str, Any], median_out: List[float]) -> None:
            async with sem:
                try:
                    # 单遍：先计算完整技术因子（同时拿到 median_amount_20d）
                    factor = self._factor_for_row(row, start_date, end_date, trade_date, benchmark)
                    median_out.append(_num(factor.get("median_amount_20d")) if factor else None)
                    if not factor:
                        return
                    raw_factors.append(factor)
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
                market_sentiment=sentiment,
                context_string=context,
                scan_errors=errors,
            )

        liquidity_p20 = None
        all_median_amounts: List[float] = []

        batch_size = max(1, int(self.config.quantitative_concurrency) * 3)
        for offset in range(0, total, batch_size):
            batch = universe[offset: offset + batch_size]
            await asyncio.gather(*[_score(row, all_median_amounts) for row in batch])
            done = min(offset + len(batch), total)
            print(f"[main_trend] scan {trade_date} {done}/{total} factors={len(raw_factors)}", flush=True)

        valid_amounts = [x for x in all_median_amounts if x is not None and x > 0]
        # 全市场横截面 P20（单遍扫描收集所有股票的 20D Median Turnover）
        if len(valid_amounts) >= 10:
            valid_amounts.sort()
            idx = max(0, int(round(len(valid_amounts) * 0.20)) - 1)
            liquidity_p20 = valid_amounts[idx]

        # ---- 全市场横截面相对强度：金融口径百分位 rank（不再只用单股 IR 近似）。 ----
        # 遍历全部 raw_factor，以 RS20/RS60/OLS residual 等做截面百分位，再重新评分。
        rs20_vals: List[float] = []
        rs60_vals: List[float] = []
        resid_idx20: List[float] = []
        resid_sector20: List[float] = []
        for f in raw_factors:
            rs20 = _num(f.get("relative_strength_20d_pct"))
            rs60 = _num(f.get("relative_strength_60d_pct"))
            resid20 = _num(f.get("residual_rs_vs_index_20d"))
            resid_sec20 = _num(f.get("residual_rs_vs_sector_20d")) or _num(f.get("residual_rs_vs_sector_60d"))
            if rs20 is not None:
                rs20_vals.append(rs20)
            if rs60 is not None:
                rs60_vals.append(rs60)
            if resid20 is not None:
                resid_idx20.append(resid20)
            if resid_sec20 is not None:
                resid_sector20.append(resid_sec20)

        for f in raw_factors:
            rs20 = _num(f.get("relative_strength_20d_pct"))
            rs60 = _num(f.get("relative_strength_60d_pct"))
            resid20 = _num(f.get("residual_rs_vs_index_20d"))
            resid_sec20 = _num(f.get("residual_rs_vs_sector_20d")) or _num(f.get("residual_rs_vs_sector_60d"))
            p20 = _percentile_rank_100(rs20, rs20_vals)
            p60 = _percentile_rank_100(rs60, rs60_vals)
            p_resid = _percentile_rank_100(resid20, resid_idx20)
            p_resid_sector = _percentile_rank_100(resid_sec20, resid_sector20)
            factor_pct = None
            if p20 is not None or p60 is not None:
                factor_pct = round((0.5 * (p20 if p20 is not None else 50.0) + 0.5 * (p60 if p60 is not None else 50.0)), 2)
                f["relative_strength_cross_section_pct"] = factor_pct
                f["relative_strength_grade"] = (
                    "A" if factor_pct >= 80
                    else "B" if factor_pct >= 60
                    else "C" if factor_pct >= 40
                    else "D"
                )
                base = 50.0
                if rs20 is not None:
                    base = max(0.0, min(100.0, float(rs20)))
                f["relative_strength_score"] = round(max(0.0, min(100.0, 0.7 * factor_pct + 0.3 * base)), 2)
            if p_resid is not None:
                f["residual_rs_vs_index_20d_pct"] = p_resid
            if p_resid_sector is not None:
                f["residual_rs_vs_sector_20d_pct"] = p_resid_sector

        # ---- Layer 3 因子族内去重：全市场截面相关矩阵 / VIF / 代表性因子 ----
        factor_family_dedup = {}
        try:
            factor_family_dedup = _family_dedup_report(
                raw_factors,
                corr_threshold=float(self.config.quality.get("family_corr_threshold", 0.85) or 0.85),
                corr_method=str(self.config.quality.get("family_corr_method", "spearman") or "spearman"),
            )
            for f in raw_factors:
                f["_factor_family_dedup"] = factor_family_dedup
        except Exception as exc:
            errors.append(f"factor_family_dedup:{exc}")

        # 构造候选：用已经过截面 RS / 因子族去重诊断的 factor
        row_by_code: Dict[str, Dict[str, Any]] = {}
        for row in universe:
            code = str(row.get("symbol_code") or "").strip().upper()
            row_by_code[code] = row
            if "." in code:
                row_by_code[code.split(".")[0]] = row
        for factor in raw_factors:
            code = str(factor.get("symbol_code") or "").strip().upper()
            row = row_by_code.get(code) or row_by_code.get(code.split(".")[0])
            if row is None:
                continue
            try:
                cand = self._candidate_from_factor(row, factor, trade_date, market, sector_snapshot, sentiment)
                if cand:
                    candidates.append(cand)
            except Exception as exc:
                errors.append(str(exc))

        # 只富化已通过技术状态初筛的候选，避免对全市场逐股请求财报。
        # 数据工具接收 trigger_time，保证回测只能看到当时已披露的信息。
        fundamental_cfg = self.config.fundamental or {}
        if candidates and bool(fundamental_cfg.get("enabled", True)) and bool(fundamental_cfg.get("fetch_reports", True)):
            try:
                payloads = []
                for cand in candidates:
                    payload = dict(cand.technical_factor or {})
                    payload["symbol_code"] = cand.symbol_code
                    payloads.append(payload)
                enriched = await enrich_signals_with_financial_report(
                    payloads,
                    trigger_time=trigger_time,
                    period_count=int(fundamental_cfg.get("period_count", 4) or 4),
                    concurrency=int(fundamental_cfg.get("concurrency", 4) or 4),
                )
                by_code = {str(row.get("symbol_code") or ""): row for row in enriched}
                for cand in candidates:
                    enriched_factor = by_code.get(cand.symbol_code)
                    if not enriched_factor:
                        continue
                    cand.technical_factor = enriched_factor
                    fundamental = self.assess_fundamental_state(enriched_factor, trade_date)
                    cand.fundamental_info = fundamental
                    market_mult = cand.market_regime_state.risk_multiplier if cand.market_regime_state else 1.0
                    cand.risk_multiplier = market_mult * fundamental.risk_multiplier
                    cand.reasons.extend(r for r in fundamental.reasons if r not in cand.reasons)
            except Exception as exc:
                errors.append(f"fundamental_enrichment:{exc}")

        for c in candidates:
            self.apply_hard_filter(c, market, liquidity_p20)

        eligible = [c for c in candidates if c.eligible]
        dedup_note = ""
        if factor_family_dedup:
            reps = factor_family_dedup.get("representatives") or {}
            dedup_note = "; factor_family_dedup=" + str(reps)
        context = (
            f"主升浪扫描：universe={total}, candidates={len(candidates)}, eligible={len(eligible)}; "
            f"MarketSentiment={sentiment.grade}({sentiment.score:.1f}); errors={len(errors)}{dedup_note}"
        )
        return MTFDiscovery(
            trade_date=trade_date,
            all_candidates=candidates,
            eligible=eligible,
            universe_count=total,
            market_regime=market,
            market_sentiment=sentiment,
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
        try:
            industry_map = load_industry_map()
            by_name = build_sector_snapshot_from_factor_store(trade_date=trade_date)
            snapshot = build_code_sector_snapshot(industry_map, by_name, trade_date=trade_date)
            if snapshot:
                return snapshot
        except Exception:
            pass
        try:
            return build_sector_snapshot(trade_date=trade_date, industry_map=load_industry_map())
        except Exception:
            return {}

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
                ma5 = float(_mavg(closes, 5, self._ma_mode()))
                ma20 = float(_mavg(closes, 20, self._ma_mode()))
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
                # 金融口径：样本标准差（ddof=1）。
                market_vol = float(rets.std(ddof=1) * 100.0)
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

    def assess_market_sentiment(self, trade_date: str, context: Optional[Dict[str, Any]] = None) -> MarketSentimentState:
        """短线市场情绪：涨停家数/炸板率/连板高度/实体涨停率。

        数据缺失时默认中性放行，避免回测或盘中数据源缺失导致误杀。
        """
        cfg = self.config.sentiment or {}
        if cfg.get("enabled") is False:
            return MarketSentimentState(
                score=50.0,
                grade="B",
                risk_sentiment="neutral",
                passed=True,
                available=False,
                risk_multiplier=1.0,
                reasons=["市场情绪因子关闭，中性放行"],
                detail={"source": "disabled"},
            )
        ctx = dict(context or {})
        min_zt = int(cfg.get("min_limit_up_count", 40) or 40)
        strong_zt = int(cfg.get("strong_limit_up_count", 80) or 80)
        max_break_ratio = float(cfg.get("max_break_ratio", 0.35) or 0.35)
        min_top_board = int(cfg.get("min_top_board", 3) or 3)
        min_real_zt_ratio = float(cfg.get("min_real_zt_ratio", 0.35) or 0.35)
        reasons: List[str] = []
        detail: Dict[str, Any] = {}
        available = False
        zt_count = _int(ctx.get("limit_up_count"), 0)
        dt_count = _int(ctx.get("limit_down_count"), 0)
        break_count = _int(ctx.get("break_count"), 0)
        top_board = _int(ctx.get("max_board"), 0)
        one_word = _int(ctx.get("one_word_limit_up_count"), 0)

        if zt_count <= 0 and not ctx:
            try:
                df = ZT_SEAL_STORE.load(trade_date)
            except Exception:
                df = pd.DataFrame()
            if df is not None and not df.empty:
                available = True
                zt_count = int(len(df))
                for _, row in df.iterrows():
                    meta = _json_dict(row.get("metadata_json"))
                    brk = _int(meta.get("break_count"), 0)
                    board = _int(meta.get("continuous_board"), 1)
                    turnover = _num(meta.get("turnover"), 99.0) or 99.0
                    if brk > 0:
                        break_count += 1
                    top_board = max(top_board, board)
                    if brk == 0 and turnover <= 1.0:
                        one_word += 1
        else:
            available = True

        if not available:
            return MarketSentimentState(
                score=50.0,
                grade="B",
                risk_sentiment="neutral",
                passed=True,
                available=False,
                risk_multiplier=1.0,
                reasons=["情绪数据缺失，默认中性放行"],
                detail={"source": "missing"},
            )

        break_ratio = break_count / max(1, zt_count)
        real_zt_ratio = 1.0 - one_word / max(1, zt_count)
        score = 50.0
        if zt_count >= strong_zt:
            score += 20
            reasons.append(f"涨停家数{zt_count}>={strong_zt}")
        elif zt_count >= min_zt:
            score += 10
            reasons.append(f"涨停家数{zt_count}>={min_zt}")
        else:
            score -= 25
            reasons.append(f"涨停家数{zt_count}<{min_zt}")
        if break_ratio >= max_break_ratio:
            score -= 18
            reasons.append(f"炸板率{break_ratio:.0%}>={max_break_ratio:.0%}")
        elif break_ratio <= 0.15:
            score += 8
            reasons.append("炸板率低")
        if top_board >= min_top_board + 2:
            score += 12
            reasons.append(f"高度{top_board}板")
        elif top_board >= min_top_board:
            score += 6
            reasons.append(f"高度{top_board}板")
        else:
            score -= 14
            reasons.append(f"最高板{top_board}<{min_top_board}")
        if real_zt_ratio < min_real_zt_ratio:
            score -= 8
            reasons.append("一字板占比高，实体接力弱")
        if dt_count >= 20:
            score -= 15
            reasons.append(f"跌停{dt_count}只")

        score = _clamp(score)
        grade = "A" if score >= 70 else "B" if score >= 55 else "C" if score >= 40 else "D"
        risk_sentiment = "risk_on" if grade == "A" else "risk_off" if grade in ("C", "D") else "neutral"
        risk_mult = 1.1 if grade == "A" else 1.0 if grade == "B" else 0.75 if grade == "C" else 0.35
        passed = bool(grade != "D")
        detail.update({
            "source": "zt_seal_strength",
            "limit_up_count": zt_count,
            "limit_down_count": dt_count,
            "break_count": break_count,
            "break_ratio": round(break_ratio, 4),
            "max_board": top_board,
            "one_word_limit_up_count": one_word,
            "real_limit_up_ratio": round(real_zt_ratio, 4),
        })
        return MarketSentimentState(
            score=round(score, 2),
            grade=grade,
            risk_sentiment=risk_sentiment,
            passed=passed,
            available=True,
            risk_multiplier=round(risk_mult, 3),
            reasons=reasons,
            detail=detail,
        )

    def assess_hot_money_state(self, factor: Dict[str, Any], trade_date: str) -> HotMoneyState:
        """个股热钱状态：龙虎榜/涨停封单只做确认与风险，不做独立买点。"""
        cfg = self.config.hot_money or {}
        if cfg.get("enabled") is False:
            return HotMoneyState(
                score=50.0,
                grade="B",
                passed=True,
                has_lhb=False,
                has_limit_up=False,
                risk_flag="",
                reasons=["龙虎榜/热钱因子关闭，中性放行"],
                detail={"source": "disabled"},
            )
        code = str(factor.get("symbol_code") or "").strip()
        code6 = code[:6]
        detail: Dict[str, Any] = {}
        reasons: List[str] = []
        score = 50.0
        has_lhb = False
        has_limit_up = False
        risk_flag = ""

        zt_meta = self._load_zt_meta(trade_date, code6)
        if zt_meta:
            has_limit_up = True
            board = _int(zt_meta.get("continuous_board"), 1)
            break_count = _int(zt_meta.get("break_count"), 0)
            seal_strength = _num(zt_meta.get("seal_strength")) or _num(zt_meta.get("factor_value")) or 0.0
            score += min(12.0, max(0.0, seal_strength) * 2.0)
            if board >= 2:
                score += min(10.0, board * 2.0)
                reasons.append(f"连板{board}")
            if break_count >= 3:
                score -= 12
                risk_flag = "frequent_break_limit"
                reasons.append(f"炸板{break_count}次")
            elif break_count == 0:
                score += 4
                reasons.append("封板稳定")
            detail["zt"] = zt_meta

        lhb = self._load_lhb_meta(trade_date, code6)
        if not lhb:
            lhb = self._lhb_meta_from_factor(factor)
        if lhb:
            has_lhb = True
            net_buy = _num(lhb.get("net_buy_amount")) or _num(lhb.get("net_buy")) or _num(lhb.get("龙虎榜净买额"))
            inst_net = _num(lhb.get("institution_net_buy")) or _num(lhb.get("institution_net_buy_amount")) or _num(lhb.get("机构净买额"))
            hot_money_net = _num(lhb.get("hot_money_net_buy")) or _num(lhb.get("游资净买额"))
            if net_buy is not None:
                if net_buy > 0:
                    score += min(10.0, _amount_to_yi(net_buy) * 2.0)
                    reasons.append("龙虎榜净买入")
                elif net_buy < 0:
                    score -= min(15.0, abs(_amount_to_yi(net_buy)) * 3.0)
                    risk_flag = risk_flag or "lhb_net_sell"
                    reasons.append("龙虎榜净卖出")
            if inst_net is not None:
                if inst_net > 0:
                    score += min(10.0, _amount_to_yi(inst_net) * 2.5)
                    reasons.append("机构净买入")
                elif inst_net < 0:
                    score -= min(15.0, abs(_amount_to_yi(inst_net)) * 3.0)
                    risk_flag = risk_flag or "institution_net_sell"
                    reasons.append("机构净卖出")
            if hot_money_net is not None and hot_money_net < 0:
                score -= min(8.0, abs(_amount_to_yi(hot_money_net)) * 2.0)
                risk_flag = risk_flag or "hot_money_net_sell"
            detail["lhb"] = lhb

        if not has_lhb and not has_limit_up:
            reasons.append("无龙虎榜/涨停热钱数据，中性")
        score = _clamp(score)
        grade = "A" if score >= 70 else "B" if score >= 55 else "C" if score >= 40 else "D"
        passed = bool(score >= float(cfg.get("min_score", 40) or 40))
        if grade == "D":
            risk_flag = risk_flag or "hot_money_weak"
        return HotMoneyState(
            score=round(score, 2),
            grade=grade,
            passed=passed,
            has_lhb=has_lhb,
            has_limit_up=has_limit_up,
            risk_flag=risk_flag,
            reasons=reasons,
            detail=detail,
        )

    def _load_zt_meta(self, trade_date: str, code6: str) -> Dict[str, Any]:
        if not code6:
            return {}
        try:
            df = ZT_SEAL_STORE.load(trade_date)
        except Exception:
            return {}
        if df is None or df.empty or "symbol_code" not in df.columns:
            return {}
        code_col = df["symbol_code"].astype(str).str.zfill(6)
        hit = df[code_col == str(code6).zfill(6)]
        if hit.empty:
            return {}
        row = hit.iloc[-1].to_dict()
        meta = _json_dict(row.get("metadata_json"))
        meta.update({
            "symbol_code": str(row.get("symbol_code") or code6).zfill(6),
            "symbol_name": row.get("symbol_name"),
            "factor_value": _num(row.get("factor_value")),
            "seal_strength": _num(row.get("factor_value")),
        })
        return {k: v for k, v in meta.items() if v is not None}

    def _load_lhb_meta(self, trade_date: str, code6: str) -> Dict[str, Any]:
        if not code6:
            return {}
        try:
            df = LHB_HOT_MONEY_STORE.load(trade_date)
        except Exception:
            return {}
        if df is None or df.empty or "symbol_code" not in df.columns:
            return {}
        code_col = df["symbol_code"].astype(str).str.replace(r"\D", "", regex=True).str[:6].str.zfill(6)
        hit = df[code_col == str(code6).zfill(6)]
        if hit.empty:
            return {}
        row = hit.iloc[-1].to_dict()
        meta = _json_dict(row.get("metadata_json"))
        meta.update({
            "symbol_code": str(row.get("symbol_code") or code6),
            "symbol_name": row.get("symbol_name"),
            "factor_value": _num(row.get("factor_value")),
        })
        return {k: v for k, v in meta.items() if v is not None}

    def _lhb_meta_from_factor(self, factor: Dict[str, Any]) -> Dict[str, Any]:
        keys = [
            "lhb_net_buy_amount", "lhb_net_buy", "net_buy_amount", "institution_net_buy",
            "institution_net_buy_amount", "hot_money_net_buy", "龙虎榜净买额", "机构净买额", "游资净买额",
        ]
        out = {}
        for k in keys:
            if k in factor and factor.get(k) is not None:
                out[k.replace("lhb_", "") if k.startswith("lhb_") else k] = factor.get(k)
        nested = factor.get("lhb") or factor.get("hot_money")
        if isinstance(nested, dict):
            out.update(nested)
        return out

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
        ma_mode = self._ma_mode()
        factor = compute_stock_technical_factor_from_history(
            hist_df=hist,
            symbol_code=symbol,
            symbol_name=str(row.get("symbol_name") or ""),
            trade_date=trade_date,
            relative_strength_benchmark=self.config.benchmark_symbol,
            benchmark_frame=benchmark,
            ma_mode=ma_mode,
        )
        return factor

    def _candidate_from_factor(
        self,
        row: Dict[str, Any],
        factor: Dict[str, Any],
        trade_date: str,
        market: MarketRegimeState,
        sector_snapshot: Dict[str, Dict[str, float]],
        sentiment: Optional[MarketSentimentState] = None,
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
        fundamental = self.assess_fundamental_state(factor, trade_date)
        hot_money = self.assess_hot_money_state(factor, trade_date)
        cand = MTFCandidate(
            symbol_code=str(factor.get("symbol_code") or _normalize_code(row.get("symbol_code"))),
            symbol_name=str(factor.get("symbol_name") or row.get("symbol_name") or ""),
            trade_date=trade_date,
            trend_state=trend.state,
            trend_quality=trend_quality.grade,
            market_regime=market.regime,
            sector_name=sector.sector_name,
            catalyst_score=round(catalyst.score, 2),
            risk_multiplier=market.risk_multiplier * fundamental.risk_multiplier,
            eligible=True,
            technical_factor=factor,
            market_regime_state=market,
            trend_state_info=trend,
            quality_info=trend_quality,
            sector_info=sector,
            catalyst_info=catalyst,
            fundamental_info=fundamental,
            market_sentiment_state=sentiment,
            hot_money_state=hot_money,
            reasons=list(trend.reasons) + list(trend_quality.reasons) + list(sector.reasons) + list(catalyst.reasons) + list(fundamental.reasons) + list(hot_money.reasons),
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
        sentiment: Optional[MarketSentimentState] = None,
    ) -> Optional[MTFCandidate]:
        symbol = str(row.get("symbol_code") or "")[:6]
        if not symbol:
            return None
        hist = get_stock_zh_a_hist(symbol, start_date, end_date, adjust="qfq", verbose=False)
        ma_mode = self._ma_mode()
        factor = compute_stock_technical_factor_from_history(
            hist_df=hist,
            symbol_code=symbol,
            symbol_name=str(row.get("symbol_name") or ""),
            trade_date=trade_date,
            relative_strength_benchmark=self.config.benchmark_symbol,
            benchmark_frame=benchmark,
            ma_mode=ma_mode,
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
        fundamental = self.assess_fundamental_state(factor, trade_date)
        hot_money = self.assess_hot_money_state(factor, trade_date)

        cand = MTFCandidate(
            symbol_code=str(factor.get("symbol_code") or _normalize_code(row.get("symbol_code"))),
            symbol_name=str(factor.get("symbol_name") or row.get("symbol_name") or ""),
            trade_date=trade_date,
            trend_state=trend.state,
            trend_quality=trend_quality.grade,
            market_regime=market.regime,
            sector_name=sector.sector_name,
            catalyst_score=round(catalyst.score, 2),
            risk_multiplier=market.risk_multiplier * fundamental.risk_multiplier,
            eligible=True,
            technical_factor=factor,
            market_regime_state=market,
            trend_state_info=trend,
            quality_info=trend_quality,
            sector_info=sector,
            catalyst_info=catalyst,
            fundamental_info=fundamental,
            market_sentiment_state=sentiment,
            hot_money_state=hot_money,
            reasons=list(trend.reasons) + list(trend_quality.reasons) + list(sector.reasons) + list(catalyst.reasons) + list(fundamental.reasons) + list(hot_money.reasons),
        )
        cand.entry_score = self._candidate_entry_score(cand)
        if not sector.passed:
            cand.eligible = False
            cand.reasons.append(f"Sector未通过:{sector.grade}")
        return cand

    def assess_fundamental_state(self, factor: Dict[str, Any], trade_date: str = "") -> FundamentalState:
        """Deterministic point-in-time fundamental layer; missing data is neutral (FU)."""
        cfg = self.config.fundamental or {}
        nested = factor.get("financial_report") if isinstance(factor.get("financial_report"), dict) else {}

        def pick(*keys: str) -> Optional[float]:
            for key in keys:
                value = factor.get(key)
                if value is None:
                    value = nested.get(key)
                parsed = _num(value)
                if parsed is not None:
                    return parsed
            return None

        ann_date = str(
            factor.get("financial_ann_date") or factor.get("ann_date")
            or nested.get("ann_date") or nested.get("publish_date") or ""
        ).replace("-", "").replace("/", "")[:8]
        asof = str(trade_date or factor.get("trade_date") or "").replace("-", "").replace("/", "")[:8]
        period = str(factor.get("financial_report_period") or nested.get("period") or nested.get("end_date") or "")
        if ann_date and asof and ann_date > asof:
            return FundamentalState(
                state="FU", available=False, as_of_date=asof, report_period=period,
                reasons=["future_financial_report_ignored"], risk_flags=["POINT_IN_TIME_GUARD"],
                detail={"ann_date": ann_date},
            )

        revenue_yoy = pick("financial_report_revenue_yoy", "revenue_yoy", "total_revenue_yoy")
        profit_yoy = pick("financial_report_adjusted_profit_yoy", "adjusted_net_profit_yoy", "deducted_net_profit_yoy", "financial_report_net_profit_yoy", "net_profit_yoy")
        roe = pick("roe_ttm", "roe")
        ocf_np = pick("operating_cashflow_net_profit_ratio", "ocf_to_net_profit")
        debt = pick("debt_ratio", "asset_liability_ratio")
        receivable_yoy = pick("receivable_yoy", "accounts_receivable_yoy")
        inventory_yoy = pick("inventory_yoy")
        audit_bad = _bool(factor.get("audit_opinion_abnormal") or nested.get("audit_opinion_abnormal"))
        major_risk = _bool(factor.get("financial_major_risk") or nested.get("major_risk"))
        available = any(v is not None for v in (revenue_yoy, profit_yoy, roe, ocf_np, debt, receivable_yoy, inventory_yoy)) or audit_bad or major_risk
        if not available:
            return FundamentalState(state="FU", available=False, as_of_date=ann_date or asof, report_period=period, reasons=["fundamental_data_unavailable"])

        score = 50.0
        reasons: List[str] = []
        flags: List[str] = []
        if revenue_yoy is not None:
            score += 10 if revenue_yoy >= 10 else (-12 if revenue_yoy < -10 else 0)
            reasons.append(f"revenue_yoy={revenue_yoy:.1f}%")
        if profit_yoy is not None:
            score += 15 if profit_yoy >= 15 else (-25 if profit_yoy < -30 else (-10 if profit_yoy < 0 else 0))
            reasons.append(f"adjusted_profit_yoy={profit_yoy:.1f}%")
        if roe is not None:
            score += 8 if roe >= 10 else (-6 if roe < 5 else 0)
        if ocf_np is not None:
            score += 8 if ocf_np >= 0.8 else (-15 if ocf_np < 0 else (-8 if ocf_np < 0.5 else 0))
            if ocf_np < 0.5:
                flags.append("WEAK_CASH_CONVERSION")
        if debt is not None and debt >= float(cfg.get("high_debt_ratio", 75) or 75):
            score -= 12
            flags.append("HIGH_LEVERAGE")
        if revenue_yoy is not None and receivable_yoy is not None and receivable_yoy > revenue_yoy + 20:
            score -= 10
            flags.append("RECEIVABLE_GROWTH_DIVERGENCE")
        if revenue_yoy is not None and inventory_yoy is not None and inventory_yoy > revenue_yoy + 25:
            score -= 8
            flags.append("INVENTORY_GROWTH_DIVERGENCE")
        if audit_bad or major_risk:
            score = min(score, 10.0)
            flags.append("MAJOR_FINANCIAL_RISK" if major_risk else "ABNORMAL_AUDIT_OPINION")

        score = _clamp(score)
        if audit_bad or major_risk:
            state, multiplier = "F5", 0.0
        elif score < 35 or (profit_yoy is not None and profit_yoy < -50):
            state, multiplier = "F4", 0.5
        elif score < 50 or flags:
            state, multiplier = "F3", 0.75
        elif score >= 70:
            state, multiplier = "F1", 1.0
        else:
            state, multiplier = "F2", 1.0
        return FundamentalState(
            state=state, score=score, available=True, passed=state not in {"F4", "F5"},
            risk_multiplier=multiplier, as_of_date=ann_date or asof, report_period=period,
            reasons=reasons or ["fundamental_snapshot_available"], risk_flags=flags,
            detail={"ann_date": ann_date, "revenue_yoy": revenue_yoy, "adjusted_profit_yoy": profit_yoy,
                    "roe": roe, "ocf_to_net_profit": ocf_np, "debt_ratio": debt},
        )

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
        # V2.0 买入条件（新增，来自架构蓝图）：Close > MA10 > MA20 + MA10 Slope>0 + 偏离度<=12%。
        close = _num(f.get("close"))
        ma10 = _num(f.get("ma10"))
        ma10_gt_ma20 = f.get("ma10_gt_ma20")
        ma10_slope = _num(f.get("ma10_slope_pct"))
        max_ma10_dev_pct = float(cfg.get("max_ma10_deviation_pct", 12.0) or 12.0)
        close_above_ma10 = bool(close is not None and ma10 is not None and close > ma10)
        if not close_above_ma10 or ma10_gt_ma20 is not True:
            ok = False
            reasons.append(f"close<=ma10或ma10<=ma20:close_above_ma10={close_above_ma10},ma10_gt_ma20={ma10_gt_ma20}")
        if ma10_slope is None or ma10_slope <= 0:
            ok = False
            reasons.append(f"ma10_slope<=0:{ma10_slope}")
        if close_above_ma10 and ma10 is not None and ma10 > 0:
            ma10_dev_pct = (close / ma10 - 1.0) * 100.0
            if ma10_dev_pct > max_ma10_dev_pct:
                ok = False
                reasons.append(f"close距MA10偏离过大:dev={ma10_dev_pct:.1f}%>{max_ma10_dev_pct:.0f}%")
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
        # 市场情绪硬闸：D 级退潮期不新增；缺数据时不误杀。
        if cand.market_sentiment_state and cand.market_sentiment_state.available and not cand.market_sentiment_state.passed:
            ok = False
            reasons.append(f"market_sentiment:{cand.market_sentiment_state.grade}")
        # 热钱 D 不硬杀趋势票，但给明确风险提示，分数和仓位已降权。
        if cand.hot_money_state and cand.hot_money_state.grade == "D":
            reasons.append(f"hot_money_risk:{cand.hot_money_state.risk_flag or 'D'}")
        if cand.fundamental_info and not cand.fundamental_info.passed:
            ok = False
            reasons.append(f"fundamental_risk:{cand.fundamental_info.state}")
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
        # S2 板块共振：默认只降级不硬拒；数据缺失默认放行避免误杀。
        s2_sector_downgrade = bool(cfg.get("s2_sector_downgrade", True))
        s2_sector_missing_lenient = bool(cfg.get("s2_sector_missing_lenient", True))
        s2_sector_min_1d = float(cfg.get("s2_sector_min_1d", 0.0) or 0.0)
        s2_sector_rank_top = float(cfg.get("s2_sector_rank_top", 0.4) or 0.4)
        if s2_sector_rank_top <= 0:
            s2_sector_rank_top = 0.4
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
        is_s3_base = bool(
            (ma20_dev is not None and ma20_dev >= 0)
            and (volume_ratio or 0) <= s3_max_vol
            and (breakout20 or breakout60)
        )
        is_s3 = is_s3_base
        is_s2_general = bool(
            new_high
            and (rs or 50) >= min_s2_rs
            and (volume_ratio or 1) >= min_s2_vol
            and ma_ok
            and ma5_gt
        )
        # ---- S2 板块共振：不强则降级为 S1/S3，不硬拒 ----
        s2_sector_ok = True
        if s2_sector_downgrade and is_s2_general:
            sector_1d = _num(factor.get("sector_1d_return"))
            sector_rank = _num(factor.get("sector_rank"))
            sector_5d = _num(factor.get("sector_5d_return"))
            if sector_1d is None:
                s2_sector_ok = s2_sector_missing_lenient
            else:
                rank_ok = True
                if sector_rank is not None:
                    rank_ok = bool(sector_rank <= max(1, round(s2_sector_rank_top * 100)))
                # 板块当日不弱，或 5 日板块仍为正面 视为共振
                s2_sector_ok = bool(
                    (sector_1d >= s2_sector_min_1d or sector_5d is None or sector_5d >= 0)
                    and rank_ok
                )
            if not s2_sector_ok:
                # S3 中继条件或 S1 启动条件已满足则降级保留候选；否则退 S0/PASS
                reasons.append("S2板块未共振，降级保留")
                if is_s3_base:
                    is_s2_general = False
                    is_s3 = True
                    reasons.append("降级为S3中继")
                elif is_s1:
                    is_s2_general = False
                    reasons.append("降级为S1启动")
                else:
                    is_s2_general = False
                    reasons.append("退S0/PASS")

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
            ma10 = _num(factor.get("ma10"))
            ma10_slope = _num(factor.get("ma10_slope_pct"))
            ret1 = _num(factor.get("ret_1d_pct"))
            if close is None or ma20_dev is None:
                reason_code = "DATA_INCOMPLETE"
                confidence = 0.0
                reasons.append("S0: 关键价格或均线数据不足")
            elif ma20_dev < 0 or (ma10 is not None and close < ma10):
                reason_code = "STRUCTURE_WEAKENING"
                confidence = 0.85
                reasons.append("S0: 均线结构转弱")
            elif (ma10_slope is not None and ma10_slope < 0) or (ma5_slope is not None and ma5_slope < 0) or (
                rs20 is not None and rs60 is not None and rs20 < rs60
            ):
                reason_code = "MOMENTUM_LOSS"
                confidence = 0.7
                reasons.append("S0: 动量或相对强度回落")
            elif ma20_dev >= 0 and (volume_ratio is None or volume_ratio <= 1.0) and (ret1 is None or ret1 <= 1.0):
                reason_code = "NORMAL_PULLBACK"
                confidence = 0.55
                reasons.append("S0: MA20上方缩量整理，可能是正常回踩")
            else:
                reason_code = "NO_VALID_SETUP"
                confidence = 0.5
                reasons.append("S0: 尚未形成有效主升浪")
            detail["reason_code"] = reason_code
            detail["confidence"] = confidence
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
        macd_hist = _num(factor.get("macd_hist"))
        if macd_hist is None:
            macd_hist = _num(factor.get("macd"))
        macd_delta = _num(factor.get("macd_hist_delta"))
        macd_declining = _bool(factor.get("macd_hist_declining_3d"))
        if macd_hist is None:
            macd_momentum = 0.5
        elif macd_hist > 0 and (macd_delta is None or macd_delta >= 0):
            macd_momentum = 1.0
        elif macd_hist > 0:
            macd_momentum = 0.75
        elif macd_delta is not None and macd_delta > 0:
            macd_momentum = 0.4
        else:
            macd_momentum = 0.2
        if macd_declining and macd_hist is not None:
            macd_momentum = min(macd_momentum, 0.35)

        family = {
            "trend_structure": round(trend_struct, 3),
            "breakout_quality": round(breakout, 3),
            "momentum_quality": round(min(1.0, momentum), 3),
            "relative_strength": round(rs_val, 3),
            "volume_price": round(volume, 3),
            "volatility_state": round(volatility, 3),
            "structure": round(structure, 3),
            "macd_momentum": round(macd_momentum, 3),
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
        macd_weight = float(cfg.get("macd_momentum_weight", 4.0) or 0.0)
        score += (trend_struct * 12) + (breakout * 12) + (rs_val * 10) + (momentum * 10) + (volume * 8) + (volatility * 6) + (structure * 5) + (macd_momentum * macd_weight)
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
            f"量价{family['volume_price']:.1f}/波动{family['volatility_state']:.1f}/结构{family['structure']:.1f}/MACD{family['macd_momentum']:.1f}",
            f"TrendQuality={grade}",
        ]
        # 因子族诊断：把 Layer 3 相关矩阵/VIF“代表性因子”挂到 family，但只作为诊断，不改变已去重的计权。
        dedup = factor.get("_factor_family_dedup") or {}
        if dedup:
            reps = dedup.get("representatives") or {}
            high_pairs = dedup.get("correlation", {}).get("high_corr_pairs") or []
            family["factor_family_dedup"] = {
                "status": dedup.get("status"),
                "representatives": reps,
                "high_corr_pairs": high_pairs[:10],
            }
            vifs = dedup.get("vif") or {}
            high_vif = [k for k, v in vifs.items() if v is not None and v >= 5.0]
            if high_vif:
                reasons.append(f"高VIF({len(high_vif)}):{','.join(high_vif[:5])}")
        if market.regime == "C":
            mult *= 0.5
            reasons.append("Regime=C, 质量乘数再降半")
        return TrendQuality(
            grade=grade, score=round(score, 2), family=family, reasons=reasons,
            multiplier=mult, residual_rs_vs_index=residual_index,
            residual_rs_vs_sector=residual_sector,
        )

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
            ex_self_return_pct = _num(factor.get("sector_return_ex_self_1d"))
            if sector_1d >= 3.0 and stock_ret > sector_1d + 5:
                score_ex = 40.0
                ex_self = False
                ex_self_detail = {"note": "个股涨幅远超板块，Ex-Self可能被腐蚀", "stock_ret": stock_ret, "sector_1d": sector_1d}
            elif ex_self_return_pct is not None and ex_self_return_pct >= 0:
                score_ex = 60.0
                ex_self = True
                ex_self_detail = {"ret": ex_self_return_pct, "ex_self": True, "note": "板块剔除本股仍为正"}
            else:
                score_ex = 55.0
                ex_self = True
                ex_self_detail = {"stock_ret": stock_ret, "sector_1d": sector_1d, "ex_self": True}
        else:
            score_ex = 50.0
            ex_self = True
            ex_self_detail = {"no_data": True}
        score = 50.0 + (score_ex - 50.0) * 0.3
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
        # 金融口径 Ex-Self：优先真实剔除本股指标（sector_return_ex_self_* / sector_breadth_ex_self）
        ex_self_return = _num(factor.get("sector_return_ex_self_1d"))
        ex_self_breadth = _num(factor.get("sector_breadth_ex_self"))
        if ex_self_return is not None:
            reasons.append(f"板块Ex-Self收益{ex_self_return:.2f}%")
        if ex_self_breadth is not None:
            reasons.append(f"板块Ex-Self广度{ex_self_breadth*100:.0f}%")
        return SectorState(
            sector_name=sector_name,
            sector_strength_pct=round(sector_1d, 3),
            breadth_pct=_num(factor.get("sector_breadth_score")) or ex_self_breadth,
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
        # 结构化事件字段（用户 spec）：event_level/earnings_impact/credibility/source_quality/company_specific
        event_level = str(catalyst.get("event_level") or level)
        earnings_impact = _num(catalyst.get("earnings_impact"))
        credibility = _num(catalyst.get("credibility"))
        source_quality = str(catalyst.get("source_quality") or "unknown")
        expected_return = _num(catalyst.get("expected_return_pct"))
        actual_return = _num(catalyst.get("actual_return_pct")) or _num(factor.get("change_pct"))
        gap_pct = _num(catalyst.get("gap_pct"))
        intraday_return = _num(catalyst.get("intraday_return_pct"))
        has_event = bool(event_type or level)
        score = 0.0
        reasons = []
        if has_event:
            # Base: 事件本身（不是“收阴=失效”，而看事件质量 × 实际价格反应）
            score += 20
            reasons.append(f"事件:{event_type or event_level}")
            level_score = {"S": 30, "A": 25, "B": 18, "C": 10}.get(str(event_level).upper(), 15) if event_level else 15
            score += level_score
            # 事件特异性与可信度
            if company_specific:
                score += 15
                reasons.append("公司特异")
            if credibility is not None:
                score += min(15.0, 15.0 * credibility)
                reasons.append(f"可信度{credibility:.2f}")
            elif source_quality in ("official", "交易所", "公告"):
                score += 10
                reasons.append(f"来源{source_quality}")
            if earnings_impact is not None:
                score += min(10.0, 10.0 * earnings_impact)
                reasons.append(f"业绩影响{earnings_impact:.2f}")
            # Catalyst × Price Reaction：不危险 Close<Open 直接归零。
            # 正面的实际收益/预期收益比、gap+日内结构共同决定 price reaction 强度。
            reaction_score = 0.0
            if reaction == "positive":
                reaction_score += 15
            elif reaction == "negative":
                reaction_score -= 20
            if actual_return is not None and expected_return is not None:
                reaction_ratio = actual_return / expected_return if expected_return != 0 else 0.0
                reaction_score += max(-15.0, min(15.0, reaction_ratio * 5.0))
                reasons.append(f"实际/预期收益={reaction_ratio:.2f}")
            elif actual_return is not None:
                if actual_return > 3:
                    reaction_score += 12
                elif actual_return > 0:
                    reaction_score += 6
                elif actual_return < -5:
                    reaction_score -= 18
                elif actual_return < 0:
                    reaction_score -= 8
                reasons.append(f"实际收益{actual_return:.2f}%")
            if gap_pct is not None:
                reaction_score += 3.0 if gap_pct > 2 else (-3.0 if gap_pct < -2 else 1.0)
            if intraday_return is not None:
                reaction_score += 3.0 if intraday_return > 1 else (-3.0 if intraday_return < -1 else 1.0)
            score += _clamp(reaction_score, -25.0, 25.0)
            score += min(20.0, freshness * 20.0)
            reasons.append(f"新鲜度{freshness * 100:.0f}%")
            if reaction_score < 0:
                reasons.append("价格反应偏弱")
        # 若无催化，默认中性 50 分，不要求必须有催化（催化是增强不是准入）。
        score = 50.0 if not has_event else _clamp(score)
        detail = {
            "event_level": event_level,
            "credibility": credibility,
            "source_quality": source_quality,
            "earnings_impact": earnings_impact,
            "gap_pct": gap_pct,
            "intraday_return_pct": intraday_return,
            "expected_return_pct": expected_return,
            "actual_return_pct": actual_return,
        }
        return CatalystState(has_event=has_event, event_type=event_type, event_level=event_level, freshness=freshness, company_specific=company_specific, price_reaction=reaction, score=round(score, 2), reasons=reasons, detail={k: v for k, v in detail.items() if v is not None})

    def _candidate_entry_score(self, cand: MTFCandidate) -> float:
        """T日 PreScore，不再把 S2+A 全部顶到 100。"""
        scores = compute_pre_score(
            trend_state=cand.trend_state,
            quality_score=cand.quality_info.score if cand.quality_info else None,
            sector_score=cand.sector_info.score if cand.sector_info else None,
            sector_grade=cand.sector_info.grade if cand.sector_info else "",
            market_sentiment_score=cand.market_sentiment_state.score if cand.market_sentiment_state else None,
            hot_money_score=cand.hot_money_state.score if cand.hot_money_state else None,
            catalyst_score=cand.catalyst_info.score if cand.catalyst_info else cand.catalyst_score,
            has_event=bool(cand.catalyst_info.has_event) if cand.catalyst_info else False,
            weights=scoring_weights(self.config.scoring),
        )
        return float(scores["pre_score"])

    def build_tday_pool(self, eligible: List[MTFCandidate], trade_date: str) -> Dict[str, Any]:
        """T日候选池：Trend/Sector/Catalyst + Reference Price + 动态止损 + 主题敞口。全部 WAIT。"""
        rows = []
        for cand in eligible:
            if not cand.eligible:
                continue
            factor = cand.technical_factor or {}
            risk = self.compute_risk_state(cand, factor, None)
            row = build_tday_row(
                symbol_code=cand.symbol_code,
                symbol_name=cand.symbol_name,
                trade_date=trade_date,
                trend_state=cand.trend_state,
                quality_score=cand.quality_info.score if cand.quality_info else None,
                sector_score=cand.sector_info.score if cand.sector_info else None,
                sector_grade=cand.sector_info.grade if cand.sector_info else "",
                sector_name=cand.sector_name or (cand.sector_info.sector_name if cand.sector_info else ""),
                market_sentiment_score=cand.market_sentiment_state.score if cand.market_sentiment_state else None,
                hot_money_score=cand.hot_money_state.score if cand.hot_money_state else None,
                catalyst_score=cand.catalyst_info.score if cand.catalyst_info else cand.catalyst_score,
                has_event=bool(cand.catalyst_info.has_event) if cand.catalyst_info else False,
                factor=factor,
                raw_position_pct=float(risk.suggested_position_pct or 0.0),
                scoring_cfg=self.config.scoring,
                holding_cfg=self.config.holding,
            )
            if cand.market_sentiment_state:
                row["market_sentiment_grade"] = cand.market_sentiment_state.grade
                row["market_sentiment_score"] = cand.market_sentiment_state.score
                row["market_sentiment_risk"] = cand.market_sentiment_state.risk_sentiment
            if cand.hot_money_state:
                row["hot_money_grade"] = cand.hot_money_state.grade
                row["hot_money_score"] = cand.hot_money_state.score
                row["hot_money_risk_flag"] = cand.hot_money_state.risk_flag
            if cand.fundamental_info:
                row["fundamental_state"] = cand.fundamental_info.state
                row["fundamental_score"] = cand.fundamental_info.score
                row["fundamental_state_info"] = cand.fundamental_info.to_dict()
            rows.append(row)
        out = finalize_tday_pool(rows, portfolio_cfg=self.config.portfolio)
        out["trade_date"] = trade_date
        return out

    # ================= 6. T+1 执行 & 风险预算 =================
    def fetch_execution_realtime(self, symbol_code: str, prefer: str = "auto") -> Dict[str, Any]:
        """拉取 T+1 实时行情：腾讯财经优先，失败则使用手动输入（config/manual_realtime.json / env）。"""
        q = _fetch_realtime_quote(symbol_code, prefer=prefer)
        payload = _build_quote_payload(q)
        if q.source in ("tencent_error", "manual_missing") and q.detail.get("error"):
            payload["realtime_error"] = q.detail.get("error")
        return payload

    def build_buy_signals(
        self,
        eligible: List[MTFCandidate],
        trade_date: str,
        realtime: Optional[Dict[str, Any]] = None,
        phase: str = "tday",
        tday_rows: Optional[List[Dict[str, Any]]] = None,
    ) -> List[BuySignal]:
        cfg = self.config.execution or {}
        tday_no_buy = bool(cfg.get("tday_no_buy", True))
        tday_map = {str(r.get("symbol_code")): r for r in (tday_rows or [])}
        out = []
        for cand in eligible:
            factor = cand.technical_factor or {}
            tday_row = tday_map.get(cand.symbol_code) or {}
            run_t1 = phase == "t1" or (phase != "tday" and bool(cfg.get("use_tencent_realtime")))
            cand_realtime = None
            exec_state = None
            if run_t1:
                if realtime is not None:
                    cand_realtime = realtime
                elif cfg.get("use_tencent_realtime"):
                    cand_realtime = self.fetch_execution_realtime(cand.symbol_code)
                exec_state = self.evaluate_execution_from_factor(cand, factor, realtime=cand_realtime)
                risk = self.compute_risk_state(cand, factor, exec_state)
                ok = bool(cand.eligible and exec_state.confirmed and risk.pass_or_wait)
            else:
                risk = self.compute_risk_state(cand, factor, None)
                ok = False
            reasons = list(cand.reasons)
            if exec_state:
                reasons.extend(exec_state.reasons)
            if tday_no_buy and phase != "t1":
                reasons.append("T日仅候选，T+1 Execution 后才允许 BUY")
            reasons.append(f"风险仓位(单股原始): {risk.suggested_position_pct or 0:.1f}%")
            if cand.market_sentiment_state:
                reasons.append(f"市场情绪{cand.market_sentiment_state.grade}:{cand.market_sentiment_state.score:.1f}")
            if cand.hot_money_state:
                reasons.append(f"热钱{cand.hot_money_state.grade}:{cand.hot_money_state.score:.1f}")
            if cand.fundamental_info:
                reasons.append(f"基本面{cand.fundamental_info.state}:{cand.fundamental_info.score:.1f}")
            pos = tday_row.get("suggested_position_pct")
            if pos is None:
                pos = risk.suggested_position_pct
            gates = {
                "market_regime": GateResult(name="market_regime", passed=cand.market_regime in ("A", "B", "C"), score=cand.market_regime_state.score if cand.market_regime_state else 0, reason=f"regime={cand.market_regime}", detail={}),
                "trend_state": GateResult(name="trend_state", passed=cand.trend_state in ("S1", "S2", "S3"), score=cand.trend_state_info.score if cand.trend_state_info else 0, reason=cand.trend_state, detail={}),
                "trend_quality": GateResult(name="trend_quality", passed=cand.quality_info.grade in ("A", "B"), score=cand.quality_info.score if cand.quality_info else 0, reason=f"quality={cand.trend_quality}", detail={}),
                "sector": GateResult(name="sector", passed=cand.sector_info.passed if cand.sector_info else True, score=cand.sector_info.score if cand.sector_info else 50, reason=cand.sector_info.grade if cand.sector_info else "default", detail={}),
                "market_sentiment": GateResult(name="market_sentiment", passed=cand.market_sentiment_state.passed if cand.market_sentiment_state else True, score=cand.market_sentiment_state.score if cand.market_sentiment_state else 50, reason=cand.market_sentiment_state.grade if cand.market_sentiment_state else "default", detail=cand.market_sentiment_state.to_dict() if cand.market_sentiment_state else {}),
                "hot_money": GateResult(name="hot_money", passed=cand.hot_money_state.passed if cand.hot_money_state else True, score=cand.hot_money_state.score if cand.hot_money_state else 50, reason=cand.hot_money_state.grade if cand.hot_money_state else "default", detail=cand.hot_money_state.to_dict() if cand.hot_money_state else {}),
                "fundamental": GateResult(name="fundamental", passed=cand.fundamental_info.passed if cand.fundamental_info else True, score=cand.fundamental_info.score if cand.fundamental_info else 50, reason=cand.fundamental_info.state if cand.fundamental_info else "FU", detail=cand.fundamental_info.to_dict() if cand.fundamental_info else {}),
                "execution": GateResult(
                    name="execution",
                    passed=bool(exec_state.confirmed) if exec_state else False,
                    score=exec_state.order_flow_score if exec_state else 0,
                    reason="T+1 execution" if exec_state else "T日无 Execution",
                    detail=exec_state.to_dict() if exec_state else {"phase": "PENDING"},
                ),
                "risk": GateResult(name="risk", passed=risk.pass_or_wait, score=0, reason=risk.reason, detail=risk.to_dict()),
            }
            ctx = price_context_from_factor(factor)
            out.append(BuySignal(
                symbol_code=cand.symbol_code,
                symbol_name=cand.symbol_name,
                trade_date=trade_date,
                lifecycle_state="WAIT" if (tday_no_buy and phase != "t1") else ("T+1买入候选" if ok else ("WAIT" if cand.eligible else "PASS")),
                pool_type="主升浪",
                divergence_mode="mtf",
                divergence_score=round(float(tday_row.get("pre_score") or cand.entry_score), 2),
                entry_quality_score=round(float(tday_row.get("pre_score") or cand.entry_score), 2),
                weak_to_strong_score=round(cand.quality_info.score if cand.quality_info else 0, 2),
                t1_buy_score=round(float(tday_row.get("pre_score") or cand.entry_score), 2),
                buy_ready=False if (tday_no_buy and phase != "t1") else ok,
                reasons=reasons,
                candidate="MainTrend",
                gates=gates,
                trend_state=cand.trend_state,
                trend_quality=cand.trend_quality,
                market_regime=cand.market_regime,
                suggested_position_pct=pos,
                stop_loss_pct=0.0,
                take_profit_pct=0.0,
                reference_price=tday_row.get("reference_price") if tday_row.get("reference_price") is not None else ctx.get("close"),
                initial_stop=tday_row.get("initial_stop"),
                trailing_stop=tday_row.get("trailing_stop"),
                current_stop=tday_row.get("current_stop"),
                theme=str(tday_row.get("theme") or ""),
                pre_score=tday_row.get("pre_score"),
                t1_state='WAIT' if (tday_no_buy and phase != "t1") else ('BUY' if ok else 'WAIT'),
                technical_factor=dict(factor),
                sector_state=cand.sector_info.to_dict() if cand.sector_info else None,
                trend_quality_info=cand.quality_info.to_dict() if cand.quality_info else None,
                hot_money_state=cand.hot_money_state.to_dict() if cand.hot_money_state else None,
                market_sentiment_state=cand.market_sentiment_state.to_dict() if cand.market_sentiment_state else None,
                fundamental_state=cand.fundamental_info.to_dict() if cand.fundamental_info else None,
                relative_strength_cross_section_pct=_num(factor.get("relative_strength_cross_section_pct")),
                relative_strength_score=_num(factor.get("relative_strength_score")),
                sector_rank=_num(factor.get("sector_rank")) or _num((cand.sector_info.rank if cand.sector_info else None)),
            ))
        return out

    def evaluate_execution_from_factor(self, cand: MTFCandidate, factor: Dict[str, Any], realtime: Optional[Dict[str, Any]] = None) -> "ExecutionState":
        """Layer 6 执行引擎。

        回测/日线没有 T+1 实时时，用日线 factor 作**先验** Proxy；有 realtime 报价时按两阶段执行确认。
        Phase 1 = Auction Signal（9:25 竞价先验）
        Phase 2 = Real-time Confirmation（价格/VWAP/盘口/指数/板块实时确认）
        """
        from strategies.main_trend.schemas import ExecutionState
        realtime = realtime or {}
        close = _num(realtime.get("price")) or _num(factor.get("close"))
        vwap = _num(realtime.get("vwap")) or _num(factor.get("vwap_20")) or _num(factor.get("vwap"))
        open_ = _num(realtime.get("open")) or _num(factor.get("open"))
        high = _num(realtime.get("high")) or _num(factor.get("high"))
        low = _num(realtime.get("low")) or _num(factor.get("low"))
        prev_close = _num(realtime.get("prev_close")) or _num(factor.get("prev_close"))
        gap_base = prev_close or close or open_
        gap_pct = (open_ / gap_base - 1.0) * 100.0 if open_ and gap_base and gap_base > 0 else None
        if gap_pct is None and open_ and close and open_ != close:
            gap_pct = (open_ / close - 1.0) * 100.0
        # VWAP 承担：实盘和日线统一金融口径 —— price/VWAP 百分位保持稳健
        vwap_hold = close is not None and vwap is not None and vwap > 0 and close >= vwap
        # 盘口/竞价先验
        auction = _num(realtime.get("auction_score")) or 0.0
        if auction == 0.0 and factor.get("auction_score") is not None:
            auction = _num(factor.get("auction_score")) or 0.0
        # 主动买入占比 / 委比
        active_buy_pct = _num(realtime.get("active_buy_pct"))
        bid_ask_raw = _num(realtime.get("bid_ask_imbalance"))
        bid_volume = _num(realtime.get("bid_volume"))
        ask_volume = _num(realtime.get("ask_volume"))
        if bid_ask_raw is None and bid_volume is not None and ask_volume is not None and ask_volume > 0:
            bid_ask_raw = (bid_volume or 0.0) / ask_volume
        order_flow = 50.0
        if _bool(factor.get("rising_volume")):
            order_flow += 20
        if _num(factor.get("pullback_near_vwap")):
            order_flow += 15
        vol = _num(realtime.get("volume_ratio")) or _num(factor.get("volume_ratio"))
        if vol is not None and 1.0 <= vol <= 3.0:
            order_flow += 10
        if active_buy_pct is not None:
            order_flow += (active_buy_pct - 50.0) * 0.25
        if bid_ask_raw is not None:
            imbalance_pct = (bid_ask_raw - 1.0) * 100.0
            order_flow += max(-15.0, min(15.0, imbalance_pct * 0.4))
        # 日内结构：HH/HL、回踩未破、低点失败（Low Break Failure）
        structure = 50.0
        if _bool(factor.get("hh_hl_strict")):
            structure += 20
        if close is not None and low is not None and low < close:
            structure += 10
        bid_recovery = _num(realtime.get("bid_recovery_score")) or _num(realtime.get("pullback_recovery"))
        if bid_recovery is not None:
            structure += float(min(15.0, max(-10.0, bid_recovery)))
        low_break_failure = _num(realtime.get("low_break_failure"))
        if low_break_failure is not None:
            structure += float(min(15.0, max(-15.0, low_break_failure)))
        # Opening Gap 动态进入成本因子
        gap_penalty, gap_reason = self._gap_penalty(cand, gap_pct)
        score = 40.0 + (15.0 if vwap_hold else 0.0) + (order_flow - 50) * 0.3 + (structure - 50) * 0.3 + gap_penalty
        min_confirm = float((self.config.execution or {}).get("min_confirm_score", 60) or 60)
        confirmed = bool(score >= min_confirm and gap_reason != "低开体现弱势")
        phase = "PHASE2_EXECUTE" if confirmed else "ABANDON"
        if not confirmed and gap_reason == "高开进入成本过高，WAIT":
            phase = "CANCEL"
        # Real-time context passed through detail
        reasons = []
        if vwap_hold:
            reasons.append("价格>=VWAP")
        else:
            reasons.append("价格低于VWAP")
        reasons.append(f"OrderFlow={order_flow:.1f}")
        reasons.append(f"IntradayStructure={structure:.1f}")
        if gap_reason:
            reasons.append(gap_reason)
        if realtime.get("source"):
            reasons.append(f"realtime_source={realtime.get('source')}")
        return ExecutionState(
            opening_gap_pct=gap_pct,
            phase=phase,
            auction_score=round(auction, 2),
            index_state=cand.market_regime,
            sector_state=cand.sector_info.grade if cand.sector_info else "",
            vwap_state=vwap_hold,
            order_flow_score=round(order_flow, 2),
            intraday_structure_score=round(structure, 2),
            active_buy_pct=None if active_buy_pct is None else round(active_buy_pct, 2),
            bid_ask_imbalance=None if bid_ask_raw is None else round(bid_ask_raw, 4),
            bid_recovery_score=None if bid_recovery is None else round(float(bid_recovery), 2),
            low_break_failure=None if low_break_failure is None else round(float(low_break_failure), 2),
            gap_penalty=round(gap_penalty, 2),
            confirmed=confirmed,
            abandon_reason="" if confirmed else (gap_reason or "执行未确认"),
            reasons=reasons,
            detail={k: v for k, v in realtime.items() if v is not None},
        )

    def _gap_penalty(self, cand: MTFCandidate, gap_pct: Optional[float]) -> tuple:
        if gap_pct is None:
            return 0.0, "Gap未知"
        if gap_pct >= 5.0:
            # A级 + S2 + 有催化：高开说明是趋势加速，不惩罚；其他强趋势高开限制成本
            if cand.market_regime == "A" and cand.trend_state == "S2" and cand.catalyst_info and cand.catalyst_info.has_event:
                return 0.0, "A级/S2/催化剂高开允许"
            if cand.market_regime in ("A", "B") and cand.trend_state in ("S1", "S2", "S3"):
                return -8.0, "高开但趋势/市场尚可，成本偏高"
            return -15.0, "高开进入成本过高，WAIT"
        if gap_pct >= 2.0:
            return -4.0, "高开在可接受成本区间"
        if gap_pct <= -3.0:
            return -10.0, "低开体现弱势"
        return 0.0, "Gap可控"


    def compute_risk_state(self, cand: MTFCandidate, factor: Dict[str, Any], exec_state: "ExecutionState") -> RiskState:
        """Layer 6 风险预算定仓位。

        Position = AccountRiskBudget / StopDistance * QualityMultiplier
        依次受：单笔风险预算、市场环境风险乘数、趋势质量乘数、执行质量乘数、
        最大单股仓位、流动性上限、板块/组合相关性（预留字段）约束。
        """
        cfg = self.config.risk or {}
        risk_budget = float(cfg.get("risk_budget_pct", 1.0) or 1.0)
        alloc_limit = float(cfg.get("alloc_limit_pct", 100.0) or 100.0)
        lq_limit = float(cfg.get("liquidity_cap_pct", 30.0) or 30.0)
        # 基础风险预算 * 市场 Regime 乘数（C 级减半，D 级禁止）
        sentiment_mult = float(cand.market_sentiment_state.risk_multiplier if cand.market_sentiment_state else 1.0)
        fundamental_mult = float(cand.fundamental_info.risk_multiplier if cand.fundamental_info else 1.0)
        account_risk = risk_budget * float(cand.market_regime_state.risk_multiplier if cand.market_regime_state else 1.0) * sentiment_mult * fundamental_mult
        # 质量乘数：Trend Quality * (执行质量 0/0.85/1.0)
        quality_mult = float(cand.quality_info.multiplier if cand.quality_info else 0.5)
        if cand.hot_money_state:
            if cand.hot_money_state.grade == "A":
                quality_mult *= 1.05
            elif cand.hot_money_state.grade == "C":
                quality_mult *= 0.85
            elif cand.hot_money_state.grade == "D":
                quality_mult *= 0.60
        exec_q = 1.0 if exec_state is None else (0.85 if not exec_state.confirmed else 1.0)
        quality_mult *= exec_q
        stop_pct = float(cfg.get("stop_atr_mult", 2.5) or 2.5)
        atr_pct = _num(factor.get("atr_pct"))
        atr = _num(factor.get("atr"))
        if atr_pct:
            stop_distance_pct = atr_pct * stop_pct
        elif atr and cand.technical_factor.get("close"):
            stop_distance_pct = atr / float(cand.technical_factor.get("close")) * 100.0 * stop_pct
        else:
            stop_distance_pct = 6.0
        max_pos = float(cfg.get("max_position_pct", 50) or 50)
        if stop_distance_pct and stop_distance_pct > 0:
            suggested = account_risk / stop_distance_pct * 100.0 * quality_mult
        else:
            suggested = 0.0
        # 硬约束：最大单股、流动性上限、组合/Regime 上限
        suggested = min(suggested, max_pos, lq_limit, alloc_limit)
        # 风险预算不允许“为了凑仓位去买 B/C”
        pass_ok = bool(suggested > 0.1 and cand.market_regime != "D" and quality_mult > 0)
        reason = f"account_risk={account_risk:.2f}% / stop_distance={stop_distance_pct:.2f}% * Q{quality_mult:.2f} -> pos={suggested:.1f}%"
        detail = {
            "market_regime": cand.market_regime,
            "market_sentiment": cand.market_sentiment_state.grade if cand.market_sentiment_state else "",
            "market_sentiment_multiplier": round(sentiment_mult, 3),
            "trend_state": cand.trend_state,
            "trend_quality": cand.trend_quality,
            "hot_money_grade": cand.hot_money_state.grade if cand.hot_money_state else "",
            "fundamental_state": cand.fundamental_info.state if cand.fundamental_info else "FU",
            "fundamental_multiplier": round(fundamental_mult, 3),
            "execution_quality_multiplier": round(exec_q, 3),
            "alloc_limit_pct": alloc_limit,
            "liquidity_cap_pct": lq_limit,
        }
        return RiskState(
            account_risk_pct=round(account_risk, 4),
            stop_distance_pct=round(stop_distance_pct, 2),
            stop_distance_abs=round(atr * stop_pct, 3) if atr else None,
            quality_multiplier=round(quality_mult, 3),
            suggested_position_pct=round(suggested, 2),
            max_position_pct=max_pos,
            pass_or_wait=pass_ok,
            reason=reason,
            detail=detail,
        )

    # ================= 7. 持仓状态机 =================

    @staticmethod
    def _record_trend_observation(h: Holding, trend: TrendState, trade_date: str) -> None:
        """按交易日推进趋势状态；同日重复运行不重复累计 streak。"""
        old_state = str(h.trend_state or "").upper()
        old_as_of = str(h.trend_state_as_of or "")
        current_state = str(trend.state or "S0").upper()
        same_observation = bool(old_as_of and old_as_of == str(trade_date or ""))
        if same_observation:
            previous_state = h.previous_trend_state
            streak = max(1, int(h.trend_state_streak or 1))
            changed_at = h.trend_state_changed_at or old_as_of
        else:
            previous_state = old_state
            streak = (max(1, int(h.trend_state_streak or 1)) + 1) if old_state == current_state else 1
            changed_at = h.trend_state_changed_at if old_state == current_state else str(trade_date or "")
        h.previous_trend_state = previous_state
        h.trend_state = current_state
        h.trend_state_streak = streak
        h.trend_state_as_of = str(trade_date or "")
        h.trend_state_changed_at = changed_at
        h.trend_state_info = trend.to_dict()
        h.trend_reason_code = str((trend.detail or {}).get("reason_code") or "")
        h.trend_confidence = float(
            (trend.detail or {}).get("confidence")
            or min(1.0, max(0.0, trend.score / 100.0))
        )

    def refresh_holding_factors(
        self,
        holdings: List[Holding],
        trade_date: str = "",
    ) -> List[Holding]:
        """状态更新时用最新因子重算，避免继续用 T 日缓存。"""
        if not holdings:
            return holdings
        try:
            if not trade_date:
                trade_date = get_latest_completed_trading_date("")
        except Exception:
            pass
        start_date, end_date = get_trading_date_range(end_date=trade_date, count=260, include_end=True)
        benchmark = self._load_benchmark(self.config.benchmark_symbol, start_date, end_date)
        sector_snapshot = self._build_sector_snapshot(trade_date)
        sentiment = self.assess_market_sentiment(trade_date)
        for h in holdings:
            try:
                factor = self._factor_for_row(
                    {"symbol_code": h.symbol_code, "symbol_name": h.symbol_name},
                    start_date,
                    end_date,
                    trade_date,
                    benchmark,
                )
                if not factor:
                    factor = {}
                    trend = TrendState(
                        state="S0", score=0.0, reasons=["S0: 当日行情因子不可用"],
                        tradeable=False, action_hint="WATCH",
                        detail={"reason_code": "DATA_INCOMPLETE", "confidence": 0.0},
                    )
                else:
                    factor = enrich_factor_with_sector(factor, sector_snapshot)
                    factor = _enrich_residual_rs(factor) if factor else {}
                    trend = self.assess_trend_state(factor)
                self._record_trend_observation(h, trend, trade_date)
                previous_state = h.previous_trend_state
                streak = h.trend_state_streak
                changed_at = h.trend_state_changed_at
                reason_code = h.trend_reason_code
                confidence = h.trend_confidence
                hot_money = self.assess_hot_money_state(factor, trade_date)
                tp = dict(h.trade_plan or {})
                fundamental = self.assess_fundamental_state({**tp, **factor}, trade_date)
                h.fundamental_state = fundamental.state
                h.fundamental_state_info = fundamental.to_dict()
                rt = dict(h.realtime_quote or {})
                keys = [
                    "ma10", "ma20", "prev_ma20", "prev_ma10", "ma10_slope_pct", "ma20_slope_pct",
                    "volume_ratio", "close", "open", "high", "low", "recent_low_20", "support_1", "support_2",
                    "relative_strength_20d_pct", "relative_strength_60d_pct",
                    "relative_strength_cross_section_pct", "relative_strength_score",
                    "sector_rank", "sector_1d_return", "sector_strength_pct",
                    "close_vs_20d_high_pct", "breakout_20d", "breakout_60d",
                    "atr", "atr_pct", "vwap", "vwap_20", "ret_5d_pct", "ret_20d_pct", "ret_1d_pct",
                    "macd", "macd_hist", "macd_dif", "macd_dea", "macd_hist_prev", "macd_hist_delta", "macd_hist_declining_3d",
                ]
                for k in keys:
                    if k in factor:
                        tp[k] = factor.get(k)
                tp["market_sentiment_grade"] = sentiment.grade
                tp["market_sentiment_score"] = sentiment.score
                tp["market_sentiment_risk"] = sentiment.risk_sentiment
                tp["hot_money_grade"] = hot_money.grade
                tp["hot_money_score"] = hot_money.score
                tp["hot_money_risk_flag"] = hot_money.risk_flag
                tp["fundamental_state"] = fundamental.state
                tp["fundamental_state_info"] = fundamental.to_dict()
                tp["trend_state"] = trend.state
                tp["trend_state_score"] = trend.score
                tp["trend_state_reasons"] = list(trend.reasons)
                tp["trend_state_tradeable"] = trend.tradeable
                tp["previous_trend_state"] = previous_state
                tp["trend_state_streak"] = streak
                tp["trend_state_as_of"] = str(trade_date or "")
                tp["trend_state_changed_at"] = changed_at
                tp["trend_reason_code"] = reason_code
                tp["trend_confidence"] = confidence
                rt["market_sentiment_grade"] = sentiment.grade
                rt["market_sentiment_score"] = sentiment.score
                rt["hot_money_grade"] = hot_money.grade
                rt["hot_money_score"] = hot_money.score
                rt["hot_money_risk_flag"] = hot_money.risk_flag
                rt["fundamental_state"] = fundamental.state
                rt["trend_state"] = trend.state
                rt["trend_state_score"] = trend.score
                rt["vwap"] = _num(factor.get("vwap")) or _num(factor.get("vwap_20")) or rt.get("vwap")
                rt["open"] = _num(factor.get("open")) or rt.get("open")
                rt["high"] = _num(factor.get("high")) or rt.get("high")
                rt["low"] = _num(factor.get("low")) or rt.get("low")
                cur = _num(h.current_price) or _num(tp.get("close"))
                vwap = _num(rt.get("vwap"))
                if cur is not None and vwap is not None and vwap > 0:
                    rt["vwap_state"] = "Above" if cur >= vwap else "Below"
                protect = compute_profit_protect_price(
                    h.entry_price,
                    cur,
                    ma10=_num(factor.get("ma10")) or _num(tp.get("ma10")),
                    vwap=_num(factor.get("vwap")) or _num(factor.get("vwap_20")) or _num(rt.get("vwap")),
                    highest_close=_num(h.highest_close) or _num(tp.get("highest_close")) or cur,
                )
                tp.update(protect)
                h.trade_plan = tp
                h.realtime_quote = rt
                # 标量字段同步，避免状态机只读到旧缓存（状态更新必须用最新因子）。
                if factor.get("ma10") is not None:
                    h.ma10 = _num(factor.get("ma10"))
                if factor.get("ma20") is not None:
                    h.ma20 = _num(factor.get("ma20"))
                if factor.get("prev_ma20") is not None:
                    h.prev_ma20 = _num(factor.get("prev_ma20"))
                if factor.get("close") is not None:
                    h.current_price = _num(factor.get("close")) or h.current_price
                if factor.get("ret_1d_pct") is not None and h.prev_close is None:
                    # prev_close 优先由外部实时数据写回；这里只在缺失时兜底。
                    c = _num(factor.get("close"))
                    r1 = _num(factor.get("ret_1d_pct"))
                    if c is not None and r1 is not None:
                        h.prev_close = round(c / (1 + r1 / 100.0), 4)
            except Exception:
                unavailable = TrendState(
                    state="S0", score=0.0, reasons=["S0: 当日因子刷新异常"],
                    tradeable=False, action_hint="WATCH",
                    detail={"reason_code": "DATA_INCOMPLETE", "confidence": 0.0},
                )
                self._record_trend_observation(h, unavailable, trade_date)
                continue
        return holdings

    def _persist_next_day_guard(self, tp: Dict[str, Any], rt: Dict[str, Any]) -> Dict[str, Any]:
        """把今日的 VWAP / 最高价固化到 trade_plan，供次日作为警戒位使用。

        不写死任何个股：任何 extension 后，明天跌破今日 VWAP -> 记一条“强势扩张失效”；
        明天放量突破今日高点 -> 才可给 ADD。TP 字段命名带 _prev 前缀，避免和最新日数据混。
        """
        tp = dict(tp or {})
        vwap = _num(rt.get("vwap")) or _num(tp.get("vwap")) or _num(tp.get("vwap_20"))
        high = _num(rt.get("high")) or _num(tp.get("high"))
        if vwap is not None and vwap > 0:
            tp["next_day_guard_vwap"] = round(vwap, 4)
        if high is not None and high > 0:
            tp["next_day_guard_high"] = round(high, 4)
        return tp

    def _add_setup_from_holding(self, holding: Holding) -> Dict[str, Any]:
        """AddSetup Layer：信号层，判断“能不能加”。

        A 健康回踩：站上/贴近 MA20 + 缩量止跌 + 未有效跌穿。
        B 放量突破：突破前高 + 放量确认 + RISK_ON。
        C 加速：创阶段新高 + 量价同步 + 偏离度可控 + 大阳实体。

        Sector / RS 在本方法只做“硬性字面判断”的辅助；主判断由
        evaluate_exits 统一调用 _sector_rs_add_ok()，这里保留两名来源。
        """
        cfg = self.config.holding or {}
        add_cfg = cfg.get("add") or {}
        tp = holding.trade_plan or {}
        rt = holding.realtime_quote or {}
        current = _num(holding.current_price) or holding.entry_price
        ma20 = _num(tp.get("ma20")) or _num(holding.ma20)
        prev_ma20 = _num(tp.get("prev_ma20")) or _num(holding.prev_ma20)
        vwap = _num(rt.get("vwap"))
        open_px = _num(rt.get("open"))
        high = _num(rt.get("high")) or _num(holding.highest_price)
        low = _num(rt.get("low"))
        close = _num(tp.get("close")) or current
        volume_ratio = _num(tp.get("volume_ratio")) or _num(rt.get("volume_ratio"))
        prev_close = _num(holding.prev_close) or _num(tp.get("prev_close"))
        close_vs_20d_high_pct = _num(tp.get("close_vs_20d_high_pct")) or _num(rt.get("close_vs_20d_high_pct"))
        close_vs_60d_high_pct = _num(tp.get("close_vs_60d_high_pct")) or _num(rt.get("close_vs_60d_high_pct"))
        market_regime = str(rt.get("market_regime") or tp.get("market_regime") or "").upper()

        A_pullback = False
        B_breakout = False
        C_accel = False

        # A: 健康回踩，未有效跌穿 MA20；MA20 缺失则不判 A
        if ma20 and ma20 > 0:
            a_close_ok = close >= ma20 * 0.98
            a_low_ok = (low is None) or (low > (prev_ma20 or ma20) * 0.98)
            a_vol = volume_ratio is not None and volume_ratio < 0.8
            a_stop = (open_px is None or close is None) or (close > open_px)
            a_new_low = (low is None or prev_close is None) or (low >= prev_close)
            A_pullback = bool(a_close_ok and a_low_ok and a_vol and a_stop and a_new_low)

        # B: 放量突破前高，实体向上突破
        breakout = bool(_bool(tp.get("breakout_20d")) or _bool(tp.get("breakout_60d")) or _bool(rt.get("breakout_20d")))
        prev_high = _num(tp.get("close_vs_20d_high_pct")) or _num(rt.get("close_vs_20d_high_pct"))
        if prev_high is not None and prev_high >= 0 and (close_vs_20d_high_pct is None or close_vs_20d_high_pct >= 0):
            b_volume = volume_ratio is not None and volume_ratio >= 1.5
            b_regime = market_regime in ("", "A", "B", "RISK_ON")
            body = high is not None and open_px is not None and close is not None and high - open_px > 0 and low is not None
            b_body = body and ((close - open_px) >= (high - open_px) * 0.51)
            B_breakout = bool(breakout and b_volume and b_regime and b_body)

        # C: 加速，创新高/贴近新高 + 量价同步 + 未过度偏离 MA20 + 大阳实体
        c_near_new_high = (close_vs_20d_high_pct is not None and close_vs_20d_high_pct >= -0.5) or                           (prev_close is not None and high is not None and high >= prev_close) or                           (current > 0 and holding.highest_price and current >= holding.highest_price * 0.99)
        # 次日警戒：昨天高点被放量突破，则“空中加油”成立，C 类加速更可信。
        prev_high = _num(tp.get("next_day_guard_high"))
        cm = self.config.holding or {}
        exit_cfg = cm.get("exit") or {}
        if exit_cfg.get("use_next_day_guard", True) and prev_high is not None and prev_high > 0:
            c_near_new_high = c_near_new_high or bool(high is not None and high > prev_high)
        if c_near_new_high:
            c_vol_req = float(exit_cfg.get("next_day_guard_add_volume_ratio", 1.2) or 1.2)
            c_vol = volume_ratio is not None and volume_ratio >= c_vol_req
            c_dev = (close is None or ma20 is None or ma20 <= 0) or ((close - ma20) / ma20) < 0.25
            c_body = (high is not None and low is not None and open_px is not None and close is not None and (high - low) > 0
                      and (close - open_px) > (high - low) * 0.6)
            C_accel = bool(c_vol and c_dev and c_body)

        if A_pullback:
            setup = "A"
            evidence = "A健康回踩缩量止跌未破MA20"
            add_reason = "回踩企稳重新突破/重新站上"
        elif B_breakout:
            setup = "B"
            evidence = "B放量突破前高"
            add_reason = "放量突破确认新趋势"
        elif C_accel:
            setup = "C"
            evidence = "C强势加速创新高"
            add_reason = "量价加速确认"
        else:
            return {"ok": False, "setup_class": "", "evidence": "未命中AddSetup", "add_reason": "无新Alpha结构", "uses": {"sector": False, "rs": False}}
        return {
            "ok": True,
            "setup_class": setup,
            "evidence": evidence,
            "add_reason": add_reason,
            "uses": {"sector": True, "rs": True},
            "market_regime": market_regime,
        }

    def _add_confirmation_from_holding(self, holding: Holding) -> Tuple[bool, str]:
        """ADD Confirmation Layer：盘中执行二次确认。

        - 价格在 VWAP 上方 / vwap_state == "Above"；
        - 或回踩恢复 / 盘口承接分。
        缺失数据不再作为“恒真”，直接不确认。
        """
        rt = holding.realtime_quote or {}
        vwap = _num(rt.get("vwap"))
        current = _num(holding.current_price)
        vwap_state = str(rt.get("vwap_state") or "").upper()
        if vwap_state == "ABOVE":
            return True, "价格>VWAP"
        if vwap is not None and vwap > 0 and current is not None and current >= vwap:
            return True, "价格>=VWAP(推导)"
        pull = _num(rt.get("pullback_recovery")) or _num(rt.get("bid_recovery_score"))
        if pull is not None and pull > 0:
            return True, "回踩企稳/盘口承接"
        of = _num(rt.get("order_flow_score"))
        if of is not None and of >= 55:
            return True, "OrderFlow积极"
        if _num(rt.get("bid_recovery_score")) is not None and _num(rt.get("bid_recovery_score")) > 0:
            return True, "盘口回踩恢复"
        return False, "缺有效盘中确认(价格< VWAP或数据缺失)"

    def _sector_rs_add_ok(self, holding: Holding) -> tuple:
        """Sector / RS 硬门槛（合并返回：sector_ok, sector_source, rs_ok, rs_source）。

        金融口径说明：
          - SectorRank 语义越小越强，沿用主流程已有“板块排名 16.0”；
            强板块 rank <= 20（前 20%）。
          - RS 用 cross_section_pct / relative_strength_score；强 RS 要求 >= 80。
          - 数据缺失：若 add.sector_lenient / rs_lenient 默认开启则放行但标记 missing，
            否则强制 false，绝不伪造“数据存在且强”。
        """
        add_cfg = (self.config.holding or {}).get("add") or {}
        tp = holding.trade_plan or {}
        rt = holding.realtime_quote or {}

        # --- Sector ---
        sr = _num(tp.get("sector_rank")) or _num(rt.get("sector_rank")) \
             or _num(tp.get("sector_rank_pct")) or _num(rt.get("sector_rank_pct"))
        sector_ok = None
        sector_source = "missing"
        if sr is not None:
            sector_ok = bool(sr <= 20)
            sector_source = "sector_rank" + ("_strong" if sector_ok else f"_{sr:.1f}_weak")
        else:
            s1d = _num(tp.get("sector_1d_return")) or _num(rt.get("sector_1d_return"))
            if s1d is not None and s1d <= 0:
                sector_ok = False
                sector_source = "sector_1d_nonpositive"
            elif s1d is not None and s1d > 0:
                sector_ok = True
                sector_source = "sector_1d_positive"
        if sector_ok is None:
            # 数据缺失不再放行：板块/RS 缺失就是证据不足。
            sector_ok, sector_source = False, "sector_missing_strict"

        # --- RS ---
        rs_pct = _num(tp.get("relative_strength_cross_section_pct")) or _num(rt.get("relative_strength_cross_section_pct"))
        rs_score = _num(tp.get("relative_strength_score")) or _num(rt.get("relative_strength_score"))
        rs20 = _num(tp.get("relative_strength_20d_pct")) or _num(rt.get("relative_strength_20d_pct"))
        rs60 = _num(tp.get("relative_strength_60d_pct")) or _num(rt.get("relative_strength_60d_pct"))
        rs_ok = None
        rs_source = "missing"
        if rs_pct is not None:
            rs_ok = bool(rs_pct >= 80)
            rs_source = "rs_cross_pct"
        elif rs_score is not None:
            rs_ok = bool(rs_score >= 80)
            rs_source = "rs_score"
        elif rs20 is not None and rs60 is not None:
            rs_ok = bool((rs20 + rs60) / 2.0 >= 80.0)
            rs_source = "rs_20_60"
        if rs_ok is None:
            # 默认严格：RS 数据缺失不能作为“证据驱动型加仓”。
            rs_ok, rs_source = False, "rs_missing_strict"
        return sector_ok, sector_source, rs_ok, rs_source

    def _calculate_add_size(
        self,
        holding: Holding,
        *,
        current_profit_pct: float,
        stop_loss_price: Optional[float],
        current_position_pct: float = 0.0,
        account_risk_pct: float = 1.0,
    ) -> Tuple[float, str]:
        """RiskEngine：加多少（等价值风险加仓法），不决定能否加。

        RiskBudget * ProfitMultiplier / (entry*risk_multiplier)
        利润 > 20% 时风险乘数 1.5，表示用可承受亏损换算手数。
        """
        add_cfg = (self.config.holding or {}).get("add") or {}
        budget = float(add_cfg.get("risk_budget_pct", account_risk_pct) or account_risk_pct)
        profit_mult = 1.5 if current_profit_pct > 20.0 else 1.0
        risk_capital_pct = budget * profit_mult
        entry = _num(holding.entry_price) or 0.0
        stop = _num(stop_loss_price)
        if not stop or stop >= entry:
            return 0.0, "无有效止损/价格结构不合法，无法加仓"
        distance_pct = (entry - stop) / entry * 100.0
        if distance_pct <= 0:
            return 0.0, "止损距离异常"
        max_size = float(add_cfg.get("max_total_position_pct", 50.0) or 50.0)
        size = risk_capital_pct / distance_pct * 100.0
        size = min(size, max(0.0, max_size - current_position_pct))
        return max(0.0, size), f"risk_budget={budget:.2f}%*{profit_mult:.1f}/stopdist={distance_pct:.2f}%"

    # ================= 7. 持仓状态机 =================

    def evaluate_exits(
        self,
        holdings: List[Holding],
        refresh_factors: bool = False,
        trade_date: str = "",
        persist_next_day_guard: bool = True,
    ) -> List[ExitDecision]:
        """Layer 7 持仓状态机：HOLD -> ADD / HOLD / DECAY / REDUCE / EXIT。

        原则（V1）：不预测顶部，只在“趋势结构被破坏 / 风险收益比明显恶化 / 极端风险”时退出。
        与短线 T+3/T+5 分开：允许持有数周甚至更久，不再固定 ±6% 进出。

        V2.0 Exit Priority（高优先级先判断；废弃 MA20 双日确认，停止矩阵搜索）：
          P0 SELL_NOW        extreme_negative_event == true                 -> SELL
          P1 MA10_REDUCE     Close < MA10 && Close >= MA20                  -> REDUCE 50%
          P1 MA20_SELL       Close < MA20                                   -> SELL（次日开盘无条件清仓）
          P2 SELL_TRAILING   close < highest_close - max(6%, 2×ATR%)        -> SELL
          P3 DECAY_REDUCE    decay_signal_count >= threshold                -> REDUCE
          P4 HOLD            以上全部 false

        核心纪律：
          - 只要 Close > MA10，坚定持有。
          - Close 跌破 MA10 但仍在 MA20 之上：减仓 50%（预警减仓，不清仓）。
          - Close 跌破 MA20：不再等双日确认，直接 SELL，次日开盘无条件清仓。
          - Risk Stop / MA20 SELL 在回测中按要求用当日 VWAP 或保守代理平仓，
            禁止用收盘价“完美平仓”。

        ADD 采用三层证据驱动式 Pyramiding：
          Setup（新的趋势确认：健康回踩/A/B/C + 板块/RS 强，不把 ret_pct>0 当开关）
          -> Confirmation（盘中 VWAP / 回踩企稳 / 盘口结构二次确认）
          -> RiskEngine（浮盈只决定本次加多少，不决定能不能加）
        """
        if refresh_factors:
            holdings = self.refresh_holding_factors(holdings, trade_date=trade_date)
        cfg = self.config.holding or {}
        exit_cfg = cfg.get("exit") or {}
        use_fixed_stop = bool(cfg.get("use_fixed_stop", False))
        stop_pct = float(cfg.get("stop_loss_pct", -6.0) or -6.0)
        max_days = int(cfg.get("horizon_days", 10) or 10)
        reduce_pct_advice = float(exit_cfg.get("reduce_pct", 40) or 40)
        decay_signal_threshold = int(exit_cfg.get("decay_signal_threshold", 2) or 2)
        use_ma10_reduce = bool(exit_cfg.get("use_ma10_reduce", True))
        ma10_reduce_pct = float(exit_cfg.get("ma10_reduce_pct", 50) or 50)
        s0_confirm_days = max(2, int(exit_cfg.get("s0_confirm_days", 2) or 2))
        s0_exit_days = max(s0_confirm_days + 1, int(exit_cfg.get("s0_exit_days", 3) or 3))
        s0_exit_min_weak_signals = max(1, int(exit_cfg.get("s0_exit_min_weak_signals", 2) or 2))
        s0_reduce_pct = float(exit_cfg.get("s0_reduce_pct", 40) or 40)
        ma10_max_deviation_pct = float(exit_cfg.get("ma10_max_buy_deviation_pct", 12.0) or 12.0) / 100.0
        ma20_confirm_allow_pct = float(exit_cfg.get("ma20_confirm_allow_pct", 1.0) or 1.0) / 100.0
        use_ma20_confirm = bool(exit_cfg.get("use_ma20_confirm", True))  # 兼容读取，不再用于双日确认
        ma20_confirm_days_cfg = int(exit_cfg.get("ma20_confirm_days", 2) or 2)
        use_trailing_stop = bool(exit_cfg.get("use_trailing_stop", True))
        trailing_min_dd = float(exit_cfg.get("trailing_min_drawdown_pct", 6.0) or 6.0) / 100.0
        trailing_atr_mult = float(exit_cfg.get("trailing_atr_mult", 2.0) or 2.0)
        use_extreme_event_sell = bool(exit_cfg.get("use_extreme_event_sell", True))
        recapture_allowance = float(cfg.get("recapture_allowance_pct", 1.0) or 1.0) / 100.0

        out = []
        for h in holdings:
            current = _num(h.current_price) or h.entry_price
            highest = _num(h.highest_price) or max(current, h.entry_price)
            ret_pct = (current / h.entry_price - 1.0) * 100.0 if h.entry_price else 0.0
            atr_pct = self._atr_pct_from_holding(h)
            atr_val = None
            rt = h.realtime_quote or {}
            atr_val = _num(rt.get("atr")) or _num((h.trade_plan or {}).get("atr"))
            decay = self._trend_decay_score(current, highest, h, cfg)
            decay_signals = self._decay_signal_list(current, highest, h, cfg)
            decay_hit = sum(1 for _name, hit in decay_signals if hit)
            trend_state = str(
                h.trend_state
                or (h.trade_plan or {}).get("trend_state")
                or (h.realtime_quote or {}).get("trend_state")
                or ""
            ).upper()
            trend_reason = ""
            if h.trend_state_info:
                trend_reason = "、".join(h.trend_state_info.get("reasons") or [])
            if not trend_reason:
                trend_reasons = (h.trade_plan or {}).get("trend_state_reasons") or []
                if isinstance(trend_reasons, list):
                    trend_reason = "、".join(str(x) for x in trend_reasons if x)
            trend_tradeable = trend_state in ("S1", "S2", "S3")
            previous_trend_state = str(h.previous_trend_state or "").upper()
            trend_state_streak = max(1, int(h.trend_state_streak or 1)) if trend_state else 0
            trend_reason_code = str(
                h.trend_reason_code
                or ((h.trend_state_info or {}).get("detail") or {}).get("reason_code")
                or (h.trade_plan or {}).get("trend_reason_code")
                or ""
            ).upper()
            trend_confidence = float(
                h.trend_confidence
                or ((h.trend_state_info or {}).get("detail") or {}).get("confidence")
                or (h.trade_plan or {}).get("trend_confidence")
                or 0.0
            )
            fundamental_info = h.fundamental_state_info or (h.trade_plan or {}).get("fundamental_state_info") or {}
            fundamental_state = str(
                h.fundamental_state or fundamental_info.get("state")
                or (h.trade_plan or {}).get("fundamental_state") or "FU"
            ).upper()
            # V2.0：MA10 主导持有，MA20 硬清仓。
            # Close < MA20 不再受“宽容差”或双日确认照顾，否则会重复 -7.83% 滞后回撤。
            ma10_below_today = h.ma10 is not None and current < h.ma10
            ma20_below_today = h.ma20 is not None and current < h.ma20
            ma20_below_prev = h.prev_ma20 is not None and h.prev_close is not None and h.prev_close < h.prev_ma20 * (1 - ma20_confirm_allow_pct)
            if h.prev_ma20 is None and h.prev_close is not None and h.prev_close < (h.ma20 or h.stop_loss_price or h.entry_price) * (1 - ma20_confirm_allow_pct):
                ma20_below_prev = True
            # 废除“双日确认”：只要当日 Close<MA20 即清仓
            ma20_confirmed = bool(ma20_below_today)
            # 最新 MA20 跌破日数（近似，供报告；不再参与退出决策）
            ma20_days = 2 if (ma20_below_today and ma20_below_prev and use_ma20_confirm and ma20_confirm_days_cfg >= 2) else (1 if ma20_below_today else 0)

            # 动态 trailing stop（P2）：Highest_Close - max(6%, 2×ATR%)
            trailing_price = None
            if use_trailing_stop:
                hc = _num(h.highest_close) or highest
                if hc and hc > 0:
                    atr_pct_for_trail = _num(rt.get("atr_pct")) or _num((h.trade_plan or {}).get("atr_pct"))
                    if atr_pct_for_trail is None and atr_val and hc:
                        atr_pct_for_trail = atr_val / hc * 100.0
                    if atr_pct_for_trail is None:
                        atr_pct_for_trail = atr_pct or 4.0
                    trail_dist_pct = max(trailing_min_dd, trailing_atr_mult * atr_pct_for_trail / 100.0)
                    trailing_price = round(hc * (1.0 - trail_dist_pct), 4)

            reasons = []
            action = "hold"
            hv_class, hv_reason = self._classify_high_volume(h, h.trade_plan or {}, h.realtime_quote or {}, current, cfg)
            health = self._holding_health(h, current, hv_class, cfg)
            health_state = str(health["state"])
            health_score = float(health["score"])
            health_signals = list(health["signals"])
            health_weak_count = int(health["weak_count"])
            key_support_broken = bool(health["key_support_broken"])
            extension_holds = (hv_class == "extension")  # 主升浪强势放量不减仓，让位给 ADD/HOLD
            # ADD 三层架构（Setup / Confirmation / Risk Engine），不把 ret_pct 当准入。
            add_setup_pack = self._add_setup_from_holding(h)
            add_conf_ok, add_conf_reason = self._add_confirmation_from_holding(h)
            add_size, add_size_reason = self._calculate_add_size(
                h,
                current_profit_pct=ret_pct,
                stop_loss_price=h.stop_loss_price,
                current_position_pct=float((h.trade_plan or {}).get("suggested_position_pct") or 0.0),
            )
            add_setup_ok = bool(add_setup_pack.get("ok"))
            add_allowed = bool(add_setup_ok and add_conf_ok and decay < 30)
            reentry_ok = add_allowed

            # Sector / RS 硬性门槛（主判断在 helper；不再用 ret_pct）。
            sector_ok, sector_source, rs_ok, rs_source = self._sector_rs_add_ok(h)
            if not sector_ok or not rs_ok:
                add_allowed = False
            pos = PositionState(
                state="HOLD",
                action="hold",
                score=100 - decay,
                reasons=reasons,
                add_allowed=add_allowed,
                entry_reentry_ok=reentry_ok,
                trend_decay_score=decay,
                add_setup=bool(add_setup_ok),
                add_confirmation=add_conf_ok,
                add_signal="ADD_READY" if add_allowed else "",
                add_setup_class=str(add_setup_pack.get("setup_class") or ""),
                add_size_pct=(add_size if add_allowed else 0.0),
                add_reason=(add_size_reason if add_allowed else ""),
                sector_source=sector_source,
                rs_source=rs_source,
                high_volume_class=hv_class,
                high_volume_reason=hv_reason,
                next_day_guard_break_vwap=bool("next_day_guard_break_vwap" in [name for name, hit in decay_signals if hit]),
                next_day_guard_vwap=_num((h.trade_plan or {}).get("next_day_guard_vwap")),
                next_day_guard_high=_num((h.trade_plan or {}).get("next_day_guard_high")),
            )
            reason_list = []
            atr_trail_triggered = False
            recapture_triggered = False
            ma20_warning = False
            exit_level = ""
            exit_class = "HOLD"
            reduce_pct = 0.0
            decay_signals_hit = [name for name, hit in decay_signals if hit]

            # ---------- P4 以下全部 false 时 HOLD ----------
            if use_fixed_stop and ret_pct <= stop_pct:
                action = "sell"
                exit_level = "P0"
                exit_class = "SELL_NOW"
                reason_list.append("跌破固定止损")
            # P0 极端事件
            elif use_extreme_event_sell and self._extreme_event_flag(h):
                action = "sell"
                exit_level = "P0"
                exit_class = "SELL_NOW"
                reason_list.append("极端负面事件/监管/重大风险")
            elif fundamental_state == "F5":
                action = "sell"
                exit_level = "P0"
                exit_class = "SELL_NOW"
                reason_list.append("FundamentalState=F5 重大财务/审计风险，尽快退出")
            # P1：关键结构位优先于 MA10 预警；否则同时破位时只会减仓。
            elif key_support_broken:
                action = "exit"
                exit_level = "P1"
                exit_class = "SELL_CONFIRM"
                reason_list.append("跌破有效关键低点/支撑位，趋势结构破坏，退出")
            # P1 V2.0：MA10 预警减仓（Close<MA10 但 Close>=MA20，趋势给一次纠错机会）
            elif use_ma10_reduce and ma10_below_today and not ma20_below_today:
                action = "reduce"
                exit_level = "P1"
                exit_class = "REDUCE"
                reduce_pct = ma10_reduce_pct
                reason_list.append(f"Close<MA10 但仍在MA20上方 -> 减仓{ma10_reduce_pct:.0f}%")
            # P1b V2.0：MA20 硬约束，单日跌破即次日开盘无条件清仓
            elif ma20_below_today:
                action = "exit"
                exit_level = 'P1'
                exit_class = 'SELL_SELL_MA20' if False else 'SELL_CONFIRM'
                reason_list.append(f"Close跌破MA20 无条件清仓（不再双日确认）")
            # P1c：主升浪状态被最新因子破坏。T日能入池不代表T+1仍可持有。
            elif trend_state == "S5":
                action = "exit"
                exit_level = "P1"
                exit_class = "SELL_CONFIRM"
                reason_list.append("TrendState=S5 趋势破坏，退出")
            elif trend_state == "S4":
                action = "reduce"
                exit_level = "P1"
                exit_class = "REDUCE"
                reduce_pct = s0_reduce_pct
                reason_list.append(f"TrendState=S4 主升末端，减仓{s0_reduce_pct:.0f}%")
            elif trend_state == "S0" and fundamental_state == "F4":
                action = "reduce"
                exit_level = "P1"
                exit_class = "REDUCE"
                reduce_pct = max(50.0, s0_reduce_pct)
                reason_list.append(f"TrendState=S0 且 FundamentalState=F4 同步恶化，减仓{reduce_pct:.0f}%")
            elif trend_state == "S0" and fundamental_state == "F3" and trend_state_streak == 1:
                action = "reduce"
                exit_level = "P1"
                exit_class = "REDUCE"
                reduce_pct = max(25.0, s0_reduce_pct / 2.0)
                reason_list.append(f"TrendState=S0 且 FundamentalState=F3 分化，首日减仓{reduce_pct:.0f}%")
            elif trend_state == "S0" and trend_reason_code == "DATA_INCOMPLETE":
                action = "watch"
                exit_level = "P1"
                exit_class = "HOLD"
                reason_list.append("TrendState=S0 但关键数据不足，仅预警，不据此交易")
            elif (
                trend_state == "S0"
                and trend_state_streak >= s0_exit_days
                and health_weak_count >= s0_exit_min_weak_signals
            ):
                action = "exit"
                exit_level = "P1"
                exit_class = "SELL_CONFIRM"
                reason_list.append(
                    f"TrendState=S0 已连续{trend_state_streak}日且{health_weak_count}项持仓证据恶化，退出"
                )
            elif trend_state == "S0" and trend_state_streak >= s0_confirm_days:
                action = "reduce"
                exit_level = "P1"
                exit_class = "REDUCE"
                reduce_pct = s0_reduce_pct
                reason_list.append(
                    f"TrendState=S0 已连续{trend_state_streak}日确认({trend_reason_code or '未分类'})，减仓{s0_reduce_pct:.0f}%"
                )
            elif trend_state == "S0":
                action = "watch"
                exit_level = "P1"
                exit_class = "HOLD"
                reason_list.append(
                    f"TrendState {previous_trend_state or '-'}→S0 首日({trend_reason_code or '未分类'})，进入WATCH并禁止加仓"
                )
            # P2 ATR trailing stop
            elif use_trailing_stop and trailing_price is not None and current < trailing_price:
                atr_trail_triggered = True
                action = "exit"
                exit_level = "P2"
                exit_class = "SELL_TRAILING"
                reason_list.append("ATR Trailing Stop触发")
                if h.ma20 and current < h.ma20:
                    reason_list.append("且跌破MA20")
                if (
                    h.prev_close is not None
                    and h.current_price is not None
                    and h.prev_close < (h.stop_loss_price or h.entry_price)
                    and current <= h.prev_close * (1 + recapture_allowance)
                ):
                    recapture_triggered = True
                    reason_list.append("且次日无法站回")
            # 兼容旧字段 atr_trailing_stop，避免数据缺失时失效
            elif h.atr_trailing_stop is not None and h.atr_trailing_stop > 0 and current < h.atr_trailing_stop:
                atr_trail_triggered = True
                action = "exit"
                exit_level = "P2"
                exit_class = "SELL_TRAILING"
                reason_list.append("ATR Trailing Stop触发(兼容旧字段)")
            elif decay_hit >= decay_signal_threshold and not extension_holds:
                action = "reduce"
                exit_level = "P3"
                exit_class = "REDUCE"
                reduce_pct = reduce_pct_advice
                reason_list.append(f"趋势衰减(REDUCE {reduce_pct_advice:.0f}%)")
                decay_signals_hit = [name for name, hit in decay_signals if hit]
            elif extension_holds:
                # 放量+收在高位 = 资金共识（强势扩张），不是分歧；REDUCE 自动让位给 HOLD/ADD。
                action = "hold"
                exit_level = "P3"
                exit_class = "HOLD"
                reason_list.append("放量强势扩张(HOLD，非滞涨不减仓)")
            elif h.holding_days >= max_days:
                action = "exit"
                exit_level = "P4"
                exit_class = "SELL_CONFIRM"
                reason_list.append(f"超期{max_days}交易日退出")
            elif (
                h.prev_close is not None
                and h.current_price is not None
                and h.prev_close < (h.stop_loss_price or h.entry_price)
                and current <= h.prev_close * (1 + recapture_allowance)
            ):
                recapture_triggered = True
                action = "exit"
                exit_level = "P2"
                exit_class = "SELL_TRAILING"
                reason_list.append("跌破关键线且次日无法站回")
            elif decay >= float(cfg.get("reduce_decay_threshold", 45) or 45) and not extension_holds:
                action = "reduce"
                exit_level = "P3"
                exit_class = "REDUCE"
                reduce_pct = reduce_pct_advice
                reason_list.append("趋势衰减减仓")
            elif add_allowed and decay < 30:
                action = "add_hint"
                reason_list.append("新趋势确认可加仓")
            else:
                action = "hold"
                fail_bits = []
                if not add_setup_ok:
                    fail_bits.append(str(add_setup_pack.get("evidence") or "未命中AddSetup"))
                elif not add_conf_ok:
                    fail_bits.append(add_conf_reason)
                if not sector_ok or not rs_ok:
                    fail_bits.append(f"{sector_source}/{rs_source}")
                reason_list.append("继续持有" + ("；" + "；".join(fail_bits) if fail_bits else ""))

            if action == 'add_hint':
                pos.state = 'ADD'
                pos.action = 'add'
            elif action == 'reduce':
                pos.state = 'REDUCE'
                pos.action = 'reduce'
            elif action in ('exit', "sell"):
                pos.state = "EXIT"
                pos.action = "exit" if action == "exit" else "sell"
                pos.reasons = reason_list[:]
            elif action == "watch":
                pos.state = "WATCH"
                pos.action = "hold"
                pos.add_allowed = False
                pos.reasons = reason_list[:]
            elif ma20_warning:
                pos.state = "HOLD"
                pos.action = "hold"
                pos.reasons = reason_list[:]
            elif extension_holds and action == "hold":
                # 强势放量扩张：明确 HOLD，不被衰减计数盖成 DECAY。
                pos.state = "HOLD"
                pos.action = "hold"
                pos.reasons = reason_list[:]
            elif decay >= 5:
                pos.state = "DECAY"
                pos.action = "decay"
                pos.reasons = reason_list[:]
            else:
                pos.state = "HOLD"
                pos.action = "hold"

            add_reason_flat = add_size_reason
            if pos.action == "add" and add_setup_pack.get("evidence"):
                add_reason_flat = f"{add_setup_pack.get('evidence')};{add_conf_reason}"
            # 仅在日终固化今日警戒位。盘中多波次可关闭，避免后一波次把
            # 前一波次 VWAP 误当成“昨日 VWAP”。
            next_trade_plan = dict(h.trade_plan or {})
            protect = compute_profit_protect_price(
                h.entry_price,
                current,
                ma10=h.ma10 or _num(next_trade_plan.get("ma10")),
                vwap=_num((h.realtime_quote or {}).get("vwap")) or _num(next_trade_plan.get("vwap")) or _num(next_trade_plan.get("vwap_20")),
                highest_close=_num(h.highest_close) or highest,
            )
            next_trade_plan.update(protect)
            h.trade_plan = next_trade_plan
            if persist_next_day_guard:
                next_trade_plan = self._persist_next_day_guard(next_trade_plan, h.realtime_quote or {})
                h.trade_plan = next_trade_plan

            out.append(ExitDecision(
                symbol_code=h.symbol_code,
                symbol_name=h.symbol_name,
                action=pos.action,
                reason="; ".join(reason_list) if reason_list else "继续持有",
                urgency="high" if pos.action == "exit" or pos.action == "sell" else "normal",
                exit_score=round(100 - decay, 2),
                current_return_pct=round(ret_pct, 2),
                stop_loss_triggered=bool(action == "sell" and exit_class == "SELL_NOW"),
                take_profit_triggered=False,
                reduce_triggered=bool(pos.action == "reduce"),
                add_allowed=pos.add_allowed,
                add_setup=pos.add_setup,
                add_confirmation=pos.add_confirmation,
                add_signal=pos.add_signal,
                add_setup_class=pos.add_setup_class,
                add_size_pct=pos.add_size_pct,
                add_reason=add_reason_flat,
                sector_source=sector_source,
                rs_source=rs_source,
                state=pos.state,
                position_state=pos.state,
                decay_score=round(decay, 2),
                atr_trailing_stop_triggered=atr_trail_triggered,
                recapture_triggered=recapture_triggered,
                exit_level=exit_level,
                exit_class=exit_class,
                reduce_pct=reduce_pct,
                ma20_confirm_days=ma20_days,
                highest_close=_num(h.highest_close) or highest,
                trailing_stop_price=trailing_price,
                decay_signals=[name for name, hit in decay_signals if hit],
                reasons=pos.reasons,
                high_volume_class=hv_class,
                high_volume_reason=hv_reason,
                trend_state=trend_state,
                trend_state_reason=trend_reason,
                previous_trend_state=previous_trend_state,
                trend_state_streak=trend_state_streak,
                trend_reason_code=trend_reason_code,
                trend_confidence=trend_confidence,
                trend_state_as_of=h.trend_state_as_of,
                trend_state_changed_at=h.trend_state_changed_at,
                trend_state_info=h.trend_state_info or {},
                fundamental_state=fundamental_state,
                fundamental_state_info=fundamental_info,
                holding_health=health_state,
                holding_health_score=health_score,
                holding_health_signals=health_signals,
                next_day_guard_break_vwap=bool("next_day_guard_break_vwap" in [name for name, hit in decay_signals if hit]),
                next_day_guard_vwap=_num(next_trade_plan.get("next_day_guard_vwap")),
                next_day_guard_high=_num(next_trade_plan.get("next_day_guard_high")),
                target_price_1=_num(next_trade_plan.get("target_price_1")),
                target_price_2=_num(next_trade_plan.get("target_price_2")),
                profit_protect_price=_num(next_trade_plan.get("profit_protect_price")),
                profit_protect_level=str(next_trade_plan.get("profit_protect_level") or ""),
                profit_protect_reason=str(next_trade_plan.get("profit_protect_reason") or ""),
            ))
        return out

    def _holding_health(
        self,
        holding: Holding,
        current_price: float,
        high_volume_class: str,
        cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        """用独立证据判断持仓是否仍有效，MA20 只作为最后结构防线之一。"""
        tp = holding.trade_plan or {}
        rt = holding.realtime_quote or {}
        exit_cfg = cfg.get("exit") or {}
        signals: List[str] = []
        weak_count = 0

        ma10 = _num(tp.get("ma10")) or _num(holding.ma10)
        ma20 = _num(tp.get("ma20")) or _num(holding.ma20)
        ma10_slope = _num(tp.get("ma10_slope_pct"))
        ma20_slope = _num(tp.get("ma20_slope_pct"))
        rs20 = _num(rt.get("relative_strength_20d_pct")) or _num(tp.get("relative_strength_20d_pct"))
        rs60 = _num(rt.get("relative_strength_60d_pct")) or _num(tp.get("relative_strength_60d_pct"))
        rs_score = _num(rt.get("relative_strength_score")) or _num(tp.get("relative_strength_score"))
        vwap = _num(rt.get("vwap")) or _num(tp.get("vwap")) or _num(tp.get("vwap_20"))

        if ma10_slope is not None and ma10_slope <= float(exit_cfg.get("weak_ma10_slope_pct", 0.0) or 0.0):
            signals.append("ma10_slope_non_positive")
            weak_count += 1
        if ma20_slope is not None and ma20_slope < float(exit_cfg.get("weak_ma20_slope_pct", 0.0) or 0.0):
            signals.append("ma20_slope_negative")
            weak_count += 1
        if rs20 is not None and rs60 is not None and rs20 < rs60:
            signals.append("relative_strength_declining")
            weak_count += 1
        elif rs_score is not None and rs_score < float(exit_cfg.get("weak_rs_score", 40.0) or 40.0):
            signals.append("relative_strength_weak")
            weak_count += 1
        if high_volume_class == "rejection":
            signals.append("high_volume_rejection")
            weak_count += 1
        if vwap is not None and current_price < vwap:
            signals.append("close_below_vwap")
            weak_count += 1
        if ma10 is not None and current_price < ma10:
            signals.append("close_below_ma10")

        # 支撑必须来自刷新因子/交易计划，且应位于当日价格附近；0.5%容差过滤毛刺。
        supports = [_num(tp.get("support_1")), _num(tp.get("recent_low_20")), _num(rt.get("support_1"))]
        supports = [x for x in supports if x is not None and x > 0]
        support = max(supports) if supports else None
        tolerance = float(exit_cfg.get("key_support_break_tolerance_pct", 0.5) or 0.5) / 100.0
        key_support_broken = bool(support is not None and current_price < support * (1 - tolerance))
        if key_support_broken:
            signals.append("key_support_broken")

        if key_support_broken or (ma20 is not None and current_price < ma20):
            state = "BROKEN"
        elif weak_count >= 2:
            state = "WEAKENING"
        elif any(x is not None for x in (ma10, ma20, ma10_slope, ma20_slope, rs20, rs_score, vwap)):
            state = "HEALTHY"
        else:
            state = "UNKNOWN"
        score = max(0.0, 100.0 - weak_count * 20.0 - (40.0 if key_support_broken else 0.0))
        return {
            "state": state,
            "score": score,
            "signals": signals,
            "weak_count": weak_count,
            "key_support_broken": key_support_broken,
        }

    def _atr_pct_from_holding(self, holding: Holding) -> Optional[float]:
        """从 Holding/trade_plan/realtime 中提取 ATR%；用于 trailing stop = max(6%, 2×ATR%)。"""
        realtime = holding.realtime_quote or {}
        atr_pct = _num(realtime.get("atr_pct"))
        if atr_pct is not None:
            return atr_pct
        if holding.trade_plan:
            atr_pct = _num((holding.trade_plan or {}).get("atr_pct"))
        if atr_pct is not None:
            return atr_pct
        # 最后兜底：从 current/ma20/entry 距离一个粗略 ATR 估计，不做精确 K 线拉取
        # 避免 CLI 必须联网。真实实现由持仓构建时填入 atr_pct。
        return 4.0

    def _trend_decay_score(self, current_price: float, highest_price: float, holding: Holding, cfg: Dict[str, Any]) -> float:
        """Trend Decay Score = 离开高点深度 + ATR trailing 接近 + 持仓时长 + 实时盘口弱化 + 市场恶化。

        ATR 高不天然风险，只在“不创新高/回撤扩大/破位”时增高；不预测顶部。
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
            if stop_dist > 0:
                score += min(35.0, max(0.0, stop_dist * 2.0))
        if holding.holding_days >= int(cfg.get("horizon_days", 5) or 5):
            score += 30
        # 实时盘口/弱势加衰减（可选）
        rt = holding.realtime_quote or {}
        of = _num(rt.get("order_flow_score"))
        if of is not None and of < 40:
            score += 15
        regime = str((rt or {}).get("market_regime") or "").upper()
        if regime == "D":
            score += 20
        sentiment_grade = str(rt.get("market_sentiment_grade") or (holding.trade_plan or {}).get("market_sentiment_grade") or "").upper()
        if sentiment_grade == "D":
            score += 18
        elif sentiment_grade == "C":
            score += 8
        hot_grade = str(rt.get("hot_money_grade") or (holding.trade_plan or {}).get("hot_money_grade") or "").upper()
        hot_risk = str(rt.get("hot_money_risk_flag") or (holding.trade_plan or {}).get("hot_money_risk_flag") or "")
        if hot_grade == "D" or hot_risk in {"institution_net_sell", "lhb_net_sell", "frequent_break_limit"}:
            score += 10
        return round(_clamp(score), 2)

    def _extreme_event_flag(self, holding: Holding) -> bool:
        """P0：极端事件/利空快照。Catalyst=EXTREME、Severity=EXTREME 直接 SELL。"""
        ec = holding.event_catalyst or {}
        if not ec:
            return False
        sev = str(ec.get("severity") or "").upper()
        cat = str(ec.get("catalyst") or "").upper()
        flag = str(ec.get("extreme_event") or ec.get("sell_now") or "").upper()
        return bool(sev == "EXTREME" or cat == "EXTREME" or flag in ("TRUE", "1", "YES"))

    def _classify_high_volume(
        self,
        holding: Holding,
        tp: Dict[str, Any],
        rt: Dict[str, Any],
        current_price: float,
        cfg: Dict[str, Any],
    ) -> Tuple[str, str]:
        """高位放量的“有效供给”二分法。

        不写死某只股票，适用于所有主升浪持仓：
          - high_volume_extension  ：强势扩张。放量+收在高位/量价共振，不减仓（P3 HOLD）。
          - high_volume_rejection  ：真正的供给冲击。放量+弱势确认（收在低区/破VWAP/长上影/天量/收阴量比/板块转弱）。
          语义：放量上涨是共识加强，不是分歧；只有放量滞涨才是分歧。
        """
        ret5 = _num(tp.get("ret_5d_pct"))
        ret20 = _num(tp.get("ret_20d_pct"))
        ret1 = _num(rt.get("ret_1d_pct")) or _num(tp.get("ret_1d_pct"))
        # trade_plan 是上一已完成交易日的缓存；盘中判定优先使用实时盘口。
        vol_ratio = _num(rt.get("volume_ratio")) or _num(tp.get("volume_ratio"))
        exit_cfg = (cfg.get("exit") or {})
        min_ret5_check = float(exit_cfg.get("high_volume_min_ret5_for_check", 8.0) or 8.0)
        strong_ret5 = float(exit_cfg.get("high_volume_strong_ret5", 15.0) or 15.0)
        ma20_dev_strong = float(exit_cfg.get("high_volume_ma20_dev_check_pct", 20.0) or 20.0)
        volume_ratio_th = float(exit_cfg.get("high_volume_vol_ratio", 1.5) or 1.5)
        extreme_ratio = float(exit_cfg.get("high_volume_extreme_ratio", 2.5) or 2.5)
        shadow_mult = float(exit_cfg.get("high_volume_upper_shadow_mult", 1.5) or 1.5)
        weak_range = float(exit_cfg.get("high_volume_close_range_weak", 0.40) or 0.40)
        strong_range = float(exit_cfg.get("high_volume_close_range_strong", 0.60) or 0.60)
        close = _num(rt.get("price")) or current_price or _num(tp.get("close"))
        open_px = _num(rt.get("open")) or _num(tp.get("open"))
        high = _num(rt.get("high")) or _num(tp.get("high")) or _num(holding.highest_price)
        low = _num(rt.get("low")) or _num(tp.get("low"))
        ma20 = _num(tp.get("ma20")) or _num(holding.ma20)
        vwap = _num(rt.get("vwap")) or _num(tp.get("vwap")) or _num(rt.get("vwap_20"))
        intraday_structure = _num(rt.get("intraday_structure_score"))
        sector_1d = _num(rt.get("sector_1d_return")) or _num(tp.get("sector_1d_return"))

        # 位置：高位 / 5日明显涨幅
        high_pos = False
        high_reasons = []
        if ret5 is not None and ret5 > strong_ret5:
            high_pos = True
            high_reasons.append(f"5日涨幅{ret5:.1f}%")
        if ma20 and close is not None and ma20 > 0 and ma20_dev_strong:
            dev = (close - ma20) / ma20 * 100.0
            if dev > ma20_dev_strong:
                high_pos = True
                high_reasons.append(f"偏离MA20 {dev:.1f}%")
        if not high_pos and ret5 is not None and ret5 > min_ret5_check:
            high_pos = True
            high_reasons.append(f"5日涨幅>{min_ret5_check:.0f}%")
        if not high_pos and ret20 is not None and ret20 > 25.0:
            high_pos = True
            high_reasons.append("20日涨幅>25%")

        volume_ok = vol_ratio is not None and vol_ratio > volume_ratio_th
        extreme_volume_ok = vol_ratio is not None and vol_ratio > extreme_ratio

        # 弱势确认（满足任一）
        rejected_reasons = []
        if high is not None and low is not None and close is not None and high > low:
            range_pos = (close - low) / (high - low)
            if range_pos < weak_range:
                rejected_reasons.append(f"收盘位于振幅下{range_pos*100:.0f}%")
        if vwap and close is not None and close < vwap:
            rejected_reasons.append("收盘低于VWAP")
        if high is not None and low is not None and open_px is not None and close is not None:
            upper_shadow = high - max(open_px, close)
            body = abs(close - open_px)
            if body > 0 and upper_shadow > body * shadow_mult:
                rejected_reasons.append(f"长上影>实体{shadow_mult:.1f}倍")
        if extreme_volume_ok:
            rejected_reasons.append(f"天量量比{vol_ratio:.1f}>2.5")
        if close is not None and open_px is not None and close < open_px and vol_ratio is not None and vol_ratio > 2.0:
            rejected_reasons.append("冲高收阴且量比>2")
        if sector_1d is not None and sector_1d < -1.0:
            rejected_reasons.append("板块日线转弱")

        # 强势确认（全部满足才 extension）
        extension_reasons = []
        if vwap and close is not None and close >= vwap:
            extension_reasons.append("收盘高于VWAP")
        if high is not None and low is not None and close is not None and high > low:
            range_pos = (close - low) / (high - low)
            if range_pos > strong_range:
                extension_reasons.append(f"收盘位于振幅上{strong_range*100:.0f}%")
        if high is not None and low is not None and open_px is not None and close is not None and (high - low) > 0:
            body_ratio = abs(close - open_px) / (high - low)
            if body_ratio > 0.60:
                extension_reasons.append("实体占比>60%")
        if intraday_structure is not None and intraday_structure >= 60:
            extension_reasons.append("日内结构偏强")

        if high_pos and volume_ok and rejected_reasons:
            return "rejection", ";".join(high_reasons + rejected_reasons)
        if high_pos and volume_ok and extension_reasons:
            return "extension", ";".join(high_reasons + extension_reasons)
        return "neutral", "未触发高位放量减仓/持有信号"


    def _decay_signal_list(self, current_price: float, highest_price: float, holding: Holding, cfg: Dict[str, Any]) -> List[Tuple[str, bool]]:
        """C级趋势衰减信号（REDUCE≥2条触发，不预测顶）。

        ① 5日不创新高
        ② Volume > 1.5 × MA5 Volume
        ③ ATR快速扩大
        ④ RS连续下降
        ⑤ Sector Strength下降
        ⑥ 高位长上影（量价配合不足）
        """
        rt = holding.realtime_quote or {}
        tp = holding.trade_plan or {}
        ret5 = _num(tp.get("ret_5d_pct"))
        ret20 = _num(tp.get("ret_20d_pct"))
        vol_ratio = _num(rt.get("volume_ratio")) or _num(tp.get("volume_ratio"))
        atr_pct = _num(rt.get("atr_pct")) or _num(tp.get("atr_pct"))
        atr_prev = _num(rt.get("atr_prev_pct")) or _num(tp.get("atr_prev_pct"))
        rs20 = _num(rt.get("relative_strength_20d_pct")) or _num(tp.get("relative_strength_20d_pct"))
        rs60 = _num(rt.get("relative_strength_60d_pct")) or _num(tp.get("relative_strength_60d_pct"))
        sector_1d = _num(rt.get("sector_1d_return")) or _num(tp.get("sector_1d_return"))
        macd_hist = _num(rt.get("macd_hist")) or _num(rt.get("macd")) or _num(tp.get("macd_hist")) or _num(tp.get("macd"))
        macd_delta = _num(rt.get("macd_hist_delta")) or _num(tp.get("macd_hist_delta"))
        macd_declining = _bool(rt.get("macd_hist_declining_3d")) or _bool(tp.get("macd_hist_declining_3d"))
        close = _num(rt.get("price")) or current_price or _num(tp.get("close"))
        recent_high = _num(rt.get("close_vs_20d_high_pct"))
        if recent_high is None:
            recent_high = _num(tp.get("close_vs_20d_high_pct"))
        out = []
        no_new_high = recent_high is not None and recent_high < -0.5
        if no_new_high is not None:
            out.append(("no_new_high_5d", bool(no_new_high)))
        out.append(("atr_expansion", bool(atr_pct is not None and atr_prev is not None and atr_pct > atr_prev * 1.05)))
        out.append(("rs_declining", bool(rs20 is not None and rs60 is not None and rs20 < rs60)))
        out.append(("sector_strength_declining", bool(sector_1d is not None and sector_1d < -1.0)))
        exit_cfg = cfg.get("exit") or {}
        if exit_cfg.get("use_macd_decay", True):
            out.append(("macd_momentum_decay", bool((macd_hist is not None and macd_hist < 0) or (macd_delta is not None and macd_delta < 0 and macd_declining))))
        # 高位放量二分：真正供给冲击才减仓；强势扩张绝不因“放量”被盲减。
        hv_class, hv_reason = self._classify_high_volume(holding, tp, rt, current_price, cfg)
        out.append(("high_volume_rejection", hv_class == "rejection"))
        out.append(("high_volume_extension", hv_class == "extension"))
        # 次日警戒：昨日 VWAP/高点被跌破 = 今日扩张失效。仅当开启了 use_next_day_guard。
        if exit_cfg.get("use_next_day_guard", True):
            prev_vwap = _num(tp.get("next_day_guard_vwap"))
            tol_break_pct = float(exit_cfg.get("next_day_guard_break_vwap_tolerance_pct", 0.5) or 0.5)
            if prev_vwap is not None and prev_vwap > 0 and close is not None and close < prev_vwap * (1 - tol_break_pct / 100.0):
                out.append(("next_day_guard_break_vwap", True))
            else:
                out.append(("next_day_guard_break_vwap", False))
        return out

    # ================= 工具 =================
    def _write_result(self, result: Dict[str, Any], output_dir: str) -> None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
