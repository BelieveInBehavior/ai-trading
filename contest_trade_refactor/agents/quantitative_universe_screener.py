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
from utils.sector_enrichment import (
    build_code_sector_snapshot,
    build_sector_snapshot_from_factor_store,
    enrich_factor_with_sector,
    load_industry_map,
)
from utils.strong_stock_lifecycle import evaluate_lifecycle, load_zt_strength_snapshot


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
    require_weinstein_stage2: bool = False
    max_ma20_deviation_pct: float = 60.0
    max_prev_day_gain_pct: float = 15.0
    ma20_deviation_penalty: float = 1.0
    sector_enrichment_enabled: bool = False
    # V2 hard/soft split
    hard_filter_stage_le: int = 4
    hard_min_weekly_score: float = 20.0
    hard_min_relative_score: float = 15.0
    hard_max_ma20_deviation_pct: float = 60.0
    hard_max_prev_day_gain_pct: float = 20.0
    hard_min_relative_20d_pct: float = -60.0
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

        # T+1~T+3 板块强度：快照可插拔；数据不可用时保持中性，不影响主流程。
        sector_map: Dict[str, Dict[str, float]] = {}
        if self.config.sector_enrichment_enabled:
            try:
                industry_map = load_industry_map()
                by_name = build_sector_snapshot_from_factor_store(trade_date=trade_date)
                sector_map = build_code_sector_snapshot(industry_map, by_name, trade_date=trade_date)
                logger.info("板块富化映射启用: {} 只股票有行业板块字段", len(sector_map))
            except Exception as exc:
                logger.warning("板块快照构建失败（保持中性分）: {}", exc)

        zt_snapshot: Dict[str, Dict[str, Any]] = {}
        try:
            zt_snapshot = load_zt_strength_snapshot(trade_date)
            if zt_snapshot:
                logger.info("涨停封单快照启用: {} 只股票", len(zt_snapshot))
        except Exception as exc:
            logger.warning("涨停封单快照加载失败（保持中性分）: {}", exc)

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
                sector_map=sector_map,
                zt_snapshot=zt_snapshot,
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
        # Candidate admission: do NOT let "remaining room" alone dominate.
        # For a momentum/短线 strategy the critical balance is:
        #   forward opportunity (near-term setup + room) AND
        #   market-recognized strength/volume (RS / short-term trend / relative activity)
        # The old pure-room sort pushed defensively-low-extension names to the top
        # and made the Research Agents produce almost no signals.
        passed.sort(
            key=lambda item: (
                (item.get("quantitative_screen") or {}).get("opportunity_rank_score") or 0,
                (item.get("quantitative_screen") or {}).get("forward_opportunity_score") or 0,
                (item.get("quantitative_screen") or {}).get("short_score") or 0,
                -((item.get("quantitative_screen") or {}).get("extension_risk") or 0),
            ),
            reverse=True,
        )
        # If top_k > 0 keep only the top-ranked slice for research; if top_k <= 0,
        # we intentionally do NOT truncate -- the full quantitative passed pool is
        # the research candidate universe.  (The caller can still limit it later.)
        if self.config.top_k and int(self.config.top_k) > 0:
            candidates = passed[: max(1, int(self.config.top_k))]
        else:
            candidates = passed
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
        sector_map: Dict[str, Dict[str, float]] | None = None,
        zt_snapshot: Dict[str, Dict[str, Any]] | None = None,
    ) -> Dict[str, Any] | None:
        async with semaphore:
            return await asyncio.to_thread(
                self._score_one_sync,
                row,
                start_date,
                end_date,
                trade_date,
                benchmark_frame,
                sector_map,
                zt_snapshot,
            )

    def _score_one_sync(
        self,
        row: Dict[str, Any],
        start_date: str,
        end_date: str,
        trade_date: str,
        benchmark_frame: pd.DataFrame,
        sector_map: Dict[str, Dict[str, float]] | None = None,
        zt_snapshot: Dict[str, Dict[str, Any]] | None = None,
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

        factor = enrich_factor_with_sector(factor, sector_map or {})
        lifecycle = evaluate_lifecycle(factor, market_context={}, zt_snapshot=zt_snapshot)
        factor["strong_stock_lifecycle"] = lifecycle
        factor["strong_stock_divergence"] = {
            "divergence_mode": lifecycle.get("divergence_mode"),
            "divergence_score": lifecycle.get("divergence_score"),
            "divergence_pass": lifecycle.get("divergence_pass"),
            "divergence_reasons": lifecycle.get("divergence_reasons"),
        }
        factor["strong_identity_score"] = lifecycle.get("strong_identity_score")
        factor["entry_quality_score"] = lifecycle.get("entry_quality_score")
        factor["weak_to_strong_score"] = lifecycle.get("weak_to_strong_score")
        ev = self._evaluate_quality(factor)
        # Forward-looking snapshot that is no longer purely "remaining room".
        rank_score = ev.get("opportunity_rank_score")
        forward_score = ev.get("forward_opportunity_score")
        legacy_score = (ev.get("score_breakdown") or {}).get("final")
        quantitative_score = (
            rank_score
            if rank_score is not None
            else forward_score if forward_score is not None else 50.0
        )

        return {
            "symbol_code": symbol_code,
            "symbol_name": str(row.get("symbol_name") or raw_code),
            "amount": row.get("amount"),
            "technical_factor": factor,
            "quantitative_score": round(quantitative_score, 2),
            "legacy_trend_score": round(legacy_score, 2) if legacy_score is not None else None,
            "quantitative_screen": ev,
            "screen_eval": ev,
            "strong_stock_lifecycle": lifecycle,
        }

    def _evaluate_quality(self, factor: Dict[str, Any]) -> Dict[str, Any]:
        """Strong-stock lifecycle screen.

        Stage 0 now prioritizes strong identity first, then keeps divergence and
        weak-to-strong quality as progressively stricter ranking signals.
        """
        lifecycle = factor.get("strong_stock_lifecycle") or {}
        hard_failed: List[str] = []
        if not factor.get("data_quality_valid") or factor.get("data_quality_status") != "ok":
            hard_failed.append("data_quality")
        hard_failed.extend(lifecycle.get("hard_failed") or [])

        change_pct = _safe_float(factor.get("change_pct"))
        ma20_dev = _safe_float(factor.get("ma20_deviation_pct"))
        lts = factor.get("long_term_structure") or {}
        ma200_dev = _safe_float(lts.get("ma200_deviation_pct"))
        dist52 = _safe_float(lts.get("distance_to_52w_high_pct"))
        if (
            change_pct is not None
            and change_pct > self.config.hard_max_prev_day_gain_pct
            and not bool(factor.get("breakout_60d"))
        ):
            hard_failed.append("prev_day_too_hot")
        if (
            self.config.hard_max_ma20_deviation_pct
            and ma20_dev is not None
            and ma20_dev > self.config.hard_max_ma20_deviation_pct
        ):
            hard_failed.append("ma20_overextended")
        if ma200_dev is not None and ma200_dev < -35:
            hard_failed.append("long_term_broken")
        if dist52 is not None and dist52 < -60:
            hard_failed.append("distance_52w_extreme")

        weekly_score = _safe_float(factor.get("weekly_trend_score"))
        relative_score = _safe_float(factor.get("relative_strength_score"))
        daily_score = _safe_float(factor.get("daily_entry_score"))
        short_setup_score = _safe_float(factor.get("short_setup_score"))
        rsi = _safe_float(factor.get("rsi"))
        vol_ratio = _safe_float(factor.get("volume_ratio"))
        amount_ratio = _safe_float(factor.get("amount_ratio"))
        ret3 = _safe_float(factor.get("ret_3d_pct"))
        ret5 = _safe_float(factor.get("ret_5d_pct"))
        close_above_ma5 = bool(factor.get("close_above_ma5"))
        ma5_slope = _safe_float(factor.get("ma5_slope_pct"))
        breakout20 = bool(factor.get("breakout_20d"))
        breakout60 = bool(factor.get("breakout_60d"))
        rs20 = _safe_float(factor.get("relative_strength_20d_pct"))
        sector_1d = _safe_float(factor.get("sector_1d_return"))
        sector_3d = _safe_float(factor.get("sector_3d_return"))
        sector_5d = _safe_float(factor.get("sector_5d_return"))
        sector_10d = _safe_float(factor.get("sector_10d_return"))
        sector_rank = _safe_float(factor.get("sector_rank"))
        stock_vs_sector = _safe_float(factor.get("stock_vs_sector_strength"))

        strong_identity = str(lifecycle.get("strong_identity") or "观察股")
        strong_identity_score = _safe_float(lifecycle.get("strong_identity_score")) or 0.0
        divergence_mode = str(lifecycle.get("divergence_mode") or "none")
        divergence_score = _safe_float(lifecycle.get("divergence_score")) or 0.0
        entry_quality_score = _safe_float(lifecycle.get("entry_quality_score")) or 0.0
        weak_to_strong_score = _safe_float(lifecycle.get("weak_to_strong_score")) or 0.0
        lifecycle_state = str(lifecycle.get("lifecycle_state") or "观察池")

        if strong_identity != "观察股" and strong_identity_score < 55:
            hard_failed.append("not_strong_stock")

        momentum_part = 0.0
        if ret3 is not None or ret5 is not None:
            blended = (ret3 if ret3 is not None else 0.0) * 0.4 + (ret5 if ret5 is not None else 0.0) * 0.6
            momentum_part = _band_score(
                blended,
                [-15, -5, 0, 3, 6, 12, 20],
                [0, 15, 30, 45, 55, 75, 85],
            )
        elif rs20 is not None:
            momentum_part = _band_score(rs20, [-10, 0, 5, 10, 20], [15, 35, 55, 70, 85])

        ma5_part = 0.0
        if close_above_ma5:
            ma5_part += 50.0
        if ma5_slope is not None and ma5_slope > 0:
            ma5_part += 30.0
        if ret5 is not None and 1.0 <= ret5 <= 12.0:
            ma5_part += 20.0
        if ret5 is not None and ret5 > 30.0:
            ma5_part -= 20.0
        ma5_part = max(0.0, min(100.0, ma5_part))

        volume_part = _band_score(vol_ratio, [0.8, 1.0, 1.2, 1.5, 2.0], [20, 40, 55, 70, 80]) if vol_ratio is not None else 40.0
        amount_part = _band_score(amount_ratio, [0.8, 1.0, 1.2, 1.5, 2.0], [20, 40, 55, 70, 80]) if amount_ratio is not None else 40.0
        volume_parts = (volume_part + amount_part) / 2.0 if vol_ratio is not None and amount_ratio is not None else (volume_part if vol_ratio is not None else amount_part)

        breakout_part = 75.0 if breakout20 or breakout60 else 50.0
        if rsi is not None and rsi > 85:
            breakout_part -= 25.0
        if ma20_dev is not None and ma20_dev > 20:
            breakout_part -= 20.0
        breakout_part = max(0.0, min(100.0, breakout_part))

        entry_part = _band_score(daily_score, [40, 50, 60, 70, 80], [10, 25, 40, 55, 70, 85])
        short_score = (
            momentum_part * 0.25
            + ma5_part * 0.25
            + volume_parts * 0.20
            + breakout_part * 0.15
            + entry_part * 0.15
        )
        if short_setup_score is not None:
            short_score = short_score * 0.85 + float(short_setup_score) * 0.15
        short_score = max(0.0, min(100.0, short_score))

        long_score = 50.0
        if weekly_score is not None:
            long_score += _band_score(weekly_score, [35, 45, 55, 65, 75, 85], [-12, -2, 10, 20, 30, 40])
        if relative_score is not None:
            long_score += _band_score(relative_score, [35, 45, 55, 65, 75], [-10, 0, 10, 20, 30])
        if rs20 is not None:
            long_score += _band_score(rs20, [-10, 5, 10, 20, 30], [-8, 0, 10, 20, 30])
        long_score = max(0.0, min(100.0, long_score))

        sector_score = 50.0
        if sector_1d is not None:
            sector_score += _band_score(sector_1d, [-2, 0, 1, 3, 4], [-15, 0, 5, 10, 15])
        if sector_3d is not None:
            sector_score += _band_score(sector_3d, [-5, 0, 3, 6, 12], [-15, 0, 8, 10, 20])
        if sector_5d is not None:
            sector_score += _band_score(sector_5d, [-5, 0, 3, 6, 12, 18], [-15, 0, 6, 10, 18, 12])
        if sector_10d is not None:
            sector_score += _band_score(sector_10d, [-8, 0, 5, 10, 15, 22], [-20, 0, 8, 12, 18, 6])
        if sector_rank is not None:
            sector_score += _band_score(sector_rank, [20, 40, 60, 90, 95], [10, 0, -5, -8, -12])
        if stock_vs_sector is not None:
            sector_score += _band_score(stock_vs_sector, [-10, -2, 0, 5, 10], [-12, -5, 0, 8, 15])
        sector_score = max(0.0, min(100.0, sector_score))

        extension_risk = 0.0
        if ma20_dev is not None:
            if ma20_dev > 30:
                extension_risk += 80
            elif ma20_dev > 15:
                extension_risk += 45
            elif ma20_dev > 6:
                extension_risk += 10
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
        sector_peak = max([x for x in (sector_3d, sector_5d, sector_10d) if x is not None] or [0.0])
        if sector_peak >= 12 and sector_rank is not None and sector_rank <= 15:
            extension_risk += 12
        elif sector_peak >= 10:
            extension_risk += 6
        extension_risk = max(0.0, min(100.0, extension_risk))

        room_score = max(0.0, 100.0 - extension_risk)
        forward_opportunity_score = (
            short_score * 0.55
            + room_score * 0.15
            + long_score * 0.10
            + sector_score * 0.20
        )
        forward_opportunity_score = max(0.0, min(100.0, forward_opportunity_score))

        rs_momentum = _band_score((rs20 if rs20 is not None else 0.0), [-10, 0, 5, 10, 20], [10, 30, 40, 70, 88])
        lifecycle_rank_score = max(
            0.0,
            min(100.0, 0.30 * strong_identity_score + 0.30 * divergence_score + 0.20 * entry_quality_score + 0.20 * weak_to_strong_score),
        )
        opportunity_rank_score = (
            short_score * 0.38
            + forward_opportunity_score * 0.17
            + rs_momentum * 0.08
            + sector_score * 0.12
            + long_score * 0.10
            + lifecycle_rank_score * 0.15
        )
        opportunity_rank_score = max(0.0, min(100.0, opportunity_rank_score))
        forward_opportunity_score = max(
            0.0,
            min(100.0, forward_opportunity_score * 0.72 + lifecycle_rank_score * 0.28),
        )

        if strong_identity != "观察股" and lifecycle_state == "T+1买入候选" and not hard_failed:
            pool = "core_buy"
        elif strong_identity != "观察股" and (divergence_score >= 60 or entry_quality_score >= 70 or weak_to_strong_score >= 80):
            pool = "best_opportunity"
        elif strong_identity != "观察股":
            pool = "short_trade"
        elif short_score >= 62:
            pool = "short_trade"
        elif long_score >= 72:
            pool = "long_watch"
        else:
            pool = "watch"

        weekly_bonus = _band_score(weekly_score, [40, 50, 60, 70, 80], [-20, -5, 5, 12, 18, 20]) if weekly_score is not None else 0.0
        rs_bonus = _band_score(relative_score, [40, 50, 60, 70, 80], [-15, -5, 5, 10, 15, 20]) if relative_score is not None else 0.0
        daily_bonus = _band_score(daily_score, [40, 50, 60, 70, 80], [-10, 0, 5, 10, 15, 20]) if daily_score is not None else 0.0
        final_score = max(0.0, min(100.0, 50 + (short_score - 50) * 0.4 + (long_score - 50) * 0.2 - extension_risk * 0.12 + lifecycle_rank_score * 0.24))

        return {
            "passed": len(hard_failed) == 0 and strong_identity != "观察股",
            "hard_failed": hard_failed,
            "pool": pool,
            "strong_identity": strong_identity,
            "strong_identity_score": round(strong_identity_score, 2),
            "strong_identity_reasons": lifecycle.get("strong_identity_reasons") or [],
            "divergence_mode": divergence_mode,
            "divergence_score": round(divergence_score, 2),
            "entry_quality_score": round(entry_quality_score, 2),
            "weak_to_strong_score": round(weak_to_strong_score, 2),
            "lifecycle_state": lifecycle_state,
            "lifecycle_rank_score": round(lifecycle_rank_score, 2),
            "long_score": round(long_score, 2),
            "short_score": round(short_score, 2),
            "sector_score": round(sector_score, 2),
            "extension_risk": round(extension_risk, 2),
            "room_score": round(room_score, 2),
            "forward_opportunity_score": round(forward_opportunity_score, 2),
            "opportunity_rank_score": round(opportunity_rank_score, 2),
            "score_breakdown": {
                "weinstein": 0,
                "weekly": round(weekly_bonus, 2),
                "relative": round(rs_bonus, 2),
                "daily_entry": round(daily_bonus, 2),
                "extension": round(extension_risk, 2),
                "lifecycle": round(lifecycle_rank_score, 2),
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
            "short_setup_score": factor.get("short_setup_score"),
            "ret_3d_pct": factor.get("ret_3d_pct"),
            "ret_5d_pct": factor.get("ret_5d_pct"),
            "close_above_ma5": factor.get("close_above_ma5"),
            "ma5_slope_pct": factor.get("ma5_slope_pct"),
            "breakout_20d": factor.get("breakout_20d"),
            "breakout_60d": factor.get("breakout_60d"),
            "volume_ratio": factor.get("volume_ratio"),
            "amount_ratio": factor.get("amount_ratio"),
            "sector_1d_return": factor.get("sector_1d_return"),
            "sector_3d_return": factor.get("sector_3d_return"),
            "sector_5d_return": factor.get("sector_5d_return"),
            "sector_10d_return": factor.get("sector_10d_return"),
            "sector_rank": factor.get("sector_rank"),
            "stock_vs_sector_strength": factor.get("stock_vs_sector_strength"),
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
            f"通过强势发现+分歧/转强综合条件: {passed_count}",
            (
                '筛选条件：硬过滤=数据质量/一字板/极端过热/长期破烂; '
                f"候选排序=强势身份+分歧质量+转强准备度+量价/板块/长期趋势; "
                f"MA20硬上限={self.config.hard_max_ma20_deviation_pct}%, "
                f"前日硬上限={self.config.hard_max_prev_day_gain_pct}%"
            ),
            "允许 Research Agent 研究的候选:",
        ]
        for index, candidate in enumerate(candidates, start=1):
            factor = candidate["technical_factor"]
            lines.append(
                f"{index}. {candidate['symbol_name']}({candidate['symbol_code']}): "
                f"机会排序分={candidate['quantitative_score']}, "
                f"强势={factor.get('strong_stock_lifecycle', {}).get('strong_identity')}/{factor.get('strong_stock_lifecycle', {}).get('strong_identity_score')}, "
                f"分歧={factor.get('strong_stock_lifecycle', {}).get('divergence_mode')}/{factor.get('strong_stock_lifecycle', {}).get('divergence_score')}, "
                f"转强={factor.get('strong_stock_lifecycle', {}).get('weak_to_strong_score')}, "
                f"入场={factor.get('strong_stock_lifecycle', {}).get('entry_quality_score')}, "
                f"短线分={factor.get('short_setup_score')}, "
                f"5日={factor.get('ret_5d_pct')}%, "
                f"量比={factor.get('volume_ratio')}, "
                f"额比={factor.get('amount_ratio')}, "
                f"RS20={factor.get('relative_strength_20d_pct')}%, "
                f"MA20={factor.get('ma20_deviation_pct')}%, "
                f"涨跌={factor.get('change_pct')}%, "
                f"突破={factor.get('breakout_20d')}"
            )
            if index >= 250:
                lines.append(f"... 候选太多，仅展示前 250 / 共 {len(candidates)} 只 ...")
                break
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
