"""全市场量化预筛选。

先从全市场股票池中计算多周期技术因子，再把通过条件的股票交给研究 Agent。
历史行情使用 AkShare 缓存；首次扫描可能较慢，后续运行会复用缓存。
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
                akshare_cached.run,
                "stock_zh_index_daily",
                {"symbol": self.config.benchmark_symbol},
                False,
            )
            benchmark_frame = _prepare_price_frame(
                benchmark_raw,
                date_columns=("date", "日期"),
                close_columns=("close", "收盘"),
            )
        except Exception as exc:
            logger.error("加载相对强度基准失败: {}", exc)
            return self._error_result(
                trigger_time,
                trade_date,
                f"benchmark_load_failed:{self.config.benchmark_symbol}",
            )

        semaphore = asyncio.Semaphore(max(1, int(self.config.max_concurrency)))
        tasks = [
            asyncio.create_task(
                self._score_one(
                    row=row,
                    start_date=start_date,
                    end_date=end_date,
                    trade_date=trade_date,
                    benchmark_frame=benchmark_frame,
                    semaphore=semaphore,
                )
            )
            for row in universe.to_dict(orient="records")
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        scored = []
        errors = []
        for result in results:
            if isinstance(result, Exception):
                errors.append(type(result).__name__)
            elif result:
                scored.append(result)

        passed = [
            item
            for item in scored
            if self._passes(item["technical_factor"])
        ]
        passed.sort(key=lambda item: item["quantitative_score"], reverse=True)
        candidates = passed[: max(1, int(self.config.top_k))]
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
            & ~result["symbol_code"].str.startswith(("4", "8"))
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
        history = akshare_cached.run(
            "stock_zh_a_hist",
            {
                "symbol": raw_code,
                "period": "daily",
                "start_date": start_date,
                "end_date": end_date,
                "adjust": "qfq",
            },
            False,
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
        weekly_score = float(factor.get("weekly_trend_score") or 0.0)
        relative_score = float(factor.get("relative_strength_score") or 0.0)
        daily_score = float(factor.get("daily_entry_score") or 0.0)
        quantitative_score = (
            weekly_score * 0.4
            + relative_score * 0.4
            + daily_score * 0.2
        )
        return {
            "symbol_code": symbol_code,
            "symbol_name": str(row.get("symbol_name") or raw_code),
            "amount": row.get("amount"),
            "technical_factor": factor,
            "quantitative_score": round(quantitative_score, 2),
            "quantitative_screen": self._screen_reasons(factor),
        }

    def _passes(self, factor: Dict[str, Any]) -> bool:
        relative_20d = factor.get("relative_strength_20d_pct")
        return (
            (
                not self.config.require_data_quality
                or (
                    bool(factor.get("data_quality_valid"))
                    and factor.get("data_quality_status") == "ok"
                )
            )
            and (
                not self.config.require_weinstein_stage2
                or (
                    bool(factor.get("weinstein_data_available"))
                    and factor.get("weinstein_stage") == "stage_2_uptrend"
                )
            )
            and bool(factor.get("weekly_data_available"))
            and float(factor.get("weekly_trend_score") or 0.0)
            >= self.config.min_weekly_trend_score
            and bool(factor.get("relative_strength_available"))
            and float(factor.get("relative_strength_score") or 0.0)
            >= self.config.min_relative_strength_score
            and relative_20d is not None
            and float(relative_20d) >= self.config.min_relative_strength_20d_pct
            and float(factor.get("daily_entry_score") or 0.0)
            >= self.config.min_daily_entry_score
        )

    def _screen_reasons(self, factor: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "weekly_trend_score": factor.get("weekly_trend_score"),
            "weekly_trend": factor.get("weekly_trend"),
            "relative_strength_score": factor.get("relative_strength_score"),
            "relative_strength_20d_pct": factor.get("relative_strength_20d_pct"),
            "relative_strength_60d_pct": factor.get("relative_strength_60d_pct"),
            "daily_entry_score": factor.get("daily_entry_score"),
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
                f"筛选条件: 周线分>={self.config.min_weekly_trend_score}, "
                f"RS评分>={self.config.min_relative_strength_score}, "
                f"20日超额收益>={self.config.min_relative_strength_20d_pct}%, "
                f"日线入场分>={self.config.min_daily_entry_score}"
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
