"""全市场量化预筛选。

先从全市场股票池中计算多周期技术因子，再把通过条件的股票交给研究 Agent。
历史行情使用 JQData（优先）+ AkShare 缓存；首次扫描可能较慢，后续运行会复用缓存。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List

import pandas as pd
from loguru import logger

from data_source.technical_indicators_akshare import (
    compute_stock_technical_factor_from_history,
    _prepare_price_frame,
)
from utils.akshare_utils import akshare_cached
from utils.cn_price_provider import get_index_daily, get_stock_zh_a_hist
from utils.date_utils import get_latest_completed_trading_date, get_trading_date_range


@dataclass
class QuantitativeScreenerConfig:
    enabled: bool = True
    max_symbols: int = 0
    max_concurrency: int = 8
    top_k: int = 80
    history_days: int = 260
    benchmark_symbol: str = "sh000300"
    min_weekly_trend_score: float = 55.0
    min_relative_strength_score: float = 50.0
    min_relative_strength_20d_pct: float = 0.0
    min_daily_entry_score: float = 50.0
    min_amount: float = 0.0
    require_data_quality: bool = True
    require_weinstein_stage2: bool = True
    max_ma20_deviation_pct: float = 60.0
    max_prev_day_gain_pct: float = 15.0
    ma20_deviation_penalty: float = 1.0
    # V2 hard/soft split
    hard_filter_stage_le: int = 4
    hard_min_weekly_score: float = 30.0
    hard_min_relative_score: float = 25.0
    hard_max_ma20_deviation_pct: float = 60.0
    hard_max_prev_day_gain_pct: float = 20.0
    hard_min_relative_20d_pct: float = -50.0
    # Number of top names to hard-label as core_buy for the trade system.
    core_buy_max: int = 5


class QuantitativeUniverseScreener:
    """Build a candidate universe from all currently tradable A-share names."""

    def __init__(self, config: QuantitativeScreenerConfig | None = None):
        self.config = config or QuantitativeScreenerConfig()

    async def screen(self, trigger_time: str) -> Dict[str, Any]:
        if not self.config.enabled:
            return {
                "status": "disabled",
                "trigger_time": trigger_time,
                "trade_date": "",
                "universe_count": 0,
                "scanned_count": 0,
                "passed_count": 0,
                "candidates": [],
                "context_string": "量化预筛选已关闭。",
                "errors": [],
            }

        trade_date = get_latest_completed_trading_date(trigger_time)
        start_date, end_date = get_trading_date_range(
            end_date=trade_date,
            count=max(80, int(self.config.history_days)),
            include_end=True,
        )

        try:
            universe = await asyncio.to_thread(self._load_universe)
        except Exception as exc:
            logger.error("加载全市场股票池失败: {}", exc)
            return self._error_result(trigger_time, trade_date, f"universe_load_failed:{exc}")

        if universe.empty:
            return self._error_result(trigger_time, trade_date, "universe_empty")

        if self.config.max_symbols > 0:
            universe = universe.sort_values(
                "amount",
                ascending=False,
                na_position="last",
            ).head(self.config.max_symbols)

        try:
            benchmark_raw = await asyncio.to_thread(
                get_index_daily,
                self.config.benchmark_symbol,
                start_date,
                end_date,
                False,
            )
            benchmark_frame = _prepare_price_frame(
                benchmark_raw,
                date_columns=("date",),
                close_columns=("close",),
            )
        except Exception as exc:
            logger.error("加载相对强度基准失败: {}", exc)
            return self._error_result(
                trigger_time,
                trade_date,
                f"benchmark_load_failed:{self.config.benchmark_symbol}",
            )

        records = universe.to_dict(orient="records")
        total = len(records)
        semaphore = asyncio.Semaphore(max(1, int(self.config.max_concurrency)))
        progress_lock = asyncio.Lock()
        completed = 0
        results: list[Any] = []
        batch_size = max(100, int(self.config.max_concurrency) * 50)

        async def _score_with_progress(row: Dict[str, Any]) -> Dict[str, Any] | None:
            nonlocal completed
            result = await self._score_one(
                row=row,
                start_date=start_date,
                end_date=end_date,
                trade_date=trade_date,
                benchmark_frame=benchmark_frame,
                semaphore=semaphore,
            )
            async with progress_lock:
                completed += 1
                if completed == 1 or completed % 200 == 0 or completed == total:
                    print(
                        f"Stage 0 progress: {completed}/{total} scanned",
                        flush=True,
                    )
            return result

        for offset in range(0, total, batch_size):
            batch = records[offset : offset + batch_size]
            batch_tasks = [
                asyncio.create_task(_score_with_progress(row)) for row in batch
            ]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            results.extend(batch_results)

        scored = []
        errors = []
        for result in results:
            if isinstance(result, Exception):
                errors.append(type(result).__name__)
            elif result:
                scored.append(result)

        funnel: Dict[str, int] = {}
        for item in scored:
            ev = self._evaluate_quality(item["technical_factor"])
            item["quantitative_screen"] = ev
            item["screen_eval"] = ev
            for reason in (ev.get("hard_failed") or []):
                funnel[reason] = funnel.get(reason, 0) + 1
        passed = [item for item in scored if item["quantitative_screen"].get("passed")]
        passed.sort(key=lambda item: item.get("quantitative_score", 0), reverse=True)
        candidates = passed[: max(1, int(self.config.top_k))]
        funnel["_passed"] = len(passed)

        # Stable core_buy: take the top few from best_opportunity/eligible names by
        # long+short blend, regardless of daily market noise. This turns the
        # str-in-threshold pool into an always-select-core tier.
        core_base = [
            item for item in candidates
            if (item.get("quantitative_screen") or {}).get("pool") in ("core_buy", "best_opportunity")
        ]
        core_base.sort(
            key=lambda item: (
                ((item.get("quantitative_screen") or {}).get("long_score") or 0)
                + ((item.get("quantitative_screen") or {}).get("short_score") or 0) * 0.5
                - ((item.get("quantitative_screen") or {}).get("extension_risk") or 0) * 0.2
            ),
            reverse=True,
        )
        core_buy_set = {id(item) for item in core_base[: max(1, int(self.config.core_buy_max))]}
        for item in candidates:
            if id(item) in core_buy_set:
                if isinstance(item.get("quantitative_screen"), dict):
                    item["quantitative_screen"]["pool"] = "core_buy"
                if isinstance(item.get("screen_eval"), dict):
                    item["screen_eval"]["pool"] = "core_buy"
        context_string = self._build_context(
            trade_date=trade_date,
            universe_count=len(universe),
            scanned_count=len(scored),
            passed_count=len(passed),
            candidates=candidates,
            errors=errors,
        )
        return {
            "status": "ok",
            "trigger_time": trigger_time,
            "trade_date": trade_date,
            "universe_count": int(len(universe)),
            "scanned_count": int(len(scored)),
            "passed_count": int(len(passed)),
            "candidates": candidates,
            "context_string": context_string,
            "errors": errors[:20],
            "screen_funnel": funnel,
        }

    def _load_universe(self) -> pd.DataFrame:
        try:
            raw = akshare_cached.run(
                "stock_zh_a_spot_em",
                {},
                False,
            )
        except Exception:
            raw = akshare_cached.run(
                "stock_info_a_code_name",
                {},
                False,
            )
        if raw is None or raw.empty:
            return pd.DataFrame(columns=["symbol_code", "symbol_name", "amount"])

        code_column = next(
            (column for column in ("代码", "code", "ts_code") if column in raw.columns),
            None,
        )
        name_column = next(
            (column for column in ("名称", "name") if column in raw.columns),
            None,
        )
        amount_column = next(
            (column for column in ("成交额", "amount") if column in raw.columns),
            None,
        )
        if not code_column:
            return pd.DataFrame(columns=["symbol_code", "symbol_name", "amount"])

        result = pd.DataFrame(
            {
                "symbol_code": raw[code_column].map(self._to_symbol_code),
                "symbol_name": raw[name_column] if name_column else raw[code_column],
                "amount": (
                    pd.to_numeric(raw[amount_column], errors="coerce")
                    if amount_column
                    else 0.0
                ),
            }
        )
        result["symbol_name"] = result["symbol_name"].astype(str).str.strip()
        result = result[
            result["symbol_code"].astype(str).str.len().eq(9)
            & ~result["symbol_name"].str.contains("ST|退", case=False, na=False)
            & ~result["symbol_code"].str.startswith(("4", "8", "920"))
        ]
        if self.config.min_amount > 0:
            result = result[result["amount"] >= self.config.min_amount]
        return result.drop_duplicates("symbol_code").reset_index(drop=True)

    async def _score_one(
        self,
        row: Dict[str, Any],
        start_date: str,
        end_date: str,
        trade_date: str,
        benchmark_frame: pd.DataFrame,
        semaphore: asyncio.Semaphore,
    ) -> Dict[str, Any] | None:
        async with semaphore:
            return await asyncio.to_thread(
                self._score_one_sync,
                row,
                start_date,
                end_date,
                trade_date,
                benchmark_frame,
            )

    def _score_one_sync(
        self,
        row: Dict[str, Any],
        start_date: str,
        end_date: str,
        trade_date: str,
        benchmark_frame: pd.DataFrame,
    ) -> Dict[str, Any] | None:
        symbol_code = str(row.get("symbol_code") or "")
        raw_code = symbol_code[:6]
        history = get_stock_zh_a_hist(
            symbol=raw_code,
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
            verbose=False,
        )
        factor = compute_stock_technical_factor_from_history(
            hist_df=history,
            symbol_code=symbol_code,
            symbol_name=str(row.get("symbol_name") or raw_code),
            trade_date=trade_date,
            relative_strength_benchmark=self.config.benchmark_symbol,
            benchmark_frame=benchmark_frame,
        )
        if not factor:
            return None

        ev = self._evaluate_quality(factor)
        final_score = (ev.get("score_breakdown") or {}).get("final")
        quantitative_score = final_score if final_score is not None else 50.0

        return {
            "symbol_code": symbol_code,
            "symbol_name": str(row.get("symbol_name") or raw_code),
            "amount": row.get("amount"),
            "technical_factor": factor,
            "quantitative_score": round(quantitative_score, 2),
            "quantitative_screen": self._evaluate_quality(factor),
            "screen_eval": self._evaluate_quality(factor),
        }

    def _evaluate_quality(self, factor: Dict[str, Any]) -> Dict[str, Any]:
        """V3 dual-axis scoring: long quality x short setup, plus isolated risk."""
        hard_failed: List[str] = []
        if not factor.get("data_quality_valid") or factor.get("data_quality_status") != "ok":
            hard_failed.append("data_quality")
        if not factor.get("weekly_data_available"):
            hard_failed.append("weekly_data_missing")
        if not factor.get("relative_strength_available"):
            hard_failed.append("relative_strength_missing")

        weinstein = str(factor.get("weinstein_stage") or "")
        if weinstein in {"", "N/A", "none", "None"}:
            hard_failed.append("weinstein_missing")
        elif self.config.hard_filter_stage_le and _stage_level(weinstein) >= self.config.hard_filter_stage_le:
            hard_failed.append("weinstein_" + str(weinstein).lower())

        rel20 = _safe_float(factor.get("relative_strength_20d_pct"))
        weekly = _safe_float(factor.get("weekly_trend_score"))
        rel_score = _safe_float(factor.get("relative_strength_score"))
        if rel20 is not None and rel20 < self.config.hard_min_relative_20d_pct:
            hard_failed.append("relative_20d_too_low")
        if weekly is not None and weekly < self.config.hard_min_weekly_score:
            hard_failed.append("weekly_score_too_low")
        if rel_score is not None and rel_score < self.config.hard_min_relative_score:
            hard_failed.append("relative_score_too_low")

        ma20_dev = _safe_float(factor.get("ma20_deviation_pct"))
        change_pct = _safe_float(factor.get("change_pct"))
        if self.config.hard_max_ma20_deviation_pct and ma20_dev is not None and ma20_dev > self.config.hard_max_ma20_deviation_pct:
            hard_failed.append("ma20_overextended")
        if self.config.hard_max_prev_day_gain_pct and change_pct is not None and change_pct > self.config.hard_max_prev_day_gain_pct:
            hard_failed.append("prev_day_too_hot")

        # ------------------------------------------------------------------
        # Basic factors
        # ------------------------------------------------------------------
        weekly_score = _safe_float(factor.get("weekly_trend_score"))
        relative_score = _safe_float(factor.get("relative_strength_score"))
        daily_score = _safe_float(factor.get("daily_entry_score"))
        ma20_dev = _safe_float(factor.get("ma20_deviation_pct"))
        change_pct = _safe_float(factor.get("change_pct"))
        rsi = _safe_float(factor.get("rsi"))
        vol_ratio = _safe_float(factor.get("volume_ratio"))
        rs20 = _safe_float(factor.get("relative_strength_20d_pct"))
        rs60 = _safe_float(factor.get("relative_strength_60d_pct"))
        stock_ret20 = _safe_float(factor.get("stock_return_20d_pct"))
        weekly_ma20_slope = _safe_float(factor.get("weekly_ma20_slope_pct"))
        wein_ma30_slope = _safe_float(factor.get("weinstein_ma30_slope_pct"))
        above_ma30_ratio = _safe_float(factor.get("weinstein_above_ma30_ratio_8w"))
        lts = factor.get("long_term_structure") or {}
        ma50_dev = _safe_float(lts.get("ma50_deviation_pct"))
        ma200_dev = _safe_float(lts.get("ma200_deviation_pct"))
        dist52 = _safe_float(lts.get("distance_to_52w_high_pct"))
        ma50_slope = _safe_float(lts.get("ma50_slope_pct"))

        # ------------------------------------------------------------------
        # Long-Term Score (position): MA20 deviation does NOT participate.
        # ------------------------------------------------------------------
        weekly_long = _band_score(weekly_score, [40,50,60,70,80], [10,30,50,70,85,100])
        stage_long = _band_score(_weinstein_score(weinstein), [-30,-10,0,10,15], [10,20,40,80,95,100])
        rs_long = _band_score(relative_score, [40,50,60,70,80], [10,30,50,70,85,100])

        long_structural = 0.0
        if weekly_ma20_slope is not None:
            long_structural += _band_score(weekly_ma20_slope, [0,1,2,4,6], [20,35,55,75,90,100]) * 0.4
        if wein_ma30_slope is not None:
            long_structural += _band_score(wein_ma30_slope, [0,1,2,4,8], [20,35,55,75,90,100]) * 0.3
        if ma50_slope is not None:
            long_structural += _band_score(ma50_slope, [0,1,3,5,8], [20,35,55,75,90]) * 0.3
        elif ma50_dev is not None:
            long_structural += _band_score(ma50_dev, [-3,0,3,8,15], [20,35,55,75,90]) * 0.3
        if ma200_dev is not None:
            long_structural += _band_score(ma200_dev, [-3,0,5,15,30], [10,30,50,75,90]) * 0.3
        if dist52 is not None:
            long_structural += _band_score(dist52, [-40,-20,-10,-3,0], [15,30,45,70,90]) * 0.4
        if above_ma30_ratio is not None:
            long_structural += _band_score(above_ma30_ratio, [0.5,0.7,0.9,1.0], [0,10,30,40]) * 0.0
        # 平均化结构分量，而不是叠加到 100+
        if long_structural > 0:
            # count how many structure factors present
            factors_present = sum([
                weekly_ma20_slope is not None,
                wein_ma30_slope is not None,
                ma50_slope is not None or ma50_dev is not None,
                ma200_dev is not None,
                dist52 is not None,
            ])
            if factors_present > 0:
                long_structural /= max(1.0, float(factors_present))
        elif rs60 is not None:
            long_structural = _band_score(rs60, [0,5,10,20,35], [15,30,55,75,90])

        long_score = weekly_long * 0.30 + stage_long * 0.20 + rs_long * 0.20 + long_structural * 0.30
        long_score = max(0.0, min(100.0, long_score))

        # ------------------------------------------------------------------
        # Short-Term Setup Score: does current window offer a good buy?
        # ------------------------------------------------------------------
        entry_part = _band_score(daily_score, [40,50,60,70,80], [10,25,40,55,70,85])

        momentum_part = 0.0
        if rs20 is not None and rs60 is not None:
            momentum_part = (
                _band_score(rs20, [-5,0,5,10,20], [10,25,40,60,80])
                + _band_score(rs60, [-5,0,5,10,20], [10,25,40,60,80])
            ) / 2.0
        elif stock_ret20 is not None:
            momentum_part = _band_score(stock_ret20, [-10,0,5,15,30], [10,30,50,75,90])
        else:
            momentum_part = 40.0

        volume_part = _band_score(vol_ratio, [0.8,1.0,1.2,1.5,2.0], [20,40,55,70,80]) if vol_ratio is not None else 40.0
        ma20_position = _band_score(ma20_dev, [0,3,6,10,15], [70,85,95,80,60]) if ma20_dev is not None else 50.0

        # breakout/pullback heuristic from current daily scores + RSI
        breakout_part = 50.0
        if ma20_dev is not None and ma20_dev > 0 and rsi is not None:
            breakout_part = _band_score(rsi, [30,45,60,75], [45,60,75,70])
        elif ma20_dev is not None and ma20_dev < -3:
            breakout_part = 25.0

        short_score = (
            entry_part * 0.35
            + momentum_part * 0.25
            + volume_part * 0.15
            + ma20_position * 0.15
            + breakout_part * 0.10
        )
        short_score = max(0.0, min(100.0, short_score))

        # ------------------------------------------------------------------
        # Extension Risk [0,100] isolated from score
        # ------------------------------------------------------------------
        extension_risk = 0.0
        if ma20_dev is not None:
            if ma20_dev <= 6:
                extension_risk += 0
            elif ma20_dev <= 15:
                extension_risk += 10
            elif ma20_dev <= 30:
                extension_risk += 45
            else:
                extension_risk += 80
        if change_pct is not None:
            if change_pct > 20:
                extension_risk += 30
            elif change_pct > 10:
                extension_risk += 25
            elif change_pct > 5:
                extension_risk += 10
        if rsi is not None:
            if rsi > 85:
                extension_risk += 10
            elif rsi > 75:
                extension_risk += 5
        extension_risk = max(0.0, min(100.0, extension_risk))

        # ------------------------------------------------------------------
        # Pools: do NOT collapse to a single final score.
        # core_buy = top tier for trading (validated by 8/11->8/13 backtest),
        # best_opportunity = wide watch pool.
        # ------------------------------------------------------------------
        if long_score >= 80 and short_score >= 75:
            pool = "core_buy"
        elif long_score >= 72 and short_score >= 65:
            pool = "best_opportunity"
        elif long_score >= 72:
            pool = "long_watch"
        elif short_score >= 65:
            pool = "short_trade"
        else:
            pool = "watch"

        # Backward-compatible fields
        weekly_bonus = _band_score(weekly_score, [40,50,60,70,80], [-20,-5,5,12,18,20])
        rs_bonus = _band_score(relative_score, [40,50,60,70,80], [-15,-5,5,10,15,20])
        daily_bonus = _band_score(daily_score, [40,50,60,70,80], [-10,0,5,10,15,20])
        stage_bonus = _weinstein_score(weinstein)
        extension = _extension_penalty(ma20_dev, change_pct, rsi)
        base_raw = weekly_bonus * 0.4 + stage_bonus * 0.2 + rs_bonus * 0.2 + daily_bonus * 0.2
        final_raw = base_raw - extension * 0.6
        final_score = max(0.0, min(100.0, 50 + final_raw))

        return {
            "passed": len(hard_failed) == 0,
            "hard_failed": hard_failed,
            "pool": pool,
            "long_score": round(long_score, 2),
            "short_score": round(short_score, 2),
            "extension_risk": round(extension_risk, 2),
            "score_breakdown": {
                "weinstein": round(stage_bonus, 2),
                "weekly": round(weekly_bonus, 2),
                "relative": round(rs_bonus, 2),
                "daily_entry": round(daily_bonus, 2),
                "extension": round(extension, 2),
                "final": round(final_score, 2),
            },
            "reason": "ok" if not hard_failed else ";".join(hard_failed),
        }


    def _passes(self, factor: Dict[str, Any]) -> bool:
        return bool(self._evaluate_quality(factor).get("passed", False))

    def _screen_reasons(self, factor: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "weekly_trend_score": factor.get("weekly_trend_score"),
            "weekly_trend": factor.get("weekly_trend"),
            "relative_strength_score": factor.get("relative_strength_score"),
            "relative_strength_20d_pct": factor.get("relative_strength_20d_pct"),
            "relative_strength_60d_pct": factor.get("relative_strength_60d_pct"),
            "daily_entry_score": factor.get("daily_entry_score"),
            "ma20_deviation_pct": factor.get("ma20_deviation_pct"),
            "change_pct": factor.get("change_pct"),
            "data_quality_valid": factor.get("data_quality_valid"),
            "data_quality_errors": factor.get("data_quality_errors"),
            "weinstein_stage": factor.get("weinstein_stage"),
            "weinstein_stage_score": factor.get("weinstein_stage_score"),
        }

    def _build_context(
        self,
        trade_date: str,
        universe_count: int,
        scanned_count: int,
        passed_count: int,
        candidates: List[Dict[str, Any]],
        errors: List[str],
    ) -> str:
        lines = [
            f"全市场量化预筛选报告 ({trade_date})",
            f"股票池数量: {universe_count}",
            f"成功计算多周期因子: {scanned_count}",
            f"通过周线+相对强度+日线条件: {passed_count}",
            (
                '筛选条件：硬过滤=数据质量/周线可用/极端坏趋势; '
                f"评分=周线+RS+Weinstein+日线-过度延伸; "
                f"MA20硬上限={self.config.hard_max_ma20_deviation_pct}%, "
                f"前日硬上限={self.config.hard_max_prev_day_gain_pct}%"
            ),
            "允许 Research Agent 研究的候选:",
        ]
        for index, candidate in enumerate(candidates, start=1):
            factor = candidate["technical_factor"]
            lines.append(
                f"{index}. {candidate['symbol_name']}({candidate['symbol_code']}): "
                f"量化分={candidate['quantitative_score']}, "
                f"周线={factor.get('weekly_trend')}/{factor.get('weekly_trend_score')}, "
                f"RS20={factor.get('relative_strength_20d_pct')}%, "
                f"RS60={factor.get('relative_strength_60d_pct')}%, "
                f"日线={factor.get('daily_entry_score')}, "
                f"MA20偏离={factor.get('ma20_deviation_pct')}%, "
                f"前日涨跌={factor.get('change_pct')}%, "
                f"温斯坦={factor.get('weinstein_stage')}"
            )
        if errors:
            lines.append(f"部分股票计算失败数量: {len(errors)}")
        return "\n".join(lines)

    @staticmethod
    def _to_symbol_code(value: Any) -> str:
        text = str(value or "").strip()
        digits = "".join(char for char in text if char.isdigit())
        if len(digits) < 6:
            return ""
        code = digits[-6:]
        suffix = ".SH" if code.startswith("6") else ".SZ"
        return f"{code}{suffix}"

    @staticmethod
    def _error_result(trigger_time: str, trade_date: str, error: str) -> Dict[str, Any]:
        return {
            "status": "error",
            "trigger_time": trigger_time,
            "trade_date": trade_date,
            "universe_count": 0,
            "scanned_count": 0,
            "passed_count": 0,
            "candidates": [],
            "context_string": f"全市场量化预筛选失败: {error}",
            "errors": [error],
        }


def _safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _band_score(value, cuts, scores):
    if value is None:
        return 0.0
    for cut, score in zip(cuts, scores):
        if value < cut:
            return score
    return scores[-1]


def _stage_level(stage: str):
    stage = str(stage or "").replace(" ", "").lower()
    if "stage_4" in stage or "stage4" in stage or "stage 4" in stage:
        return 4
    if "stage_3" in stage or "stage3" in stage or "stage 3" in stage:
        return 3
    if "stage_2" in stage or "stage2" in stage or "stage 2" in stage:
        return 2
    if "stage_1" in stage or "stage1" in stage or "stage 1" in stage:
        return 1
    return 0


def _weinstein_score(stage: str) -> float:
    level = _stage_level(stage)
    if level == 2:
        return 15.0
    if level == 1:
        return 10.0
    if level == 3:
        return -10.0
    if level == 4:
        return -30.0
    return 0.0


def _extension_penalty(ma20_dev, change_pct, rsi) -> float:
    """Monotonic, positive risk score (higher = more dangerous).

    Roughly matches the product boundary:
      MA20  <=6 ideal, 6-15 mild, 15-30 risk, 30-60 high,
            >60 hard-filtered elsewhere (returned 20 for safety).
      Daily <=5 normal, 5-10 mild, 10-20 high, >20 hard-filtered elsewhere.
    """
    risk = 0.0
    if ma20_dev is not None:
        if ma20_dev <= 6:
            risk += 0.0
        elif ma20_dev <= 15:
            risk += 3.0
        elif ma20_dev <= 30:
            risk += 7.0
        elif ma20_dev <= 60:
            risk += 13.0
        else:
            risk += 20.0
    if change_pct is not None:
        if change_pct <= 5:
            risk += 0.0
        elif change_pct <= 10:
            risk += 2.0
        elif change_pct <= 20:
            risk += 6.0
        else:
            risk += 14.0
    if rsi is not None:
        if rsi > 85:
            risk += 4.0
        elif rsi > 75:
            risk += 1.5
        elif rsi < 30:
            risk += 1.0
    return risk
