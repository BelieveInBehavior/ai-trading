"""
因子回测框架

核心功能：
- 对任意因子（数据源产出的信号）做 T+1 / T+3 / T+5 前向收益率验证
- 输出胜率、平均收益、IC（信息系数）、分组收益等统计指标
- 支持从历史信号 JSON 文件批量回测
- 支持自定义因子函数的回测

与 news_signal_backtest.py 的区别：
- news_signal_backtest 面向已有的 best_signals 做事后评估
- 本框架面向底层数据因子，用于验证"某个因子是否有预测能力"
"""

from __future__ import annotations

import json
import asyncio
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from dataclasses import dataclass, field

from loguru import logger
from config.config import PROJECT_ROOT
from utils.akshare_utils import akshare_cached
from utils.data_quality import normalize_market_frame


@dataclass
class FactorRecord:
    """单条因子记录"""
    symbol_code: str          # 股票代码（纯6位数字）
    symbol_name: str          # 股票名称
    factor_date: str          # 因子日期 YYYYMMDD
    factor_name: str          # 因子名称
    factor_value: float       # 因子值（越大越看多）
    factor_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BacktestResult:
    """回测结果"""
    factor_name: str
    total_signals: int
    evaluated_signals: int
    # 按 horizon 的统计
    horizons: Dict[str, Dict[str, Any]]  # {"t1": {"hit_rate": ..., "avg_return": ...}, ...}
    # 分组统计（按因子值分5组）
    quintile_returns: Dict[str, List[Dict[str, Any]]]
    # IC 值
    ic_values: Dict[str, Optional[float]]  # {"t1": 0.05, ...}
    # 详细记录
    details: pd.DataFrame
    # 滚动样本外验证
    walk_forward: Dict[str, Any] = field(default_factory=dict)


class FactorBacktester:
    """因子回测引擎"""

    def __init__(
        self,
        horizons: Sequence[int] = (1, 3, 5),
        benchmark_symbol: str = "sh000300",
        output_dir: Optional[Path] = None,
        commission_bps: float = 5.0,
        stamp_duty_bps: float = 10.0,
        slippage_bps: float = 5.0,
        entry_mode: str = "next_open",
    ):
        self.horizons = list(horizons)
        self.benchmark_symbol = benchmark_symbol
        self.output_dir = output_dir or (PROJECT_ROOT / "agents_workspace" / "backtest_results")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.commission_bps = max(0.0, float(commission_bps))
        self.stamp_duty_bps = max(0.0, float(stamp_duty_bps))
        self.slippage_bps = max(0.0, float(slippage_bps))
        self.entry_mode = entry_mode if entry_mode in {"next_open", "next_close"} else "next_open"
        self._price_cache: Dict[tuple[str, str, str, bool], pd.DataFrame] = {}

    def run(
        self,
        factor_records: List[FactorRecord],
        factor_name: str = "unnamed_factor",
    ) -> BacktestResult:
        """
        对一组因子记录做回测。

        Args:
            factor_records: 因子记录列表
            factor_name: 因子名称（用于输出文件命名）

        Returns:
            BacktestResult
        """
        if not factor_records:
            return BacktestResult(
                factor_name=factor_name,
                total_signals=0,
                evaluated_signals=0,
                horizons={},
                quintile_returns={},
                ic_values={},
                details=pd.DataFrame(),
            )

        logger.info(f"[FactorBacktest] 开始回测因子 '{factor_name}'，共 {len(factor_records)} 条信号")

        # 确定日期范围
        all_dates = [r.factor_date for r in factor_records]
        min_date = min(all_dates)
        max_date = max(all_dates)
        start_date = (datetime.strptime(min_date, "%Y%m%d") - timedelta(days=5)).strftime("%Y%m%d")
        end_date = (datetime.strptime(max_date, "%Y%m%d") + timedelta(days=max(self.horizons) + 10)).strftime("%Y%m%d")

        # 获取基准收益
        benchmark_df = self._get_price("__benchmark__", self.benchmark_symbol, start_date, end_date, is_index=True)

        # 逐条计算前向收益
        rows = []
        for record in factor_records:
            row = self._evaluate_single(record, start_date, end_date, benchmark_df)
            if row:
                rows.append(row)

        details = pd.DataFrame(rows)
        evaluated = len(details)
        logger.info(f"[FactorBacktest] 评估完成: {evaluated}/{len(factor_records)} 条有效")

        # 计算统计指标
        horizon_stats = self._compute_horizon_stats(details)
        quintile_returns = self._compute_quintile_returns(details)
        ic_values = self._compute_ic(details)
        walk_forward = self.run_walk_forward(
            factor_records,
            factor_name=factor_name,
        )

        result = BacktestResult(
            factor_name=factor_name,
            total_signals=len(factor_records),
            evaluated_signals=evaluated,
            horizons=horizon_stats,
            quintile_returns=quintile_returns,
            ic_values=ic_values,
            details=details,
            walk_forward=walk_forward,
        )

        # 保存结果
        self._save_result(result)

        return result

    def run_walk_forward(
        self,
        factor_records: List[FactorRecord],
        *,
        factor_name: str = "unnamed_factor",
        train_days: int = 252,
        test_days: int = 63,
        min_train_records: int = 30,
        top_quantile: float = 0.8,
    ) -> Dict[str, Any]:
        """Evaluate a factor using non-overlapping, train-then-test windows."""

        if not factor_records:
            return {"status": "no_data", "folds": [], "test_samples": 0}

        records = sorted(
            factor_records,
            key=lambda record: pd.to_datetime(record.factor_date, format="%Y%m%d"),
        )
        dates = sorted({record.factor_date for record in records})
        if len(dates) < 2:
            return {"status": "insufficient_dates", "folds": [], "test_samples": 0}

        fold_rows: list[dict[str, Any]] = []
        test_rows: list[dict[str, Any]] = []
        max_horizon = max(self.horizons) if self.horizons else 1
        first_date = datetime.strptime(dates[0], "%Y%m%d")
        last_date = datetime.strptime(dates[-1], "%Y%m%d")
        start_date = (first_date - timedelta(days=10)).strftime("%Y%m%d")
        end_date = (last_date + timedelta(days=max_horizon + 10)).strftime("%Y%m%d")
        benchmark_df = self._get_price(
            "__benchmark__",
            self.benchmark_symbol,
            start_date,
            end_date,
            is_index=True,
        )

        cursor = 0
        while cursor < len(dates):
            test_start = pd.to_datetime(dates[cursor], format="%Y%m%d")
            train_start = test_start - pd.Timedelta(days=train_days)
            train_dates = [
                date for date in dates
                if train_start.strftime("%Y%m%d") <= date < dates[cursor]
            ]
            if len(train_dates) < 2:
                cursor += test_days
                continue

            test_dates = dates[cursor: cursor + test_days]
            train_records = [record for record in records if record.factor_date in train_dates]
            test_records = [record for record in records if record.factor_date in test_dates]
            if len(train_records) < min_train_records or not test_records:
                cursor += test_days
                continue

            threshold = float(
                pd.Series([record.factor_value for record in train_records])
                .quantile(top_quantile)
            )
            selected = [
                record for record in test_records
                if float(record.factor_value) >= threshold
            ]
            rows = []
            for record in selected:
                row = self._evaluate_single(
                    record,
                    start_date,
                    end_date,
                    benchmark_df,
                )
                if row:
                    rows.append(row)
            if rows:
                fold_details = pd.DataFrame(rows)
                fold_stats = self._compute_horizon_stats(fold_details)
                test_rows.extend(rows)
                fold_rows.append(
                    {
                        "train_start": min(train_dates),
                        "train_end": max(train_dates),
                        "test_start": min(test_dates),
                        "test_end": max(test_dates),
                        "threshold": round(threshold, 6),
                        "train_samples": len(train_records),
                        "test_candidates": len(test_records),
                        "test_samples": len(rows),
                        "horizons": fold_stats,
                    }
                )
            cursor += test_days

        if not test_rows:
            return {
                "status": "insufficient_data",
                "factor_name": factor_name,
                "folds": fold_rows,
                "test_samples": 0,
            }

        details = pd.DataFrame(test_rows)
        return {
            "status": "ok",
            "factor_name": factor_name,
            "folds": fold_rows,
            "fold_count": len(fold_rows),
            "test_samples": len(details),
            "horizons": self._compute_horizon_stats(details),
            "ic_values": self._compute_ic(details),
            "costs": {
                "commission_bps": self.commission_bps,
                "stamp_duty_bps": self.stamp_duty_bps,
                "slippage_bps": self.slippage_bps,
                "entry_mode": self.entry_mode,
            },
        }

    def run_from_data_source(
        self,
        data_source_name: str,
        extract_signals_fn: Callable[[pd.DataFrame, str], List[FactorRecord]],
        trigger_times: List[str],
    ) -> BacktestResult:
        """
        从数据源的历史缓存中提取因子并回测。

        Args:
            data_source_name: 数据源名称（对应 data_source/data_cache/ 下的目录）
            extract_signals_fn: 从数据源 DataFrame 中提取 FactorRecord 列表的函数
            trigger_times: 历史 trigger_time 列表

        Returns:
            BacktestResult
        """
        cache_dir = PROJECT_ROOT / "data_source" / "data_cache" / data_source_name
        if not cache_dir.exists():
            logger.warning(f"缓存目录不存在: {cache_dir}")
            return self.run([], data_source_name)

        all_records = []
        for trigger_time in trigger_times:
            cache_file = cache_dir / f"{trigger_time.replace(' ', '_').replace(':', '-')}.pkl"
            if not cache_file.exists():
                continue
            try:
                df = pd.read_pickle(cache_file)
                records = extract_signals_fn(df, trigger_time)
                all_records.extend(records)
            except Exception as e:
                logger.warning(f"加载缓存 {cache_file} 失败: {e}")

        return self.run(all_records, data_source_name)

    def _evaluate_single(
        self,
        record: FactorRecord,
        start_date: str,
        end_date: str,
        benchmark_df: pd.DataFrame,
    ) -> Optional[Dict[str, Any]]:
        """评估单条因子记录"""
        symbol = record.symbol_code
        if not symbol:
            return None

        price_df = self._get_price(symbol, symbol, start_date, end_date)
        if price_df.empty:
            return None

        # 找到因子日期后的第一个交易日作为入场点
        factor_date = pd.to_datetime(record.factor_date, format="%Y%m%d")
        entry_idx = self._find_entry_index(price_df, factor_date)
        if entry_idx is None:
            return None

        entry_row = price_df.iloc[entry_idx]
        if self.entry_mode == "next_open":
            if "open" not in price_df.columns or pd.isna(entry_row["open"]):
                return None
            entry_price = float(entry_row["open"])
        else:
            entry_price = float(entry_row["close"])
        if entry_price <= 0:
            return None

        row: Dict[str, Any] = {
            "symbol_code": symbol,
            "symbol_name": record.symbol_name,
            "factor_date": record.factor_date,
            "factor_name": record.factor_name,
            "factor_value": record.factor_value,
            "entry_date": price_df.iloc[entry_idx]["date"].strftime("%Y-%m-%d"),
            "entry_close": float(price_df.iloc[entry_idx]["close"]),
            "entry_price": entry_price,
            "entry_mode": self.entry_mode,
        }

        for horizon in self.horizons:
            ret = self._forward_return(price_df, entry_idx, horizon)
            row[f"ret_t{horizon}"] = ret

            # 基准收益
            if benchmark_df is not None and not benchmark_df.empty and ret is not None:
                bench_entry_idx = self._find_entry_index(benchmark_df, factor_date)
                if bench_entry_idx is not None:
                    bench_ret = self._forward_return(benchmark_df, bench_entry_idx, horizon)
                    row[f"bench_ret_t{horizon}"] = bench_ret
                    row[f"alpha_t{horizon}"] = (ret - bench_ret) if bench_ret is not None else None
                else:
                    row[f"bench_ret_t{horizon}"] = None
                    row[f"alpha_t{horizon}"] = None
            else:
                row[f"bench_ret_t{horizon}"] = None
                row[f"alpha_t{horizon}"] = None

        return row

    def _get_price(
        self, cache_key: str, symbol: str, start_date: str, end_date: str, is_index: bool = False
    ) -> pd.DataFrame:
        """获取价格数据（带缓存）"""
        cache_token = (cache_key, start_date, end_date, is_index)
        if cache_token in self._price_cache:
            return self._price_cache[cache_token]

        try:
            if is_index:
                import akshare as ak
                df = ak.stock_zh_index_daily_em(symbol=symbol)
                if df is not None and not df.empty:
                    df = df.rename(
                        columns={
                            "日期": "date",
                            "开盘": "open",
                            "最高": "high",
                            "最低": "low",
                            "收盘": "close",
                        }
                    )
                    df["date"] = pd.to_datetime(df["date"], errors="coerce")
                    start_dt = pd.to_datetime(start_date)
                    end_dt = pd.to_datetime(end_date)
                    df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]
                    df, quality = normalize_market_frame(
                        df,
                        as_of_date=end_date,
                        min_rows=1,
                        require_ohlcv=False,
                    )
                    if not quality.valid:
                        logger.warning(
                            "回测指数数据质量异常 {}: {}",
                            symbol,
                            ",".join(quality.errors),
                        )
                        df = pd.DataFrame(columns=["date", "open", "high", "low", "close"])
                    else:
                        df["date"] = pd.to_datetime(df["date"], errors="coerce")
                        df["close"] = pd.to_numeric(df["close"], errors="coerce")
                        keep_columns = [column for column in ("date", "open", "high", "low", "close") if column in df.columns]
                        df = df[keep_columns].dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
                else:
                    df = pd.DataFrame(columns=["date", "open", "high", "low", "close"])
            else:
                df = akshare_cached.run(
                    func_name="stock_zh_a_hist",
                    func_kwargs={
                        "symbol": symbol,
                        "period": "daily",
                        "start_date": start_date,
                        "end_date": end_date,
                        "adjust": "qfq",
                    },
                    verbose=False,
                )
                if df is not None and not df.empty:
                    df = df.rename(
                        columns={
                            "日期": "date",
                            "开盘": "open",
                            "最高": "high",
                            "最低": "low",
                            "收盘": "close",
                        }
                    )
                    df["date"] = pd.to_datetime(df["date"], errors="coerce")
                    start_dt = pd.to_datetime(start_date)
                    end_dt = pd.to_datetime(end_date)
                    df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]
                    df, quality = normalize_market_frame(
                        df,
                        as_of_date=end_date,
                        min_rows=1,
                        require_ohlcv=False,
                    )
                    if not quality.valid:
                        logger.warning(
                            "回测价格数据质量异常 {}: {}",
                            symbol,
                            ",".join(quality.errors),
                        )
                        df = pd.DataFrame(columns=["date", "open", "high", "low", "close"])
                    else:
                        df["date"] = pd.to_datetime(df["date"], errors="coerce")
                        df["close"] = pd.to_numeric(df["close"], errors="coerce")
                        df = df[[column for column in ("date", "open", "high", "low", "close") if column in df.columns]]
                        df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
                else:
                    df = pd.DataFrame(columns=["date", "open", "high", "low", "close"])

            self._price_cache[cache_token] = df
            return df

        except Exception as e:
            logger.warning(f"获取价格数据失败 {symbol}: {e}")
            self._price_cache[cache_token] = pd.DataFrame(columns=["date", "open", "high", "low", "close"])
            return self._price_cache[cache_token]

    def _find_entry_index(self, price_df: pd.DataFrame, factor_date: pd.Timestamp) -> Optional[int]:
        """找到因子日期后的第一个交易日"""
        if price_df.empty:
            return None
        candidates = price_df.index[price_df["date"].dt.date > factor_date.date()].tolist()
        return candidates[0] if candidates else None

    def _forward_return(self, price_df: pd.DataFrame, entry_idx: int, horizon: int) -> Optional[float]:
        """计算前向收益率"""
        exit_idx = entry_idx + horizon
        if exit_idx >= len(price_df):
            return None
        entry_row = price_df.iloc[entry_idx]
        exit_row = price_df.iloc[exit_idx]
        if self.entry_mode == "next_open":
            if "open" not in price_df.columns or pd.isna(entry_row["open"]):
                return None
            entry_price = float(entry_row["open"])
        else:
            entry_price = float(entry_row["close"])
        exit_price = float(exit_row["close"])
        if entry_price <= 0 or exit_price <= 0:
            return None
        entry_cost = self.commission_bps + self.slippage_bps
        exit_cost = self.commission_bps + self.stamp_duty_bps + self.slippage_bps
        return (
            exit_price * (1.0 - exit_cost / 10000.0)
            / (entry_price * (1.0 + entry_cost / 10000.0))
        ) - 1.0

    def _compute_horizon_stats(self, details: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """按 horizon 计算统计指标"""
        stats = {}
        for horizon in self.horizons:
            key = f"t{horizon}"
            ret_col = f"ret_t{horizon}"
            alpha_col = f"alpha_t{horizon}"

            if ret_col not in details.columns:
                stats[key] = {"hit_rate": None, "avg_return": None, "avg_alpha": None, "sharpe": None}
                continue

            valid = details[ret_col].dropna()
            if valid.empty:
                stats[key] = {"hit_rate": None, "avg_return": None, "avg_alpha": None, "sharpe": None}
                continue

            hit_rate = float((valid > 0).mean())
            avg_return = float(valid.mean())
            std_return = float(valid.std())
            sharpe = (avg_return / std_return * np.sqrt(252 / horizon)) if std_return > 0 else None

            avg_alpha = None
            if alpha_col in details.columns:
                valid_alpha = details[alpha_col].dropna()
                if not valid_alpha.empty:
                    avg_alpha = float(valid_alpha.mean())

            stats[key] = {
                "hit_rate": round(hit_rate, 4),
                "avg_return": round(avg_return, 6),
                "avg_alpha": round(avg_alpha, 6) if avg_alpha is not None else None,
                "sharpe": round(sharpe, 4) if sharpe is not None else None,
                "count": len(valid),
                "win_count": int((valid > 0).sum()),
                "loss_count": int((valid <= 0).sum()),
                "max_return": round(float(valid.max()), 6),
                "min_return": round(float(valid.min()), 6),
                "median_return": round(float(valid.median()), 6),
            }

        return stats

    def _compute_quintile_returns(self, details: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
        """按因子值分5组，计算各组收益"""
        result = {}
        if details.empty or "factor_value" not in details.columns:
            return result

        try:
            details = details.copy()
            details["quintile"] = pd.qcut(
                details["factor_value"], q=5, labels=["Q1(低)", "Q2", "Q3", "Q4", "Q5(高)"],
                duplicates="drop"
            )
        except ValueError:
            return result

        for horizon in self.horizons:
            key = f"t{horizon}"
            ret_col = f"ret_t{horizon}"
            if ret_col not in details.columns:
                continue

            group_stats = []
            for quintile, group in details.groupby("quintile", observed=False):
                valid = group[ret_col].dropna()
                if valid.empty:
                    group_stats.append({
                        "quintile": str(quintile),
                        "count": 0,
                        "avg_return": None,
                        "hit_rate": None,
                    })
                else:
                    group_stats.append({
                        "quintile": str(quintile),
                        "count": len(valid),
                        "avg_return": round(float(valid.mean()), 6),
                        "hit_rate": round(float((valid > 0).mean()), 4),
                    })
            result[key] = group_stats

        return result

    def _compute_ic(self, details: pd.DataFrame) -> Dict[str, Optional[float]]:
        """计算 Rank IC（Spearman 相关系数）"""
        result = {}
        if details.empty or "factor_value" not in details.columns:
            return result

        for horizon in self.horizons:
            key = f"t{horizon}"
            ret_col = f"ret_t{horizon}"
            if ret_col not in details.columns:
                result[key] = None
                continue

            valid = details[["factor_value", ret_col]].dropna()
            if len(valid) < 10:
                result[key] = None
                continue

            ic = valid["factor_value"].corr(valid[ret_col], method="spearman")
            result[key] = round(float(ic), 6) if not np.isnan(ic) else None

        return result

    def _save_result(self, result: BacktestResult):
        """保存回测结果"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        factor_dir = self.output_dir / result.factor_name
        factor_dir.mkdir(parents=True, exist_ok=True)

        # 保存 summary
        summary = {
            "factor_name": result.factor_name,
            "total_signals": result.total_signals,
            "evaluated_signals": result.evaluated_signals,
            "horizons": result.horizons,
            "quintile_returns": result.quintile_returns,
            "ic_values": result.ic_values,
            "walk_forward": result.walk_forward,
            "generated_at": timestamp,
        }
        summary_path = factor_dir / f"summary_{timestamp}.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        # 保存 details
        if not result.details.empty:
            details_path = factor_dir / f"details_{timestamp}.csv"
            result.details.to_csv(details_path, index=False)

        logger.info(f"[FactorBacktest] 结果已保存到 {factor_dir}")

    def generate_report(self, result: BacktestResult) -> str:
        """生成人类可读的回测报告"""
        lines = [
            f"# 因子回测报告: {result.factor_name}",
            f"",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**总信号数**: {result.total_signals}",
            f"**有效评估数**: {result.evaluated_signals}",
            f"",
            "---",
            "",
            "## 各 Horizon 统计",
            "",
            "| Horizon | 胜率 | 平均收益 | 超额收益(Alpha) | Sharpe | 最大收益 | 最大亏损 |",
            "|---------|------|----------|----------------|--------|----------|----------|",
        ]

        for key, stats in result.horizons.items():
            hit = f"{stats['hit_rate']*100:.1f}%" if stats.get('hit_rate') is not None else "N/A"
            avg = f"{stats['avg_return']*100:.2f}%" if stats.get('avg_return') is not None else "N/A"
            alpha = f"{stats['avg_alpha']*100:.2f}%" if stats.get('avg_alpha') is not None else "N/A"
            sharpe = f"{stats['sharpe']:.2f}" if stats.get('sharpe') is not None else "N/A"
            max_r = f"{stats['max_return']*100:.2f}%" if stats.get('max_return') is not None else "N/A"
            min_r = f"{stats['min_return']*100:.2f}%" if stats.get('min_return') is not None else "N/A"
            lines.append(f"| {key} | {hit} | {avg} | {alpha} | {sharpe} | {max_r} | {min_r} |")

        # IC 值
        lines.extend(["", "## Rank IC (信息系数)", ""])
        for key, ic in result.ic_values.items():
            ic_str = f"{ic:.4f}" if ic is not None else "N/A"
            interpretation = ""
            if ic is not None:
                if abs(ic) > 0.05:
                    interpretation = " (有效因子)" if ic > 0 else " (反向因子)"
                elif abs(ic) > 0.03:
                    interpretation = " (弱有效)"
                else:
                    interpretation = " (无效)"
            lines.append(f"- **{key}**: {ic_str}{interpretation}")

        walk_forward = result.walk_forward or {}
        lines.extend(["", "## 滚动样本外验证", ""])
        lines.append(
            f"- **状态**: {walk_forward.get('status', '未运行')}; "
            f"**测试样本数**: {walk_forward.get('test_samples', 0)}; "
            f"**折数**: {walk_forward.get('fold_count', 0)}"
        )

        # 分组收益
        if result.quintile_returns:
            lines.extend(["", "## 分组收益（因子值从低到高分5组）", ""])
            for key, quintiles in result.quintile_returns.items():
                lines.append(f"### {key}")
                lines.append("| 组别 | 样本数 | 平均收益 | 胜率 |")
                lines.append("|------|--------|----------|------|")
                for q in quintiles:
                    avg = f"{q['avg_return']*100:.2f}%" if q.get('avg_return') is not None else "N/A"
                    hit = f"{q['hit_rate']*100:.1f}%" if q.get('hit_rate') is not None else "N/A"
                    lines.append(f"| {q['quintile']} | {q['count']} | {avg} | {hit} |")
                lines.append("")

                # 单调性判断
                valid_returns = [q["avg_return"] for q in quintiles if q.get("avg_return") is not None]
                if len(valid_returns) >= 3:
                    is_monotonic = all(
                        valid_returns[i] <= valid_returns[i + 1]
                        for i in range(len(valid_returns) - 1)
                    )
                    is_reverse = all(
                        valid_returns[i] >= valid_returns[i + 1]
                        for i in range(len(valid_returns) - 1)
                    )
                    if is_monotonic:
                        lines.append("**单调性**: 正单调 (因子值越高收益越高，因子有效)")
                    elif is_reverse:
                        lines.append("**单调性**: 反单调 (因子值越高收益越低，需反向使用)")
                    else:
                        lines.append("**单调性**: 非单调 (因子预测能力不稳定)")
                lines.append("")

        return "\n".join(lines)


# ===== 便捷函数：从现有数据源提取因子 =====

def extract_fund_flow_factors(df: pd.DataFrame, trigger_time: str) -> List[FactorRecord]:
    """从个股资金流数据中提取因子记录"""
    records = []
    content = df.iloc[0]["content"] if not df.empty else ""
    if not content:
        return records

    trigger_date = trigger_time.split(" ")[0].replace("-", "")

    # 简易解析：从报告文本中提取股票代码和主力净流入数据
    import re
    pattern = r"(\S+)\((\d{6})\).*?主力净流入([\d.]+)亿"
    for match in re.finditer(pattern, content):
        name, code, amount = match.groups()
        records.append(FactorRecord(
            symbol_code=code,
            symbol_name=name,
            factor_date=trigger_date,
            factor_name="主力净流入",
            factor_value=float(amount),
        ))

    return records


def extract_margin_factors(df: pd.DataFrame, trigger_time: str) -> List[FactorRecord]:
    """从融资融券数据中提取因子记录"""
    records = []
    content = df.iloc[0]["content"] if not df.empty else ""
    if not content:
        return records

    trigger_date = trigger_time.split(" ")[0].replace("-", "")

    import re
    pattern = r"(\S+)\((\S+)\).*?融资净买入([\d.]+)亿"
    for match in re.finditer(pattern, content):
        name, code, amount = match.groups()
        # 清理代码
        clean_code = code.split(".")[0] if "." in code else code
        if clean_code.isdigit() and len(clean_code) == 6:
            records.append(FactorRecord(
                symbol_code=clean_code,
                symbol_name=name,
                factor_date=trigger_date,
                factor_name="融资净买入",
                factor_value=float(amount),
            ))

    return records


def extract_zt_seal_factors(df: pd.DataFrame, trigger_time: str) -> List[FactorRecord]:
    """从涨停封单强度数据中提取因子记录"""
    records = []
    content = df.iloc[0]["content"] if not df.empty else ""
    if not content:
        return records

    trigger_date = trigger_time.split(" ")[0].replace("-", "")

    import re
    pattern = r"(\S+)\((\d{6})\).*?封单强度([\d.]+)%"
    for match in re.finditer(pattern, content):
        name, code, strength = match.groups()
        records.append(FactorRecord(
            symbol_code=code,
            symbol_name=name,
            factor_date=trigger_date,
            factor_name="涨停封单强度",
            factor_value=float(strength),
        ))

    return records


if __name__ == "__main__":
    # 示例：回测虚拟因子
    backtester = FactorBacktester(horizons=[1, 3, 5])

    # 创建一些测试因子记录
    test_records = [
        FactorRecord("600519", "贵州茅台", "20260801", "test_factor", 0.8),
        FactorRecord("000858", "五粮液", "20260801", "test_factor", 0.6),
        FactorRecord("300750", "宁德时代", "20260801", "test_factor", 0.9),
    ]

    result = backtester.run(test_records, "test_factor")
    report = backtester.generate_report(result)
    print(report)
