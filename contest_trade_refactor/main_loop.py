"""
Simplified Trade Company - Agent Loop Version

Refactored from LangGraph to direct async orchestration.
Uses the new agent loop implementations for cleaner control flow.
"""

import re
import json
import asyncio
import pandas as pd
from datetime import datetime
from typing import Awaitable, Callable, List, Dict, Any, Optional

from config.config import cfg, PROJECT_ROOT, WORKSPACE_ROOT
from config.strategies import get_strategy
from agents.data_analysis_pipeline import DataAnalysisPipeline
from agents.research_agent_loop import (
    ResearchAgentLoop,
    ResearchAgentLoopConfig,
    ResearchAgentInput,
)
from agents.consensus_aggregator import ConsensusAggregator, ConsensusConfig
from agents.quantitative_universe_screener import (
    QuantitativeScreenerConfig,
    QuantitativeUniverseScreener,
)
from agents.stock_opportunity_ranker import RankerConfig, StockOpportunityRanker
from agents.signal_schema import parse_json_signals, validate_research_signal
from agents.signal_tier_classifier import SignalTierClassifier
from agents.market_regime_detector import MarketRegimeDetector, format_regime_report
from utils.signal_tracker import SignalTracker
from data_source.technical_indicators_akshare import compute_stock_technical_factor
from utils.market_manager import GLOBAL_MARKET_MANAGER
from utils.report_utils import generate_trade_decision_report
from utils.financial_report_utils import enrich_signals_with_financial_report
from utils.performance_tracker import PerformanceTracker
from utils.cn_price_provider import get_index_daily
from utils.date_utils import get_latest_completed_trading_date, get_trading_date_range
from utils.system_health_utils import (
    count_data_factor_tool_errors,
    factor_content_is_usable,
    summarize_research_agent_tool_errors,
    text_indicates_tool_failure,
)


def _normalize_stock_code(value: Any) -> str:
    match = re.search(r"(\d{6})", str(value or ""))
    return match.group(1) if match else ""


def _parse_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        text = str(value).replace("%", "").strip()
        if not text or text.upper() in {"N/A", "NAN", "NONE"}:
            return None
        return float(text)
    except Exception:
        return None


def _config_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"false", "0", "no", "off"}:
            return False
        if normalized in {"true", "1", "yes", "on"}:
            return True
    return bool(value)


def _config_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _config_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_technical_stock_factors(data_factors: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    factors: Dict[str, Dict[str, Any]] = {}
    line_pattern = re.compile(
        r"^(?P<name>[^()\n:：]+)\((?P<code>\d{6})\):\s*"
        r"收盘(?P<close>[-+]?\d+(?:\.\d+)?),\s*"
        r"涨跌幅(?P<change>[-+]?\d+(?:\.\d+)?|N/A)%?,\s*"
        r"MA20距离(?P<ma20>[-+]?\d+(?:\.\d+)?|N/A)%?,\s*"
        r"RSI=(?P<rsi>[-+]?\d+(?:\.\d+)?|N/A|nan),\s*"
        r"MACD=(?P<macd>[-+]?\d+(?:\.\d+)?|N/A|nan),\s*"
        r"量比=(?P<volume_ratio>[-+]?\d+(?:\.\d+)?|N/A|nan),\s*"
        r"布林=(?P<bollinger>[^\s<]+)",
    )

    for factor in data_factors or []:
        agent_name = str(factor.get("agent_name") or "")
        content = str(factor.get("context_string") or "")
        if "technical_indicators_agent" not in agent_name and "活跃个股技术面" not in content:
            continue

        date_match = re.search(r"技术指标分析报告\s*\((\d{8})\)", content)
        report_date = date_match.group(1) if date_match else ""

        for raw_line in content.splitlines():
            line = raw_line.strip()
            match = line_pattern.search(line)
            if not match:
                continue

            code = match.group("code")
            ma20_distance_pct = _parse_float(match.group("ma20"))
            change_pct = _parse_float(match.group("change"))
            factors[code] = {
                "symbol_code": code,
                "symbol_name": match.group("name").strip(),
                "report_date": report_date,
                "close": _parse_float(match.group("close")),
                "change_pct": change_pct,
                "ma20_deviation_pct": ma20_distance_pct,
                "rsi": _parse_float(match.group("rsi")),
                "macd": _parse_float(match.group("macd")),
                "volume_ratio": _parse_float(match.group("volume_ratio")),
                "bollinger": match.group("bollinger"),
                "source_line": line,
            }

    return factors


def _format_technical_factor_context(factor: Dict[str, Any]) -> str:
    ma20_distance = factor.get("ma20_deviation_pct")
    if ma20_distance is None:
        ma20_status = "MA20距离缺失"
    elif ma20_distance < -3:
        ma20_status = "跌破20日线"
    elif ma20_distance > 3:
        ma20_status = "站上20日线"
    else:
        ma20_status = "贴近20日线"

    date_label = factor.get("report_date") or "N/A"
    weekly_trend = factor.get("weekly_trend") or "N/A"
    weekly_score = factor.get("weekly_trend_score")
    relative_strength_score = factor.get("relative_strength_score")
    relative_strength_20d = factor.get("relative_strength_20d_pct")
    relative_strength_60d = factor.get("relative_strength_60d_pct")
    weinstein_stage = factor.get("weinstein_stage") or "unknown"
    weinstein_score = factor.get("weinstein_stage_score")
    quality_status = factor.get("data_quality_status") or "unknown"
    multi_timeframe = (
        f"周线={weekly_trend}/{_parse_float(weekly_score) if weekly_score is not None else 'N/A'}, "
        f"相对强度20日={_parse_float(relative_strength_20d) if relative_strength_20d is not None else 'N/A'}%, "
        f"60日={_parse_float(relative_strength_60d) if relative_strength_60d is not None else 'N/A'}, "
        f"RS评分={_parse_float(relative_strength_score) if relative_strength_score is not None else 'N/A'}, "
        f"温斯坦={weinstein_stage}/{_parse_float(weinstein_score) if weinstein_score is not None else 'N/A'}, "
        f"行情质量={quality_status}"
    )
    return f"技术指标因子({date_label}): {factor.get('source_line', '')}，{ma20_status}，{multi_timeframe}"


def _enrich_signals_with_technical_factors(
    research_signals: List[Dict[str, Any]],
    data_factors: List[Dict[str, Any]],
    trigger_time: str | None = None,
) -> List[Dict[str, Any]]:
    technical_factors = _extract_technical_stock_factors(data_factors)
    selection_config = getattr(cfg, "signal_selection_config", None) or {}
    relative_strength_benchmark = str(
        selection_config.get("relative_strength_benchmark") or "sh000300"
    )
    expected_trade_date = None
    kline_start_date = None
    kline_end_date = None
    if trigger_time:
        try:
            expected_trade_date = get_latest_completed_trading_date(trigger_time)
            kline_start_date, kline_end_date = get_trading_date_range(
                end_date=expected_trade_date,
                count=260,
                include_end=True,
            )
        except Exception:
            expected_trade_date = None

    factors_by_name = {
        factor["symbol_name"]: factor
        for factor in technical_factors.values()
        if factor.get("symbol_name")
    }

    enriched = []
    for signal in research_signals or []:
        item = dict(signal)
        code = _normalize_stock_code(item.get("symbol_code"))
        name = str(item.get("symbol_name") or "").strip()
        factor = technical_factors.get(code) or factors_by_name.get(name)

        if factor and expected_trade_date:
            factor_date = str(factor.get("report_date") or "")
            if factor_date and factor_date != expected_trade_date:
                factor = None

        # Candidate-level enrichment must include the longer history needed for
        # weekly trend and relative-strength calculations. Fall back to the
        # active-stock report only when the fresh calculation is unavailable.
        has_multi_timeframe_factor = factor and all(
            key in factor
            for key in (
                "weekly_trend_score",
                "relative_strength_score",
                "daily_entry_score",
            )
        )
        if (
            expected_trade_date
            and kline_start_date
            and kline_end_date
            and code
            and not has_multi_timeframe_factor
        ):
            try:
                fresh_factor = compute_stock_technical_factor(
                    symbol_code=code,
                    symbol_name=name,
                    trade_date=expected_trade_date,
                    start_date=kline_start_date,
                    end_date=kline_end_date,
                    adjust="qfq",
                    relative_strength_benchmark=relative_strength_benchmark,
                )
                if fresh_factor:
                    factor = fresh_factor
            except Exception:
                pass

        if factor:
            item["technical_factor"] = factor
            if factor.get("ma20_deviation_pct") is not None:
                item["ma20_deviation_pct"] = factor["ma20_deviation_pct"]
            if factor.get("change_pct") is not None:
                item["prev_day_gain_pct"] = factor["change_pct"]
            for key in (
                "weekly_data_available",
                "weekly_trend",
                "weekly_trend_score",
                "relative_strength_available",
                "relative_strength_benchmark",
                "relative_strength_score",
                "relative_strength_20d_pct",
                "relative_strength_60d_pct",
                "daily_entry_score",
                "data_quality_valid",
                "data_quality_status",
                "data_quality_errors",
                "data_quality_warnings",
                "data_quality_last_date",
                "observation_count",
                "weinstein_data_available",
                "weinstein_stage",
                "weinstein_stage_score",
                "weinstein_ma30",
                "weinstein_ma30_slope_pct",
                "weinstein_close_vs_ma30_pct",
                "weinstein_above_ma30_ratio_8w",
                "weinstein_observation_count",
            ):
                if key in factor:
                    item[key] = factor[key]

            context_line = _format_technical_factor_context(factor)
            existing_kline = str(item.get("kline_description") or "").strip()
            if context_line not in existing_kline:
                item["kline_description"] = "\n".join(
                    part for part in [existing_kline, context_line] if part
                )
        elif expected_trade_date and code:
            warnings = list(item.get("data_quality_warnings") or [])
            if "missing_kline" not in warnings:
                warnings.append("missing_kline")
            item["data_quality_warnings"] = warnings

        enriched.append(item)

    return enriched


class SimpleTradeCompany:
    """
    Simplified Trade Company using proper architecture patterns.

    Architecture:
    - Data Analysis: Pipeline pattern (fixed steps, linear flow)
    - Research: Agent Loop pattern (dynamic decisions, ReAct loop)
    - Orchestration: Simple async coordination
    """

    def __init__(self, strategy: str = "momentum"):
        self.strategy = get_strategy(strategy)
        self.workspace_dir = WORKSPACE_ROOT
        selection_config = getattr(cfg, "signal_selection_config", None) or {}
        strategy_config = self.strategy
        self.quantitative_screener = QuantitativeUniverseScreener(
            QuantitativeScreenerConfig(
                enabled=_config_bool(
                    selection_config.get("quantitative_screen_enabled"),
                    True,
                ),
                max_symbols=_config_int(
                    selection_config.get("quantitative_screen_max_symbols"),
                    0,
                ),
                max_concurrency=_config_int(
                    selection_config.get("quantitative_screen_concurrency"),
                    8,
                ),
                top_k=_config_int(
                    selection_config.get("quantitative_screen_top_k"),
                    _config_int(strategy_config.get("quantitative_screen_top_k"), 80),
                ),
                history_days=_config_int(
                    selection_config.get("quantitative_screen_history_days"),
                    _config_int(strategy_config.get("quantitative_screen_history_days"), 260),
                ),
                benchmark_symbol=str(
                    selection_config.get("relative_strength_benchmark")
                    or "sh000300"
                ),
                min_weekly_trend_score=_config_float(
                    selection_config.get("min_weekly_trend_score"),
                    _config_float(strategy_config.get("min_weekly_trend_score"), 55.0),
                ),
                min_relative_strength_score=_config_float(
                    selection_config.get("min_relative_strength_score"),
                    _config_float(strategy_config.get("min_relative_strength_score"), 50.0),
                ),
                min_relative_strength_20d_pct=_config_float(
                    selection_config.get("min_relative_strength_20d_pct"),
                    _config_float(strategy_config.get("min_relative_strength_20d_pct"), 0.0),
                ),
                min_daily_entry_score=_config_float(
                    selection_config.get("min_daily_entry_score"),
                    _config_float(strategy_config.get("min_daily_entry_score"), 50.0),
                ),
                min_amount=_config_float(
                    selection_config.get("quantitative_screen_min_amount"),
                    0.0,
                ),
                max_ma20_deviation_pct=_config_float(
                    selection_config.get("quantitative_max_ma20_deviation_pct"),
                    _config_float(strategy_config.get("quantitative_max_ma20_deviation_pct"), 60.0),
                ),
                max_prev_day_gain_pct=_config_float(
                    selection_config.get("quantitative_max_prev_day_gain_pct"),
                    _config_float(strategy_config.get("quantitative_max_prev_day_gain_pct"), 15.0),
                ),
                ma20_deviation_penalty=_config_float(
                    selection_config.get("quantitative_ma20_deviation_penalty"),
                    _config_float(strategy_config.get("quantitative_ma20_deviation_penalty"), 1.0),
                ),
                hard_max_ma20_deviation_pct=_config_float(
                    selection_config.get("quantitative_hard_max_ma20_deviation_pct"),
                    _config_float(strategy_config.get("quantitative_hard_max_ma20_deviation_pct"), 80.0),
                ),
                hard_max_prev_day_gain_pct=_config_float(
                    selection_config.get("quantitative_hard_max_prev_day_gain_pct"),
                    _config_float(strategy_config.get("quantitative_hard_max_prev_day_gain_pct"), 20.0),
                ),
                hard_min_weekly_score=_config_float(
                    selection_config.get("quantitative_hard_min_weekly_score"),
                    _config_float(strategy_config.get("quantitative_hard_min_weekly_score"), 30.0),
                ),
                hard_min_relative_score=_config_float(
                    selection_config.get("quantitative_hard_min_relative_score"),
                    _config_float(strategy_config.get("quantitative_hard_min_relative_score"), 25.0),
                ),
                require_data_quality=_config_bool(
                    selection_config.get("require_data_quality"),
                    True,
                ),
                # V2: 不再强制 Weinstein Stage 2。改用 stage 评分 + stage>=4硬拒绝。
                require_weinstein_stage2=_config_bool(
                    selection_config.get("require_weinstein_stage2"),
                    False,
                ),
            )
        )
        self.quantitative_screen_fail_open = _config_bool(
            selection_config.get("quantitative_screen_fail_open"),
            False,
        )
        self.quantitative_screen_result: Dict[str, Any] = {
            "status": "not_run",
            "candidates": [],
            "context_string": "",
        }
        self.quantitative_candidates_by_code: Dict[str, Dict[str, Any]] = {}

        # ���增：信号分级���和市���环境识别器
        self.signal_tier_classifier = SignalTierClassifier()
        self.market_regime_detector = MarketRegimeDetector()
        self.signal_tracker = SignalTracker(self.workspace_dir)
        ranker_overrides = self.strategy.get("ranker_overrides") or {}
        self.signal_ranker = StockOpportunityRanker(
            RankerConfig(
                reject_future_evidence=_config_bool(
                    selection_config.get("reject_future_evidence"),
                    True,
                ),
                risk_veto_enabled=_config_bool(
                    selection_config.get("risk_veto_enabled"),
                    True,
                ),
                enforce_multi_timeframe=_config_bool(
                    selection_config.get("multi_timeframe_enabled"),
                    True,
                ),
                min_weekly_trend_score=_config_float(
                    ranker_overrides.get("min_weekly_trend_score"),
                    _config_float(selection_config.get("min_weekly_trend_score"), 55.0),
                ),
                min_relative_strength_score=_config_float(
                    ranker_overrides.get("min_relative_strength_score"),
                    _config_float(selection_config.get("min_relative_strength_score"), 50.0),
                ),
                min_relative_strength_20d_pct=_config_float(
                    ranker_overrides.get("min_relative_strength_20d_pct"),
                    _config_float(selection_config.get("min_relative_strength_20d_pct"), 0.0),
                ),
                min_daily_entry_score=_config_float(
                    ranker_overrides.get("min_daily_entry_score"),
                    _config_float(selection_config.get("min_daily_entry_score"), 50.0),
                ),
                min_flow_confirmation_score=_config_float(
                    ranker_overrides.get("min_flow_confirmation_score"),
                    _config_float(selection_config.get("min_flow_confirmation_score"), 55.0),
                ),
                min_regime_confirmation_score=_config_float(
                    ranker_overrides.get("min_regime_confirmation_score"),
                    _config_float(selection_config.get("min_regime_confirmation_score"), 52.0),
                ),
                max_prev_day_gain_pct=_config_float(
                    ranker_overrides.get("max_prev_day_gain_pct"),
                    _config_float(selection_config.get("max_prev_day_gain_pct"), 6.0),
                ),
                max_ma20_deviation_pct=_config_float(
                    ranker_overrides.get("max_ma20_deviation_pct"),
                    _config_float(selection_config.get("max_ma20_deviation_pct"), 8.0),
                ),
                min_risk_reward_score=_config_float(
                    ranker_overrides.get("min_risk_reward_score"),
                    50.0,
                ),
                expected_return_floor_pct=_config_float(
                    ranker_overrides.get("expected_return_floor_pct"),
                    0.3,
                ),
                strong_trend_penalty_bias=_config_float(
                    ranker_overrides.get("strong_trend_penalty_bias"),
                    0.0,
                ),
            )
        )
        self.consensus_aggregator = ConsensusAggregator(
            ConsensusConfig(
                enabled=_config_bool(
                    selection_config.get("consensus_enabled"),
                    True,
                ),
                method=str(
                    selection_config.get("consensus_method")
                    or "weighted_majority"
                ),
                require_majority=_config_bool(
                    selection_config.get("consensus_require_majority"),
                    True,
                ),
            )
        )
        self.system_health = {"tool_error_count": 0, "agent_error_count": 0, "warnings": []}
        self.performance_tracker = PerformanceTracker()

        # Initialize Data Agents (using Pipeline)
        self.data_agents = {}
        for agent_idx, agent_config in enumerate(cfg.data_agents_config):
            self.data_agents[agent_idx] = DataAnalysisPipeline(
                agent_name=agent_config["agent_name"],
                source_list=agent_config["data_source_list"],
                final_target_tokens=agent_config.get("final_target_tokens", 4000),
                bias_goal=agent_config.get("bias_goal", ""),
                passthrough_summary=agent_config.get("passthrough_summary", False),
            )

        # Initialize Research Agents
        self.research_agents = {}
        belief_list = strategy_config.get("belief_list")
        if not belief_list:
            belief_list_path = PROJECT_ROOT / cfg.research_agent_config["belief_list_path"]
            with open(belief_list_path, 'r', encoding='utf-8') as f:
                belief_list = json.load(f)

        for agent_idx, belief in enumerate(belief_list):
            config = ResearchAgentLoopConfig(
                agent_name=f"agent_{agent_idx}",
                belief=belief,
                verbose=True,
                enable_cache=False,
            )
            self.research_agents[agent_idx] = ResearchAgentLoop(config)

    def _get_signal_selection_settings(self) -> tuple[int, int]:
        config = getattr(cfg, "signal_selection_config", None) or {}
        strategy = self.strategy or {}
        require_min_buys = max(0, int(config.get("require_min_buys", strategy.get("require_min_buys", 0))))
        max_research_rounds = max(1, int(config.get("max_research_rounds", strategy.get("max_research_rounds", 10))))
        return require_min_buys, max_research_rounds

    def _get_max_stall_rounds(self) -> int:
        config = getattr(cfg, "signal_selection_config", None) or {}
        strategy = self.strategy or {}
        return max(1, int(config.get("max_stall_rounds", strategy.get("max_stall_rounds", 3))))

    async def _enrich_round_signals_financial(
        self,
        signals: List[Dict[str, Any]],
        trigger_time: str,
    ) -> List[Dict[str, Any]]:
        """Attach latest income-statement YOY figures to candidate signals."""
        if not signals:
            return signals
        needs = [s for s in signals if not s.get("financial_report")]
        if not needs:
            return signals
        try:
            enriched = await enrich_signals_with_financial_report(
                signals=needs,
                trigger_time=trigger_time,
                period_count=3,
                concurrency=3,
            )
            by_key = {
                (str(s.get("symbol_code") or ""), s.get("research_round" or 0)): s
                for s in enriched
            }
        except Exception as exc:
            logger.warning("financial enrich failed: {}", exc)
            return signals

        def _apply(sig):
            key = (str(sig.get("symbol_code") or ""), sig.get("research_round"))
            enr = by_key.get(key) or by_key.get((str(sig.get("symbol_code") or ""), None))
            if enr:
                return enr
            return sig
        return [_apply(sig) for sig in signals]

    async def _run_research_and_select_until_min_buys(
        self,
        trigger_time: str,
        data_factors: List[Dict[str, Any]],
        market_context: Dict[str, Any],
        research_runner: Optional[
            Callable[[str, List[Dict[str, Any]]], Awaitable[List[Dict[str, Any]]]]
        ] = None,
        on_round_start: Optional[Callable[[int, int], Awaitable[None]]] = None,
        on_round_complete: Optional[Callable[[int, Dict[str, Any]], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """
        Re-run research agents (strict gates unchanged) until require_min_buys is met
        or max_research_rounds is reached.
        """
        require_min_buys, max_rounds = self._get_signal_selection_settings()
        max_stall_rounds = self._get_max_stall_rounds()
        using_default_research_runner = research_runner is None
        research_runner = research_runner or self._run_research_agents

        all_research_signals: List[Dict[str, Any]] = []
        buy_signals: List[Dict[str, Any]] = []
        watchlist: List[Dict[str, Any]] = []
        consensus_signals: List[Dict[str, Any]] = []
        rounds_completed = 0
        met_requirement = require_min_buys == 0
        stall_rounds = 0

        if (
            self.quantitative_screener.config.enabled
            and not self.quantitative_screen_fail_open
            and using_default_research_runner
            and (
                self.quantitative_screen_result.get("status") != "ok"
                or not self.quantitative_candidates_by_code
            )
        ):
            warning = (
                "quantitative_screen_unavailable"
                if self.quantitative_screen_result.get("status") != "ok"
                else "quantitative_screen_empty"
            )
            if warning not in self.system_health["warnings"]:
                self.system_health["warnings"].append(warning)
            return {
                "research_signals": [],
                "buy_signals": [],
                "watchlist": [],
                "consensus_signals": [],
                "research_rounds": 0,
                "require_min_buys": require_min_buys,
                "require_min_buys_met": False,
            }

        for round_num in range(1, max_rounds + 1):
            rounds_completed = round_num
            if on_round_start:
                await on_round_start(round_num, max_rounds)
            print(f"\n🔍 Stage 2 (round {round_num}/{max_rounds}): Running Research Agents...")

            round_signals = await research_runner(trigger_time, data_factors)
            round_signals = _enrich_signals_with_technical_factors(
                round_signals,
                data_factors,
                trigger_time=trigger_time,
            )
            round_signals = await self._enrich_round_signals_financial(
                round_signals,
                trigger_time=trigger_time,
            )
            for signal in round_signals:
                signal["research_round"] = round_num
            had_new_signals = len(round_signals) > 0
            all_research_signals.extend(round_signals)

            if not had_new_signals and require_min_buys > 0:
                stall_rounds += 1
                no_new_warning = (
                    f"stall_new_signals={stall_rounds}"
                    f",limit={max_stall_rounds},round={round_num}"
                )
                if stall_rounds >= max_stall_rounds:
                    print(
                        f"⚠️  No new signals for {stall_rounds} consecutive round(s) "
                        f"(limit {max_stall_rounds}); stopping research retry loop."
                    )
                    self.system_health["warnings"].append(no_new_warning)
                    break
            else:
                stall_rounds = 0

            print(
                f"✅ Research round {round_num}: {len(round_signals)} new signals, "
                f"{len(all_research_signals)} total"
            )

            signal_groups = self._select_signal_groups(
                research_signals=all_research_signals,
                trigger_time=trigger_time,
                market_context=market_context,
                system_health=self.system_health,
            )
            buy_signals = signal_groups["buy_signals"]
            watchlist = signal_groups["watchlist"]
            consensus_signals = signal_groups.get("consensus_signals", [])
            print(
                f"✅ Selected {len(buy_signals)} buy signals and "
                f"{len(watchlist)} watchlist candidates"
            )

            round_stats = {
                "round": round_num,
                "new_signals": len(round_signals),
                "total_signals": len(all_research_signals),
                "buy_count": len(buy_signals),
                "watchlist_count": len(watchlist),
                "consensus_count": len(consensus_signals),
            }
            if on_round_complete:
                await on_round_complete(round_num, round_stats)

            if len(buy_signals) >= require_min_buys:
                met_requirement = True
                print(
                    f"✅ require_min_buys={require_min_buys} satisfied after round {round_num}"
                )
                break

            if require_min_buys > 0 and round_num < max_rounds:
                print(
                    f"⚠️  {len(buy_signals)} buy signal(s) < require_min_buys="
                    f"{require_min_buys}, retrying research (gates unchanged)..."
                )

        if require_min_buys > 0 and not met_requirement:
            print(
                f"⚠️  Stopped after {rounds_completed} round(s): "
                f"{len(buy_signals)} buy signal(s), require_min_buys={require_min_buys}"
            )
            self.system_health["warnings"].append(
                "require_min_buys_unmet:"
                f"required={require_min_buys},got={len(buy_signals)},rounds={rounds_completed}"
            )

        return {
            "research_signals": all_research_signals,
            "buy_signals": buy_signals,
            "watchlist": watchlist,
            "consensus_signals": consensus_signals,
            "research_rounds": rounds_completed,
            "require_min_buys": require_min_buys,
            "require_min_buys_met": met_requirement,
        }

    async def run(self, trigger_time: str) -> Dict:
        """
        Run the entire trading company workflow.

        Args:
            trigger_time: Trigger time for analysis

        Returns:
            Dictionary with data_factors, research_signals, and best_signals
        """
        print(f"🚀 Starting Trade Company Analysis at {trigger_time}")
        print("=" * 80)
        self.system_health = {"tool_error_count": 0, "agent_error_count": 0, "warnings": []}

        # Stage 0: Scan the full tradable universe with quantitative factors.
        print("\n🔎 Stage 0: Full-market quantitative screening...")
        self.quantitative_screen_result = await self.quantitative_screener.screen(trigger_time)
        quantitative_candidates = self.quantitative_screen_result.get("candidates") or []
        self.quantitative_candidates_by_code = {
            _normalize_stock_code(item.get("symbol_code")): item
            for item in quantitative_candidates
            if _normalize_stock_code(item.get("symbol_code"))
        }
        if self.quantitative_screen_result.get("status") != "ok":
            self.system_health["warnings"].append(
                "quantitative_screen_failed:"
                + ",".join(self.quantitative_screen_result.get("errors") or ["unknown"])
            )
        print(
            "✅ Quantitative screen: "
            f"universe={self.quantitative_screen_result.get('universe_count', 0)}, "
            f"scanned={self.quantitative_screen_result.get('scanned_count', 0)}, "
            f"passed={self.quantitative_screen_result.get('passed_count', 0)}, "
            f"research_candidates={len(quantitative_candidates)}"
        )

        # Stage 1: Run Data Agents in parallel
        print("\n📊 Stage 1: Running Data Agents...")
        data_factors = await self._run_data_agents(trigger_time)
        data_factor_errors = count_data_factor_tool_errors(data_factors)
        if data_factor_errors:
            self.system_health["tool_error_count"] += data_factor_errors
            self.system_health["warnings"].append(f"data_factor_errors={data_factor_errors}")
        print(f"✅ Data Agents completed: {len(data_factors)} factors generated")

        market_context = self._build_market_context(data_factors, trigger_time=trigger_time)

        # Stage 2+3: Research + strict gate selection; retry research until min buys met
        print("\n🎯 Stage 2+3: Research and buy selection (strict gates)...")
        selection = await self._run_research_and_select_until_min_buys(
            trigger_time=trigger_time,
            data_factors=data_factors,
            market_context=market_context,
        )
        research_signals = selection["research_signals"]
        buy_signals = selection["buy_signals"]
        watchlist = selection["watchlist"]
        consensus_signals = selection.get("consensus_signals", [])

        print("\n" + "=" * 80)
        print("✅ Trade Company Analysis Completed")

        result = {
            "trigger_time": trigger_time,
            "data_factors": data_factors,
            "research_signals": research_signals,
            "buy_signals": buy_signals,
            "watchlist": watchlist,
            "consensus_signals": consensus_signals,
            "quantitative_screen": self.quantitative_screen_result,
            "quantitative_candidates": quantitative_candidates,
            # Backward-compatible alias. From here on this means passed-gate buys only.
            "best_signals": buy_signals,
            "logic_version": {
                "schema": "trade_decision.v2",
                "strategy_id": (self.strategy or {}).get("id"),
                "workspace_root": str(WORKSPACE_ROOT),
                "generated_by": "main_loop.SimpleTradeCompany",
            },
            "market_context": market_context,
            "system_health": self.system_health,
            "strategy": self.strategy,
            "research_rounds": selection["research_rounds"],
            "require_min_buys": selection["require_min_buys"],
            "require_min_buys_met": selection["require_min_buys_met"],
        }

        generate_trade_decision_report(result)

        # Stage 4: Record signals and evaluate past performance
        print("\n���� Stage 4: Performance tracking...")
        await self.performance_tracker.record_signals(trigger_time, buy_signals)
        await self.performance_tracker.evaluate_pending()
        perf_stats = self.performance_tracker.get_summary_stats()
        if perf_stats["total_signals"] > 0:
            print(f"   Historical win rate: {perf_stats['win_rate']:.1f}% ({perf_stats['total_signals']} signals)")
        result["performance_stats"] = perf_stats

        # Stage 4.5: Record signals for tier-based tracking (NEW)
        # Track both passed-buy and watchlist candidates so downstream evaluation can
        # compare pass vs watch and calibrate tier confidence over time.
        tier_signals = list(buy_signals or []) + list(watchlist or [])
        if tier_signals and hasattr(self, 'signal_tracker'):
            self.signal_tracker.record_signals(
                signals=tier_signals,
                trigger_time=trigger_time,
                metadata={
                    "market_regime": selection.get("market_regime"),
                    "regime_confidence": selection.get("regime_confidence"),
                    "strategy": self.strategy.get("name", "default"),
                }
            )
            print(f"   📊 Recorded {len(tier_signals)} signals for tier-based tracking")

        return result

    async def _run_data_agents(self, trigger_time: str) -> List:
        """Run all data agents (pipelines) in parallel"""
        tasks = []

        for agent_id, pipeline in self.data_agents.items():
            task = asyncio.create_task(pipeline.run(trigger_time))
            tasks.append((agent_id, task))

        results = []
        for agent_id, task in tasks:
            try:
                result = await task
                if result and result.get("context_string"):
                    results.append(result)
                    self._print_data_agent_result(result)
            except Exception as e:
                print(f"❌ Data Agent {agent_id} failed: {e}")

        return results

    async def _run_research_agents(
        self, trigger_time: str, data_factors: List
    ) -> List[Dict]:
        """Run all research agents in parallel"""
        tasks = []

        for agent_id, agent in self.research_agents.items():
            # Build background information for this agent
            research_factors = list(data_factors or [])
            quantitative_factor = self._quantitative_context_factor()
            if quantitative_factor:
                research_factors.append(quantitative_factor)
            background = agent.build_background_information(
                trigger_time, agent.config.belief, research_factors
            )

            input_data = ResearchAgentInput(
                trigger_time=trigger_time,
                background_information=background,
            )

            task = asyncio.create_task(agent.run(input_data))
            tasks.append((agent_id, agent, task))

        all_signals = []
        for agent_id, agent, task in tasks:
            try:
                result = await task
                if result:
                    self._update_system_health_from_agent(result, agent)

                    # Parse signals from result
                    signals = self._parse_signals(result)
                    signals = self._restrict_to_quantitative_candidates(signals)

                    # Add agent metadata
                    for i, signal in enumerate(signals[:5]):  # Max 5 signals per agent
                        signal["agent_id"] = agent_id
                        signal["agent_name"] = agent.config.agent_name
                        signal["signal_index"] = i + 1
                        all_signals.append(signal)

                    if signals:
                        self._print_research_agent_result(agent.config.agent_name, signals)
                    elif not str(getattr(result, "final_result", "") or "").strip():
                        self.system_health["agent_error_count"] += 1
                        self.system_health["warnings"].append(
                            f"agent_{agent_id}_empty_final_result"
                        )
                else:
                    self.system_health["agent_error_count"] += 1
                    self.system_health["warnings"].append(
                        f"agent_{agent_id}_empty_result"
                    )

            except Exception as e:
                print(f"❌ Research Agent {agent_id} failed: {e}")
                self.system_health["agent_error_count"] += 1
                self.system_health["warnings"].append(f"agent_{agent_id}_failed")

        return all_signals

    def _quantitative_context_factor(self) -> Dict[str, Any] | None:
        if not self.quantitative_screener.config.enabled:
            return None
        return {
            "agent_name": "quantitative_universe_screener",
            "trigger_time": self.quantitative_screen_result.get("trigger_time", ""),
            "context_string": self.quantitative_screen_result.get("context_string", ""),
        }

    def _restrict_to_quantitative_candidates(
        self,
        signals: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if (
            not self.quantitative_screener.config.enabled
            or self.quantitative_screen_fail_open
        ):
            return signals

        filtered = []
        for signal in signals or []:
            code = _normalize_stock_code(signal.get("symbol_code"))
            candidate = self.quantitative_candidates_by_code.get(code)
            if not candidate:
                continue
            signal["technical_factor"] = dict(candidate.get("technical_factor") or {})
            signal["quantitative_score"] = candidate.get("quantitative_score")
            signal["quantitative_screen"] = candidate.get("quantitative_screen") or {}
            filtered.append(signal)
        return filtered

    def _parse_signals(self, result) -> List[Dict]:
        """Parse preferred JSON output, with legacy XML compatibility."""
        thinking_text = getattr(result, "final_result_thinking", "") or ""
        final_text = getattr(result, "final_result", "") or ""
        thinking = thinking_text.split("<Output>")[0].strip()
        output = final_text.split("<Output>")[-1].strip()
        if not output:
            # Recover structured output when a provider misplaces it in
            # reasoning_content instead of the visible content channel.
            output = thinking_text.split("<Output>")[-1].strip()

        json_signals = parse_json_signals(output, thinking=thinking)
        if json_signals:
            for signal in json_signals:
                self._fix_signal_symbol(signal)
            return json_signals

        signals = []
        try:
            # Find all signal blocks
            signal_blocks = re.findall(r'<signal>(.*?)</signal>', output, flags=re.DOTALL)

            for signal_block in signal_blocks:
                try:
                    signal = self._parse_single_signal(signal_block, thinking)
                    if signal:
                        signals.append(signal)
                except Exception as e:
                    print(f"Error parsing individual signal: {e}")
                    continue

        except Exception as e:
            print(f"Error parsing signals: {e}")

        return signals

    def _parse_single_signal(self, signal_block: str, thinking: str) -> Dict:
        """Parse a single signal block"""
        try:
            has_opportunity = re.search(
                r"<has_opportunity>(.*?)</has_opportunity>", signal_block, flags=re.DOTALL
            ).group(1).strip()

            action = re.search(
                r"<action>(.*?)</action>", signal_block, flags=re.DOTALL
            ).group(1).strip()

            symbol_code = re.search(
                r"<symbol_code>(.*?)</symbol_code>", signal_block, flags=re.DOTALL
            ).group(1).strip()

            symbol_name = re.search(
                r"<symbol_name>(.*?)</symbol_name>", signal_block, flags=re.DOTALL
            ).group(1).strip()

            # Parse evidence list
            evidence_list_str = re.search(
                r"<evidence_list>(.*?)</evidence_list>", signal_block, flags=re.DOTALL
            ).group(1)

            evidence_list = []
            for item in evidence_list_str.split("<evidence>"):
                if '</evidence>' not in item:
                    continue

                evidence_description = item.split("</evidence>")[0].strip()

                try:
                    evidence_time = re.search(
                        r"<time>(.*?)</time>", item, flags=re.DOTALL
                    ).group(1).strip()
                except (AttributeError, TypeError):
                    evidence_time = "N/A"

                try:
                    evidence_from_source = re.search(
                        r"<from_source>(.*?)</from_source>", item, flags=re.DOTALL
                    ).group(1).strip()
                except (AttributeError, TypeError):
                    evidence_from_source = "N/A"

                evidence_list.append({
                    "description": evidence_description,
                    "time": evidence_time,
                    "from_source": evidence_from_source,
                })

            # Parse limitations (optional — LLM may omit this block)
            limitations_match = re.search(
                r"<limitations>(.*?)</limitations>", signal_block, flags=re.DOTALL
            )
            if limitations_match:
                limitations = [
                    l.strip()
                    for l in re.findall(
                        r"<limitation>(.*?)</limitation>", limitations_match.group(1), flags=re.DOTALL
                    )
                ]
            else:
                limitations = []

            # Parse probability
            probability = re.search(
                r"<probability>(.*?)</probability>", signal_block, flags=re.DOTALL
            ).group(1).strip()

            try:
                symbol_name, symbol_code = GLOBAL_MARKET_MANAGER.fix_symbol_code(
                    "CN-Stock", symbol_name, symbol_code
                )
            except Exception:
                pass

            return validate_research_signal({
                "thinking": thinking,
                "has_opportunity": has_opportunity,
                "action": action,
                "symbol_code": symbol_code,
                "symbol_name": symbol_name,
                "evidence_list": evidence_list,
                "limitations": limitations,
                "probability": probability,
                "data_quality_warnings": self._extract_data_quality_warnings(limitations, thinking),
            })

        except Exception as e:
            print(f"Error parsing single signal: {e}")
            return None

    def _fix_signal_symbol(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        try:
            symbol_name, symbol_code = GLOBAL_MARKET_MANAGER.fix_symbol_code(
                "CN-Stock",
                str(signal.get("symbol_name") or ""),
                str(signal.get("symbol_code") or ""),
            )
            signal["symbol_name"] = symbol_name
            signal["symbol_code"] = symbol_code
        except Exception:
            pass
        return signal

    def _extract_data_quality_warnings(self, limitations: List[str], thinking: str) -> List[str]:
        warning_tags = []
        text = "\n".join(limitations or []) + "\n" + (thinking or "")
        mapping = {
            "code_uncertain": ["代码推断", "代码识别风险", "需再确认"],
            "missing_price": ["未能实时核对", "价格", "技术形态"],
            "high_volatility": ["波动", "追高", "冲高回落"],
        }
        if text_indicates_tool_failure(text):
            warning_tags.append("tool_error")
        for tag, keywords in mapping.items():
            if any(keyword in text for keyword in keywords):
                warning_tags.append(tag)
        return warning_tags

    def _select_signal_groups(
        self,
        research_signals: List[Dict],
        trigger_time: str,
        market_context: Dict[str, Any],
        system_health: Dict[str, Any],
    ) -> Dict[str, List[Dict]]:
        """
        Select passed-gate buy signals and keep rejected candidates separate.
        使用���场环���识���和���号分级系统
        """
        if not research_signals:
            return {
                "buy_signals": [],
                "watchlist": [],
                "consensus_signals": [],
                "market_regime": "neutral",
                "regime_confidence": 50.0,
                "regime_reasons": [],
                "signal_tiers": {},
            }

        # 1. 市场���境识别
        regime, regime_confidence, regime_reasons = self.market_regime_detector.detect(
            market_context=market_context,
            index_data=pd.DataFrame(market_context.get("index_snapshot", {}).get("market_index_df") or []) if isinstance(market_context, dict) and market_context.get("index_snapshot", {}).get("market_index_df") else None,
        )
        print(f"\n市场���境识���: {regime} (置信���: {regime_confidence:.1f}%)")
        for reason in regime_reasons:
            print(f"  - {reason}")

        # 2. 共���聚合
        aggregator = getattr(self, "consensus_aggregator", None)
        consensus_signals = (
            aggregator.aggregate(research_signals, trigger_time)
            if aggregator
            else list(research_signals)
        )

        # 3. ���序打分
        ranked = self.signal_ranker.rank_signals(
            research_signals=consensus_signals,
            trigger_time=trigger_time,
            market_context=market_context,
            system_health=system_health,
        )

        # 4. 信���分���（核心改进）
        signal_tiers = self.signal_tier_classifier.classify(
            signals=ranked,
            market_regime=regime
        )

        # ���印分级结果
        print(self.signal_tier_classifier.get_tier_summary(signal_tiers))

        # 5. 构���最终���入信号列表（A+B级）
        buy_signals = signal_tiers.get("tier_A", []) + signal_tiers.get("tier_B", [])

        # 6. ���建���察列���（C��� + 部分watch）
        watchlist = self.signal_ranker.build_watchlist(
            research_signals=consensus_signals,
            trigger_time=trigger_time,
            market_context=market_context,
            system_health=system_health,
            top_k=5,
        )
        buy_keys = {
            (sig.get("symbol_code") or sig.get("symbol_name") or "").strip()
            for sig in buy_signals
        }
        watchlist = [
            sig for sig in watchlist
            if (
                (sig.get("symbol_code") or sig.get("symbol_name") or "").strip() not in buy_keys
                and str(sig.get("buy_decision") or "").lower() != "buy"
            )
        ]
        # ���加C���信号到观察列表
        for c_signal in signal_tiers.get("tier_C", []):
            code = (c_signal.get("symbol_code") or c_signal.get("symbol_name") or "").strip()
            if code not in buy_keys:
                watchlist.append(c_signal)

        return {
            "buy_signals": buy_signals,
            "watchlist": watchlist[:8],  # 限制观���列表���度
            "consensus_signals": consensus_signals,
            "market_regime": regime,
            "regime_confidence": regime_confidence,
            "regime_reasons": regime_reasons,
            "signal_tiers": signal_tiers,
        }

    def _select_best_signals(
        self,
        research_signals: List[Dict],
        trigger_time: str,
        market_context: Dict[str, Any],
        system_health: Dict[str, Any],
    ) -> List[Dict]:
        """Backward-compatible helper returning passed-gate buys only."""
        return self._select_signal_groups(
            research_signals=research_signals,
            trigger_time=trigger_time,
            market_context=market_context,
            system_health=system_health,
        )["buy_signals"]

    def _load_index_market_snapshot(self, trigger_time: str) -> Dict[str, Any]:
        """
        Build a lightweight market snapshot from the major CN indices so that
        regime detection uses actual price/MAs rather than only text keywords.
        """
        snapshot: Dict[str, Any] = {
            "index_available": False,
            "index_ma_trend": "neutral",
            "index_ma_reasons": [],
            "indices": {},
        }
        try:
            from utils.cn_price_provider import get_index_daily
            from utils.date_utils import get_latest_completed_trading_date

            trade_date = get_latest_completed_trading_date(trigger_time)
            start_date, end_date = get_trading_date_range(
                end_date=trade_date,
                count=80,
                include_end=True,
            )
            symbols = {
                "sh000001": "上证指数",
                "sz399006": "创业板指",
                "sh000688": "科创50",
            }
            reason_bits = []
            for symbol, name in symbols.items():
                try:
                    df = get_index_daily(symbol, start_date, end_date, False)
                    if df is None or df.empty or len(df) < 20:
                        continue
                    closes = df["close"].dropna().astype(float)
                    latest = float(closes.iloc[-1])
                    ma5 = float(closes.iloc[-5:].mean())
                    ma10 = float(closes.iloc[-10:].mean())
                    ma20 = float(closes.iloc[-20:].mean())
                    snapshot["indices"][name] = {
                        "close": round(latest, 2),
                        "ma5": round(ma5, 2),
                        "ma10": round(ma10, 2),
                        "ma20": round(ma20, 2),
                        "above_ma20": bool(latest >= ma20),
                    }
                    if ma5 > ma10 > ma20 and latest > ma5:
                        reason_bits.append(f"{name}:多头排列")
                    elif ma5 < ma10 < ma20 and latest < ma5:
                        reason_bits.append(f"{name}:空头排列")
                    else:
                        reason_bits.append(f"{name}:震荡")
                except Exception:
                    continue

            if len(snapshot["indices"]) >= 2:
                snapshot["index"] = True
                snapshot["index_trend"] = "up" if reason_bits.count("多头排列") >= 2 else (
                    "down" if reason_bits.count("空头排列") >= 2 else "neutral"
                )
                snapshot["index_reasons"] = reason_bits
                # Keep the raw SH index frame for MarketRegimeDetector index-technical analysis.
                try:
                    sh_frame = get_index_daily("sh000001", start_date, end_date, False)
                    if sh_frame is not None and not sh_frame.empty:
                        frame = sh_frame[["date", "close"]].dropna().reset_index(drop=True)
                        snapshot["market_index_df"] = [
                            {
                                "date": str(row.get("date") or row.get("日期") or ""),
                                "close": row.get("close", row.get("收盘")),
                            }
                            for row in frame.to_dict(orient="records")
                        ]
                except Exception:
                    pass
        except Exception as exc:
            print(f"⚠️ 指数快照失败: {exc}")
        return snapshot

    def _build_market_context(self, data_factors: List[Dict], trigger_time: str = "") -> Dict[str, Any]:
        context = {
            "market_trend": "neutral",
            "risk_sentiment": "neutral",
            "has_sector_flow_data": True,
            "has_fund_flow_data": False,
            "has_margin_data": False,
            "has_block_trade_data": False,
            "has_zt_seal_data": False,
            "data_source_count": len(data_factors or []),
            "index_snapshot": {},
        }

        # 1) 指数均线/收盘数据作为主依据（如果可用），文本关键词作为补充/兜底。
        index_snapshot = self._load_index_market_snapshot(trigger_time or "") if trigger_time else {}
        if index_snapshot.get("index"):
            context["index_snapshot"] = index_snapshot
            index_trend = str(index_snapshot.get("index_trend") or "neutral")
            if index_trend in {"up", "bullish", "bull"}:
                context["market_trend"] = "up"
            elif index_trend in {"down", "bearish", "bear"}:
                context["market_trend"] = "down"

        combined_text = "\n".join((factor.get("context_string") or "") for factor in data_factors or [])

        positive_trend_hits = sum(combined_text.count(keyword) for keyword in ["涨停", "普涨", "收涨", "上涨", "新高", "反弹"])
        negative_trend_hits = sum(combined_text.count(keyword) for keyword in ["回调", "下跌", "承压", "走弱", "回落"])

        # 仅在指数数据不可用时才退化到关键词计数；且不再让“回调/风险”等舆情词单方面压过均线多头。
        if not index_snapshot.get("index"):
            if positive_trend_hits > negative_trend_hits + 1:
                context["market_trend"] = "up"
            elif negative_trend_hits > positive_trend_hits + 1:
                context["market_trend"] = "down"

        risk_on_hits = sum(combined_text.count(keyword) for keyword in [
            "热钱", "共振", "净买入", "情绪回暖", "活跃",
            "主力吸筹", "融资净买入", "溢价成交", "封单极强",
        ])
        risk_off_hits = sum(combined_text.count(keyword) for keyword in [
            "恐慌", "避险", "风险偏好收敛", "谨慎",
            "主力出货", "融资净偿还", "大幅折价",
        ])
        if risk_on_hits > risk_off_hits + 1:
            context["risk_sentiment"] = "risk_on"
        elif risk_off_hits > risk_on_hits + 1:
            context["risk_sentiment"] = "risk_off"

        missing_flow_markers = [
            "资金流向数据", "未能成功获取", "数据缺失", "无法对行业资金偏好进行判断", "LLM分析失败", "连接异常"
        ]
        if any(marker in combined_text for marker in missing_flow_markers):
            context["has_sector_flow_data"] = False

        # 检测新 alpha 数据源是否有有效数据
        for factor in data_factors or []:
            agent_name = factor.get("agent_name", "")
            content = factor.get("context_string", "")
            if agent_name == "individual_fund_flow_agent" and "主力资金流" in content and factor_content_is_usable(content):
                context["has_fund_flow_data"] = True
            elif agent_name == "margin_trading_agent" and "融资融券" in content and factor_content_is_usable(content):
                context["has_margin_data"] = True
            elif agent_name == "block_trade_agent" and "大宗交易" in content and factor_content_is_usable(content):
                context["has_block_trade_data"] = True
            elif agent_name == "zt_seal_strength_agent" and "封单强度" in content and factor_content_is_usable(content):
                context["has_zt_seal_data"] = True

        return context

    def _update_system_health_from_agent(self, result, agent) -> None:
        count = summarize_research_agent_tool_errors(result, getattr(agent, "tool_calls", None))
        if count <= 0:
            return

        self.system_health["tool_error_count"] += count
        agent_name = getattr(getattr(agent, "config", None), "agent_name", "research_agent")
        self.system_health["warnings"].append(f"research_tool_errors={count}:{agent_name}")

    def _print_data_agent_result(self, factor):
        """Print data agent result"""
        print(f"\n{'=' * 60}")
        print(f"✅ [{factor.get('agent_name')}] Data Factor Ready")
        print(f"{'=' * 60}")
        context = factor.get('context_string', '')
        summary = context[:300] if context else "(No content)"
        print(summary)
        if len(context) > 300:
            print("...")
        print(f"{'=' * 60}\n")

    def _print_research_agent_result(self, agent_name: str, signals: List[Dict]):
        """Print research agent result"""
        print(f"\n{'=' * 60}")
        print(f"✅ [{agent_name}] Research Signals Ready")
        print(f"{'=' * 60}")
        for i, signal in enumerate(signals, 1):
            symbol = signal.get("symbol_name") or signal.get("symbol_code") or "—"
            action = signal.get("action") or "—"
            print(f"{i}. {symbol} | {action}")
        print(f"{'=' * 60}\n")


async def main():
    """Main entry point for testing"""
    company = SimpleTradeCompany()

    # Use current time or specify a time
    trigger_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # trigger_time = "2024-01-23 09:00:00"  # For testing with specific time

    result = await company.run(trigger_time)

    print("\n" + "=" * 80)
    print("📊 Final Summary:")
    print(f"   Trigger Time: {result['trigger_time']}")
    print(f"   Data Factors: {len(result['data_factors'])}")
    print(f"   Research Signals: {len(result['research_signals'])}")
    print(f"   Best Signals: {len(result['best_signals'])}")
    print(f"   Research Rounds: {result.get('research_rounds', 1)}")
    print(f"   Require Min Buys Met: {result.get('require_min_buys_met', True)}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
