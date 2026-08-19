"""
Agent 级别报告生成与汇总刷新。
"""
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from config.config import WORKSPACE_ROOT


def _format_optional_number(value, precision: int = 2, suffix: str = "") -> str:
    if value is None or value == "":
        return "N/A"
    if str(value).strip().upper() in {"N/A", "NAN", "NONE", "--"}:
        return "N/A"
    try:
        number = float(value)
        if not math.isfinite(number):
            return "N/A"
        return f"{number:.{precision}f}{suffix}"
    except (TypeError, ValueError):
        return f"{value}{suffix}"


def _safe_trigger_time(trigger_time: str) -> str:
    return trigger_time.replace(" ", "_").replace(":", "-")


def _results_dir() -> Path:
    return WORKSPACE_ROOT / "results"


def _get_text(cn_text: str, en_text: str) -> str:
    market_type = os.environ.get("CONTEST_TRADE_MARKET", "CN-Stock")
    return en_text if market_type == "US-Stock" else cn_text


def _clean_context(context_string: str) -> str:
    return re.sub(r"\[Batch \d+\]", "", context_string or "").strip()


def _format_technical_summary(signal: Dict) -> str:
    factor = signal.get("technical_factor") or {}
    if factor:
        report_date = factor.get("report_date") or "N/A"
        weekly_trend = factor.get("weekly_trend") or "N/A"
        weekly_score = _format_optional_number(factor.get("weekly_trend_score"))
        relative_strength_20d = _format_optional_number(
            factor.get("relative_strength_20d_pct"),
            suffix="%",
        )
        relative_strength_60d = _format_optional_number(
            factor.get("relative_strength_60d_pct"),
            suffix="%",
        )
        relative_strength_score = _format_optional_number(
            factor.get("relative_strength_score")
        )
        daily_entry_score = _format_optional_number(factor.get("daily_entry_score"))
        return (
            f"{report_date}: 收盘{_format_optional_number(factor.get('close'))}, "
            f"涨跌幅{_format_optional_number(factor.get('change_pct'), suffix='%')}, "
            f"MA20距离{_format_optional_number(factor.get('ma20_deviation_pct'), suffix='%')}, "
            f"RSI={_format_optional_number(factor.get('rsi'))}, "
            f"MACD={_format_optional_number(factor.get('macd'), precision=3)}, "
            f"量比={_format_optional_number(factor.get('volume_ratio'))}, "
            f"额比={_format_optional_number(factor.get('amount_ratio'))}, "
            f"量趋势={_format_optional_number(factor.get('volume_ma5_ma20_ratio'))}, "
            f"布林={factor.get('bollinger') or 'N/A'}, "
            f"周线={weekly_trend}({weekly_score}), "
            f"相对强度20日={relative_strength_20d}, "
            f"60日={relative_strength_60d}, "
            f"RS评分={relative_strength_score}, "
            f"日线入场={daily_entry_score}"
        )

    kline_description = str(signal.get("kline_description") or "").strip()
    if kline_description:
        return kline_description.splitlines()[-1]

    warnings = signal.get("data_quality_warnings") or []
    if "missing_kline" in warnings:
        return _get_text("K线/均线数据缺失", "K-line/MA data missing")
    return _get_text("未提供K线/均线数据", "No K-line/MA data provided")


def _format_financial_consistency(signal: Dict) -> str:
    gate = signal.get("next_day_gate_report") or {}
    reasons = gate.get("failed_reasons") or gate.get("risk_flags") or []
    financial_flags = [
        str(r) for r in reasons
        if "financial" in str(r).lower()
        or "statement_conflict" in str(r).lower()
        or "claim_conflict" in str(r).lower()
    ]
    if financial_flags:
        base = ", ".join(sorted(set(financial_flags))) + "; " + "请以正式财报/公告口径为准"
    else:
        # Also check scorecard/data_quality reason
        quality_reason = signal.get("data_quality_reason") or (signal.get("next_day_factor_scorecard") or {}).get("data_quality_reason", "")
        if "financial-conflict" in quality_reason:
            base = "data_quality_financial_conflict"
        else:
            base = "ok"
    report = signal.get("financial_report") or {}
    if report:
        extra = f" report_yoy={report.get('net_profit_yoy')}, period={report.get('period')}"
        if base == "ok":
            base = "ok" + extra
        else:
            base += extra
    return base


def generate_data_agent_report(factor: Dict) -> Optional[Path]:
    """
    为单个 Data Agent 生成 Markdown 报告。
    @generated AI Assistant - 2026-08-05 19:32:00
    """
    agent_name = factor.get("agent_name")
    trigger_time = factor.get("trigger_time")
    if not agent_name or not trigger_time:
        return None

    safe_time = _safe_trigger_time(trigger_time)
    report_dir = _results_dir() / "data_reports" / agent_name
    report_dir.mkdir(parents=True, exist_ok=True)
    save_path = report_dir / f"{safe_time}.md"

    context_string = _clean_context(factor.get("context_string", ""))
    content = f"""# {_get_text('数据分析报告', 'Data Analysis Report')} — {agent_name}

**{_get_text('分析时间', 'Analysis Time')}**: {trigger_time}  
**{_get_text('数据代理', 'Data Agent')}**: {agent_name}  
**{_get_text('报告生成时间', 'Report Generation Time')}**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## {_get_text('分析内容', 'Analysis Content')}

{context_string if context_string else _get_text('暂无分析内容', 'No analysis content available')}

---

## {_get_text('免责声明', 'Disclaimer')}

{_get_text('本报告由 ContestTrade 自动生成，仅供参考，不构成投资建议。', 'This report is auto-generated by ContestTrade for reference only.')}
"""
    save_path.write_text(content, encoding="utf-8")
    return save_path


def generate_research_agent_report(result: Dict, agent_name: str) -> Optional[Path]:
    """
    为单个 Research Agent 生成 Markdown 报告。
    @generated AI Assistant - 2026-08-05 19:32:00
    """
    trigger_time = result.get("trigger_time")
    if not trigger_time:
        return None

    safe_time = _safe_trigger_time(trigger_time)
    report_dir = _results_dir() / "research_reports" / agent_name
    report_dir.mkdir(parents=True, exist_ok=True)
    save_path = report_dir / f"{safe_time}.md"

    final_result = (result.get("final_result") or "").strip()
    belief = result.get("belief") or ""
    task = result.get("task") or ""

    content = f"""# {_get_text('研究报告', 'Research Report')} — {agent_name}

**{_get_text('分析时间', 'Analysis Time')}**: {trigger_time}  
**{_get_text('研究代理', 'Research Agent')}**: {agent_name}  
**{_get_text('交易信念', 'Trading Belief')}**: {belief}  
**{_get_text('报告生成时间', 'Report Generation Time')}**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## {_get_text('研究任务', 'Research Task')}

{task if task else "—"}

---

## {_get_text('研究结论', 'Research Conclusion')}

{final_result if final_result else _get_text('暂无研究结论', 'No research conclusion available')}

---

## {_get_text('免责声明', 'Disclaimer')}

{_get_text('本报告由 ContestTrade 自动生成，仅供参考，不构成投资建议。', 'This report is auto-generated by ContestTrade for reference only.')}
"""
    save_path.write_text(content, encoding="utf-8")
    return save_path


def load_factors_for_trigger(trigger_time: str) -> Dict:
    """
    加载指定 trigger_time 下所有已完成的 Data Agent 因子。
    @generated AI Assistant - 2026-08-05 19:32:00
    """
    factors_data = {"trigger_time": trigger_time, "agents": {}}
    timestamp_str = _safe_trigger_time(trigger_time)
    factors_dir = WORKSPACE_ROOT / "factors"
    if not factors_dir.exists():
        return factors_data

    for agent_dir in factors_dir.iterdir():
        if not agent_dir.is_dir():
            continue
        files = list(agent_dir.glob(f"{timestamp_str}*.json"))
        if not files:
            continue
        with open(files[0], "r", encoding="utf-8") as f:
            factors_data["agents"][agent_dir.name] = json.load(f)
    return factors_data


def refresh_combined_data_report(trigger_time: str) -> Optional[Path]:
    """
    根据当前已完成的 Data Agent 因子，刷新汇总数据报告。
    @generated AI Assistant - 2026-08-05 19:32:00
    """
    factors_data = load_factors_for_trigger(trigger_time)
    agents = factors_data.get("agents") or {}
    if not agents:
        return None

    safe_time = _safe_trigger_time(trigger_time)
    report_dir = _results_dir() / "data_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    save_path = report_dir / f"data_report_{safe_time}.md"

    lines = [
        f"# ContestTrade {_get_text('数据分析汇总报告', 'Data Analysis Summary Report')}",
        "",
        f"**{_get_text('分析时间', 'Analysis Time')}**: {trigger_time}  ",
        f"**{_get_text('已完成代理', 'Completed Agents')}**: {len(agents)}  ",
        f"**{_get_text('报告生成时间', 'Report Generation Time')}**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
    ]
    for agent_name, agent_data in agents.items():
        lines.append(f"## {agent_name}")
        lines.append("")
        context = _clean_context(agent_data.get("context_string", ""))
        lines.append(context if context else _get_text("暂无分析内容", "No analysis content available"))
        lines.append("")
        lines.append("---")
        lines.append("")

    save_path.write_text("\n".join(lines), encoding="utf-8")
    return save_path


def _format_trade_plan(sig: Dict) -> str:
    plan = sig.get("trade_plan") or {}
    if not plan:
        return "N/A"
    if plan.get("status") != "ok":
        return f"不可用({plan.get('error', plan.get('status', 'unknown'))})"
    inds = plan.get("indicators") or {}
    levels = plan.get("levels") or {}
    p = plan.get("plan") or {}
    pass_flag = sig.get("trade_plan_pass")
    pass_label = "PASS" if pass_flag is True else ("FAIL" if pass_flag is False else "N/A")
    return (
        f"[{pass_label}] "
        f"RSI={inds.get('rsi', 'N/A')}, "
        f"VWAP20={inds.get('vwap_20', 'N/A')}, "
        f"EMA8/13/21={inds.get('ema8', 'N/A')}/{inds.get('ema13', 'N/A')}/{inds.get('ema21', 'N/A')}, "
        f"量比={inds.get('volume_ratio', 'N/A')}, "
        f"额比={inds.get('amount_ratio', 'N/A')}, "
        f"量趋势={inds.get('volume_ma5_ma20_ratio', 'N/A')}, "
        f"支撑1/2={levels.get('support_1', 'N/A')}/{levels.get('support_2', 'N/A')}, "
        f"压力1/2={levels.get('resistance_1', 'N/A')}/{levels.get('resistance_2', 'N/A')}, "
        f"入场={p.get('entry_zone_low', 'N/A')}-{p.get('entry_zone_high', 'N/A')}, "
        f"止损={p.get('stop_loss', 'N/A')}({p.get('stop_loss_pct', '')}%), "
        f"目标1/2={p.get('take_profit_1', 'N/A')}/{p.get('take_profit_2', 'N/A')}, "
        f"RR={p.get('rr_1', 'N/A')}, "
        f"仓位={p.get('suggested_position_size_pct', 'N/A')}%"
    )


def generate_trade_decision_report(trade_result: Dict) -> Optional[Path]:
    """Generate final next-day buy decision report."""
    trigger_time = trade_result.get("trigger_time")
    if not trigger_time:
        return None

    safe_time = _safe_trigger_time(trigger_time)
    report_dir = _results_dir() / "trade_decisions"
    report_dir.mkdir(parents=True, exist_ok=True)

    json_path = report_dir / f"{safe_time}.json"
    md_path = report_dir / f"{safe_time}.md"

    def _json_default(obj):
        if hasattr(obj, "isoformat"):
            try:
                return obj.isoformat()
            except Exception:
                return str(obj)
        return str(obj)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(trade_result, f, ensure_ascii=False, indent=2, default=_json_default)

    def _is_buy_signal(signal: Dict) -> bool:
        decision = str(signal.get("buy_decision") or "").lower()
        if decision:
            return decision == "buy"
        gate = signal.get("next_day_gate_report") or {}
        return bool(gate.get("passed", False))

    legacy_best_signals = trade_result.get("best_signals") or []
    explicit_buy_signals = trade_result.get("buy_signals")
    if isinstance(explicit_buy_signals, list):
        buy_signals = explicit_buy_signals
    else:
        buy_signals = [
            x for x in legacy_best_signals
            if _is_buy_signal(x)
        ]

    explicit_watchlist = trade_result.get("watchlist")
    if isinstance(explicit_watchlist, list):
        watchlist = explicit_watchlist
    else:
        watchlist = [
            x for x in legacy_best_signals
            if not _is_buy_signal(x)
        ]
    market_context = trade_result.get("market_context") or {}
    system_health = trade_result.get("system_health") or {}
    quantitative_screen = trade_result.get("quantitative_screen") or {}

    lines = [
        f"# {_get_text('次日买入决策报告', 'Next-Day Buy Decision Report')}",
        "",
        f"**{_get_text('分析时间', 'Analysis Time')}**: {trigger_time}  ",
        f"**{_get_text('候选信号数', 'Candidate Signals')}**: {len(trade_result.get('research_signals') or [])}  ",
        f"**{_get_text('共识标的数', 'Consensus Symbols')}**: {len(trade_result.get('consensus_signals') or [])}  ",
        f"**{_get_text('通过门控数', 'Passed Gates')}**: {len(buy_signals)}  ",
        f"**{_get_text('观察候选数', 'Watchlist Candidates')}**: {len(watchlist)}  ",
        f"**{_get_text('量化股票池数', 'Quantitative Universe')}**: {quantitative_screen.get('universe_count', 0)}  ",
        f"**{_get_text('量化通过数', 'Quantitative Passed')}**: {quantitative_screen.get('passed_count', 0)}  ",
        f"**{_get_text('量化研究候选数', 'Quantitative Research Candidates')}**: {len(trade_result.get('quantitative_candidates') or [])}  ",
    ]
    research_rounds = trade_result.get("research_rounds")
    if research_rounds:
        lines.append(f"**{_get_text('研究轮次', 'Research Rounds')}**: {research_rounds}  ")
    require_min_buys_met = trade_result.get("require_min_buys_met")
    if require_min_buys_met is not None:
        lines.append(
            f"**{_get_text('满足最少买入要求', 'Require Min Buys Met')}**: `{require_min_buys_met}`  "
        )
    lines.extend([
        "",
        "---",
        "",
        f"## {_get_text('市场环境', 'Market Context')}",
        "",
        f"- {_get_text('趋势', 'Trend')}: `{market_context.get('market_trend', '')}`",
        f"- {_get_text('风险偏好', 'Risk Sentiment')}: `{market_context.get('risk_sentiment', '')}`",
        f"- {_get_text('板块资金数据完整', 'Sector Flow Data Complete')}: `{market_context.get('has_sector_flow_data', '')}`",
        f"- {_get_text('系统工具错误数', 'System Tool Error Count')}: `{system_health.get('tool_error_count', 0)}`",
        f"- {_get_text('研究代理错误数', 'Research Agent Error Count')}: `{system_health.get('agent_error_count', 0)}`",
        f"- {_get_text('系统告警', 'System Warnings')}: `{', '.join(system_health.get('warnings') or []) or 'none'}`",
        "",
        f"## {_get_text('买入清单', 'Buy List')}",
        "",
    ])

    if not buy_signals:
        if quantitative_screen.get("status") == "error":
            lines.append(
                _get_text(
                    "全市场量化预筛选失败，未允许 Research Agent 绕过筛选。",
                    "Full-market quantitative screening failed; Research Agents were not allowed to bypass it.",
                )
            )
        elif (
            quantitative_screen.get("status") == "ok"
            and int(quantitative_screen.get("passed_count", 0) or 0) == 0
        ):
            lines.append(
                _get_text(
                    "没有股票通过全市场周线、相对强度和日线预筛选。",
                    "No stocks passed the full-market weekly, relative-strength, and daily pre-screen.",
                )
            )
        elif not (trade_result.get("research_signals") or []):
            lines.append(
                _get_text(
                    "研究 Agent 未产生可解析信号，请先检查最终报告输出、模型接口或 Agent 告警。",
                    "Research agents produced no parseable signals. Check final output, model access, or agent warnings first.",
                )
            )
        else:
            lines.append(
                _get_text(
                    "无满足次日买入门槛的标的。",
                    "No symbols pass next-day buy gates.",
                )
            )
        lines.append("")
    else:
        for i, sig in enumerate(buy_signals, start=1):
            code = sig.get("symbol_code") or ""
            name = sig.get("symbol_name") or ""
            score = sig.get("buy_score", "")
            prob = sig.get("probability_value", "")
            er = sig.get("expected_return_t1_pct", "")
            gate = sig.get("next_day_gate_report") or {}
            consensus = sig.get("consensus_report") or {}
            failed = ", ".join(gate.get("failed_reasons") or []) or "none"
            technical_summary = _format_technical_summary(sig)
            setup_meta = sig.get("setup_meta") or {}
            lines.extend([
                f"### {i}. {name} ({code})",
                "",
                f"- `buy_score`: `{score}`",
                f"- `probability_value`: `{prob} `(subjective confidence, not backtested)`",
                f"- `expected_return_t1_pct`: `{er} `(heuristic edge, not statistical expectation)`",
                f"- `setup_state`: `{setup_meta.get('risk_state', '')} / driver={setup_meta.get('driver_quality', '')}`",
                f"- `technical_summary`: `{technical_summary}`",
                f"- `buy_decision`: `{sig.get('buy_decision', '')}`",
                f"- `signal_contract_version`: `{sig.get('signal_contract_version', 'buy-signal.v1')}`",
                f"- `entry_timing`: `{sig.get('entry_timing', 'next_trading_day_open')}`",
                f"- `analysis_as_of_date`: `{sig.get('analysis_as_of_date', '')}`",
                f"- `risk_flags`: `{', '.join(sig.get('risk_flags') or []) or 'none'}`",
                f"- `consensus_action`: `{consensus.get('consensus_action', '')}`",
                f"- `consensus_confidence`: `{consensus.get('consensus_confidence', '')}`",
                f"- `agent_votes`: `buy={consensus.get('buy_vote_count', 0)}, watch={consensus.get('watch_vote_count', 0)}, sell={consensus.get('sell_vote_count', 0)}`",
                f"- `gate_failed_reasons`: `{failed}`",
                f"- `financial_consistency`: `{_format_financial_consistency(sig)}`",
                f"- `trade_plan`: `{_format_trade_plan(sig)}`",
                "",
            ])

    if watchlist:
        lines.extend([
            f"## {_get_text('观察清单（未通过门控）', 'Watchlist (Failed Gates)')}",
            "",
        ])
        for i, sig in enumerate(watchlist, start=1):
            code = sig.get("symbol_code") or ""
            name = sig.get("symbol_name") or ""
            score = sig.get("buy_score", "")
            prob = sig.get("probability_value", "")
            er = sig.get("expected_return_t1_pct", "")
            gate = sig.get("next_day_gate_report") or {}
            consensus = sig.get("consensus_report") or {}
            failed = ", ".join(gate.get("failed_reasons") or []) or "none"
            technical_summary = _format_technical_summary(sig)
            lines.extend([
                f"### {i}. {name} ({code})",
                "",
                f"- `buy_score`: `{score}`",
                f"- `probability_value`: `{prob}`",
                f"- `expected_return_t1_pct`: `{er}`",
                f"- `technical_summary`: `{technical_summary}`",
                f"- `buy_decision`: `{sig.get('buy_decision', '')}`",
                f"- `signal_contract_version`: `{sig.get('signal_contract_version', 'buy-signal.v1')}`",
                f"- `entry_timing`: `{sig.get('entry_timing', 'next_trading_day_open')}`",
                f"- `analysis_as_of_date`: `{sig.get('analysis_as_of_date', '')}`",
                f"- `risk_flags`: `{', '.join(sig.get('risk_flags') or []) or 'none'}`",
                f"- `consensus_action`: `{consensus.get('consensus_action', '')}`",
                f"- `consensus_confidence`: `{consensus.get('consensus_confidence', '')}`",
                f"- `agent_votes`: `buy={consensus.get('buy_vote_count', 0)}, watch={consensus.get('watch_vote_count', 0)}, sell={consensus.get('sell_vote_count', 0)}`",
                f"- `gate_failed_reasons`: `{failed}`",
                f"- `trade_plan`: `{_format_trade_plan(sig)}`",
                "",
            ])

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path
