#!/usr/bin/env python3
"""
TradingAgents-style investment decision report generator.

Reads replay candidate signals (buy_signals / watchlist / consensus_signals),
builds a Bull/Bear/Trader/Portfolio-Manager review using the project LLM, then
writes a Markdown report per candidate.

This tool does NOT modify backend gating/scoring/rules.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent

import sys
sys.path.insert(0, str(PROJECT_ROOT))

from models.llm_model import GLOBAL_LLM


# ---------------------------------------------------------------------------
# helper functions
# ---------------------------------------------------------------------------


async def llm_chat(user: str, system: str, temperature: float = 0.4) -> str:
    """Call the project's primary LLM."""
    resp = await GLOBAL_LLM.a_run(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=4000,
        verbose=False,
        thinking=False,
    )
    if resp and resp.content:
        return resp.content
    return "*LLM 未返回内容*"


async def fetch_financial_company(market: str, symbol: str, trigger_time: str) -> str:
    """Try to pull financial context via existing A-share tool; fallback gracefully."""
    if market != "CN-Stock":
        return "(当前仅CN-Stock支持财务工具)"
    try:
        from tools.corp_info_akshare import company_financial_info
        if hasattr(company_financial_info, "ainvoke"):
            return await company_financial_info.ainvoke({
                "market": market,
                "symbol": symbol,
                "task": "请提供最近一期主要财务数据、ROE、资产负债率、营收与净利增速；如果是多业务公司请说明各板块（如面板/光伏/半导体等）经营与风险。",
                "trigger_time": trigger_time,
            })
        return await company_financial_info(
            market=market,
            symbol=symbol,
            task="请提供最近一期主要财务数据、ROE、资产负债率、营收与净利增速；如果是多业务公司请说明各板块（如面板/光伏/半导体等）经营与风险。",
            trigger_time=trigger_time,
        )
    except Exception as exc:
        return f"(财务数据拉取失败: {exc})"


def signal_brief(signal: Dict) -> str:
    sc = signal.get("next_day_factor_scorecard") or {}
    tech = signal.get("technical_factor") or {}
    evidence = signal.get("evidence_list") or []
    votes = signal.get("agent_votes") or []
    consensus = signal.get("consensus_report") or {}
    limitations = signal.get("limitations") or []

    lines = []
    lines.append(f"股票: {signal.get('symbol_name')} ({signal.get('symbol_code')})")
    lines.append(f"系统评分: {signal.get('buy_score')}")
    lines.append(f"校准概率: {signal.get('probability_value')}")
    lines.append(f"决策: {signal.get('buy_decision')}")
    lines.append(f"共识: {consensus.get('consensus_action')} (agents={len(votes)})")
    lines.append("")

    if tech:
        lines.append("技术/量化:")
        lines.append(
            f"  MA20偏离: {tech.get('ma20_deviation_pct')}% | 涨跌幅: {tech.get('change_pct')}% | "
            f"RSI: {tech.get('rsi')} | 量比: {tech.get('volume_ratio')} | MACD: {tech.get('macd')} | "
            f"布林: {tech.get('bollinger')}"
        )
    lines.append(
        f"  周线: {sc.get('weekly_trend_score')} | RS: {sc.get('relative_strength_score')} | "
        f"日线: {sc.get('daily_entry_score')} | 催化: {sc.get('catalyst_score')} | "
        f"资金: {sc.get('capital_flow_score')} | 数据质量: {sc.get('data_quality_score')}"
    )
    lines.append(f"  MA20偏离: {sc.get('ma20_deviation_pct')} | 前日涨幅: {sc.get('prev_day_gain_pct')}")
    lines.append("")

    lines.append("证据:")
    for e in evidence[:10]:
        src = e.get("from_source") or "N/A"
        desc = e.get("description") or ""
        lines.append(f"  [{src}] {desc[:200]}")
    lines.append("")

    lines.append("共识投票:")
    for v in votes:
        lines.append(
            f"  agent={v.get('agent_name')} vote={v.get('vote')} prob={v.get('probability')} "
            f"evidence={v.get('evidence_count')}"
        )
    lines.append("")

    lines.append("风险/限制:")
    for lim in limitations[:5]:
        lines.append(f"  - {lim[:180]}")
    if not limitations:
        lines.append("  - 无显式限制")
    return "\n".join(lines)


def normalize_trigger(trigger_time: str, date_label: str) -> str:
    t = trigger_time or ""
    if " " not in t:
        t = f"{date_label} 18:00:00"
    # replace underscores dashes
    t = t.replace("_", " ").replace("T", " ")
    return t


async def generate_report_for_signal(signal: Dict, market: str, trigger_time: str) -> str:
    brief = signal_brief(signal)
    financial_raw = await fetch_financial_company(market, signal.get("symbol_code", ""), trigger_time)
    if isinstance(financial_raw, (dict, list)):
        financial_text = json.dumps(financial_raw, ensure_ascii=False, indent=2)
    else:
        financial_text = str(financial_raw)

    bull_sys = (
        "你是一名严谨的多头研究员。仅基于给定证据构建看多论据，不要编造目标价或财务数字，"
        "辨别事实与观点，至少包含投资逻辑、增长催化、潜在优势。"
    )
    bull_prompt = f"材料:\n{brief}\n\n财务数据(可选):\n{financial_text}\n\n请输出【Bull论据】2-4条。"
    bull = await llm_chat(bull_prompt, bull_sys)

    bear_sys = (
        "你是一名严谨的空头/风险研究员。基于证据构建看空与风险论据，明确指出数据不足、"
        "估值风险、筹码风险、业务下行风险。不要故意唱空，要有事实依据。"
    )
    bear_prompt = f"材料:\n{brief}\n\n财务数据(可选):\n{financial_text}\n\nBull方论据:\n{bull}\n\n请输出【Bear/风险论据】2-4条。"
    bear = await llm_chat(bear_prompt, bear_sys)

    trader_sys = (
        "你是交易员。基于多空辩论给出具体交易建议。严格输出:\n"
        "Action: Buy / Hold / Sell\n"
        "Entry Price: ... 或 等待[具体条件]\n"
        "Stop Loss: ...\n"
        "Position Sizing: ...%\n"
        "Time Horizon: ...\n"
        "Reasoning: ..."
    )
    trader_prompt = f"候选:\n{brief}\n\nBull:\n{bull}\n\nBear:\n{bear}\n\n请给出交易计划。"
    trader = await llm_chat(trader_prompt, trader_sys)

    pm_sys = (
        "你是组合经理，综合多空辩论与交易员建议，给出最终投资决议。"
        "评级必须是五档之一: Buy / Overweight / Hold / Underweight / Sell。"
        "输出 Price Target（或观察位）、Time Horizon、Position 建议、执行摘要。"
    )
    pm_prompt = f"候选:\n{brief}\n\nBull:\n{bull}\n\nBear:\n{bear}\n\nTrader:\n{trader}\n\n请给出最终投资决议。"
    pm = await llm_chat(pm_prompt, pm_sys)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return "\n".join([
        f"# 投资决策报告：{signal.get('symbol_name')}（{signal.get('symbol_code')}）",
        "",
        f"报告生成: {now}  |  分析时点: {trigger_time}",
        "",
        "## 1. 候选信号快照",
        "",
        "```",
        brief,
        "```",
        "",
        "## 2. 基本面 / 财务（可用性受限）",
        "",
        financial_text,
        "",
        "## 3. 多头研究",
        "",
        bull,
        "",
        "## 4. 空头 / 风险研究",
        "",
        bear,
        "",
        "## 5. 交易员建议",
        "",
        trader,
        "",
        "## 6. 组合经理最终决议",
        "",
        pm,
        "",
        "---",
        "_本报告由当前系统候选信号 + LLM 投研层生成，不修改后端门控/选股规则。_",
        "",
    ])


def iter_candidates(root: Path) -> List[Dict]:
    rows = []
    seen = set()
    for date_dir in sorted([p for p in root.iterdir() if p.is_dir()]):
        trade_dir = date_dir / "results" / "trade_decisions"
        if not trade_dir.exists():
            continue
        for f in sorted(trade_dir.glob("*.json")):
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
            for list_name in ["buy_signals", "watchlist", "consensus_signals"]:
                for sig in (data.get(list_name) or []):
                    code = str(sig.get("symbol_code") or "")
                    name = str(sig.get("symbol_name") or "")
                    if not code and not name:
                        continue
                    key = (date_dir.name, code or name)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({"date": date_dir.name, "list": list_name, "signal": sig})
    return rows


async def main() -> None:
    parser = argparse.ArgumentParser(description="TradingAgents-style investment decision report generator.")
    parser.add_argument("--strategy", default="momentum")
    parser.add_argument("--workspace", default="agents_workspace_replays")
    parser.add_argument("--market", default="CN-Stock")
    parser.add_argument("--symbol-filter", default="", help="optional filter")
    parser.add_argument("--max", type=int, default=0)
    args = parser.parse_args()

    # Only for strategy folder
    root = Path(args.workspace).expanduser() / args.strategy
    if not root.exists():
        print(f"workspace not found: {root}")
        sys.exit(1)

    cands = iter_candidates(root)
    if args.symbol_filter:
        f = args.symbol_filter.upper()
        cands = [c for c in cands if f in str(c["signal"].get("symbol_code") or "").upper() or f in str(c["signal"].get("symbol_name") or "").upper()]
    if args.max > 0:
        cands = cands[: args.max]

    out_dir = PROJECT_ROOT / "agents_workspace_replays" / args.strategy / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating decision reports for {len(cands)} candidates")
    for c in cands:
        sig = c["signal"]
        trigger = normalize_trigger(sig.get("analysis_as_of_date") or sig.get("trigger_time"), c["date"])
        safe_symbol = (sig.get("symbol_code") or sig.get("symbol_name") or "unknown").replace("/", "_")
        out_file = out_dir / f"{c['date']}_{safe_symbol}_decision.md"
        print(f"  -> {out_file}")
        md = await generate_report_for_signal(sig, args.market, trigger)
        out_file.write_text(md, encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
