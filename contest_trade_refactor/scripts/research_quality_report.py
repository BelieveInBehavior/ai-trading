#!/usr/bin/env python3
"""Layered fundamental/technical sanity report for replay candidates.

This is an analytical tool only. It does NOT change backend gating or scoring.
It reads agents_workspace_replays/... and outputs a markdown report that breaks
candidates into:
  - strongly_buy: high technical + money/flow + consensus + quality + gate pass
  - watch:        system said buy OR quality is mixed; wait for better trigger
  - avoid:        clear red flags / missing legs

It only uses structured fields already produced by the pipeline, so it does not
invent valuation / consensus / overhang data that isn't present.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _f(value, precision: int = 1) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{precision}f}"
    except (TypeError, ValueError):
        return str(value)


def _pct(value) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _dedupe_votes(votes: List[Dict]) -> List[Dict]:
    seen = set()
    out = []
    for v in votes or []:
        key = v.get("agent_name") or v.get("agent_id") or str(v.get("agent_key"))
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def _evidence_text(signal: Dict) -> str:
    parts = []
    for e in (signal.get("evidence_list") or []):
        src = e.get("from_source") or "N/A"
        desc = e.get("description") or ""
        parts.append(f"[{src}] {desc}")
    return "\n".join(parts)


def _gate_failed(signal: Dict) -> List[str]:
    rep = signal.get("next_day_gate_report") or {}
    reasons = rep.get("failed_reasons") or []
    if not reasons:
        reasons = signal.get("gate_failed_reasons") or []
    return list(reasons)


def _is_passed(signal: Dict) -> bool:
    rep = signal.get("next_day_gate_report") or {}
    if rep.get("passed") is not None:
        return bool(rep.get("passed"))
    return str(signal.get("buy_decision") or "").lower() == "buy"


def analyze_one(signal: Dict, date: str, list_name: str) -> Dict:
    sc = signal.get("next_day_factor_scorecard") or {}
    tech = signal.get("technical_factor") or {}
    votes = _dedupe_votes(signal.get("agent_votes") or [])
    buy_votes = sum(1 for v in votes if str(v.get("vote") or "").lower() == "buy")
    watch_votes = sum(1 for v in votes if str(v.get("vote") or "").lower() == "watch")
    passed = _is_passed(signal)
    failed = _gate_failed(signal)

    # technical legs
    weekly = sc.get("weekly_trend_score")
    rs = sc.get("relative_strength_score")
    daily = sc.get("daily_entry_score")
    ma20 = sc.get("ma20_deviation_pct")
    prev_gain = sc.get("prev_day_gain_pct")
    rsi = tech.get("rsi")

    tech_good = bool(
        (weekly is not None and weekly >= 60)
        and (rs is not None and rs >= 55)
        and (daily is not None and daily >= 55)
        and (ma20 is None or abs(ma20) <= 8)
        and (prev_gain is None or prev_gain <= 8)
    )

    # money/flow
    flow = sc.get("capital_flow_score")
    regime_score = sc.get("market_regime_score")
    ev = _evidence_text(signal)
    strong_flow_hits = sum(
        1 for kw in ["主力净流入", "龙虎榜", "北向资金", "融资净买入", "机构净买入", "连续净流入", "净流入"]
        if kw in ev
    )
    flow_ok = bool((flow is not None and flow >= 55) or strong_flow_hits >= 2)
    flow_text = []
    if flow is not None:
        flow_text.append(f"flow={flow:.0f}")
    if strong_flow_hits:
        flow_text.append(f"text_money_hits={strong_flow_hits}")
    else:
        flow_text.append("text_money=weak")
    if regime_score is not None:
        flow_text.append(f"regime={regime_score:.0f}")

    # consensus
    consensus_ok = len(votes) >= 2 and buy_votes >= 2

    # quality
    quality = sc.get("data_quality_score")
    quality_ok = quality is not None and quality >= 60

    # risk / veto
    veto_rep = signal.get("risk_veto_report") or {}
    veto_ok = bool(veto_rep.get("passed"))

    # rating
    if passed and consensus_ok and quality_ok and flow_ok and tech_good:
        rating = "strongly_buy"
        action = "可买入（技术+资金+共识+数据+门控均到位）"
    elif passed:
        rating = "watch"
        action = "系统判买，但质量不足，建议观望或小仓验证"
    elif consensus_ok and flow_ok and tech_good and quality_ok:
        rating = "watch"
        action = "未过门控，但多维质量尚可，等更好买点"
    elif not tech_good:
        rating = "avoid"
        action = "技术位置不佳，拒绝追高"
    elif not flow_ok:
        rating = "avoid"
        action = "资金确认不足，不建议买入"
    elif buy_votes == 0:
        rating = "avoid"
        action = "无买入共识"
    else:
        rating = "watch"
        action = "观察，等待技术/资金/质量改善"

    reasons = [
        f"技术: weekly={_f(weekly)} rs={_f(rs)} daily={_f(daily)} ma20={_pct(ma20)} prev={_pct(prev_gain)}",
        f"资金: {'; '.join(flow_text)}",
        f"共识: {buy_votes}买/{watch_votes}观/{len(votes)}总",
        f"数据质量: {_f(quality)}",
        f"门控: passed={passed}{' 失败=' + ', '.join(failed) if failed else ''}",
    ]

    risk_notes = []
    if not veto_ok:
        risk_notes.append("风险否决未通过")
    if not quality_ok:
        risk_notes.append("数据质量分偏低")
    for t in (signal.get("limitations") or []):
        risk_notes.append(str(t)[:160])

    return {
        "date": date,
        "list": list_name,
        "symbol_code": signal.get("symbol_code") or "",
        "symbol_name": signal.get("symbol_name") or "",
        "buy_score": signal.get("buy_score"),
        "probability": signal.get("probability_value") or signal.get("probability"),
        "rating": rating,
        "action": action,
        "reasons": reasons,
        "risk_notes": risk_notes,
        "evidence": _evidence_text(signal),
    }


def load_replays(strategy: str, base_dirs: List[str]) -> List[Dict]:
    out = []
    for base in base_dirs:
        root = Path(base).expanduser()
        if not root.exists() or not root.is_dir():
            continue
        for date_dir in sorted([p for p in root.iterdir() if p.is_dir()]):
            trade_dir = date_dir / "results" / "trade_decisions"
            if not trade_dir.exists():
                continue
            for f in sorted(trade_dir.glob("*.json")):
                with open(f, encoding="utf-8") as fp:
                    r = json.load(fp)
                for list_name in ["buy_signals", "watchlist", "consensus_signals"]:
                    for s in (r.get(list_name) or []):
                        out.append(analyze_one(s, date_dir.name, list_name))
    # dedupe by (date, symbol, list)
    seen = set()
    deduped = []
    for row in out:
        key = (row["date"], row["symbol_code"], row["list"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def write_section(lines: List[str], rows: List[Dict], title: str):
    lines.append(f"## {title}")
    lines.append("")
    if not rows:
        lines.append("无。")
        lines.append("")
        return
    for r in rows:
        lines.append(f"### {r['symbol_name']}（{r['symbol_code']}）  [{r['rating']}]")
        lines.append("")
        lines.append(f"- 日期: {r['date']} | 类型: {r['list']}")
        lines.append(f"- 系统评分: {_f(r['buy_score'])} | 概率: {_f(r['probability'], 4)}")
        lines.append(f"- 建议: {r['action']}")
        lines.append("- 理由:")
        for reason in r["reasons"]:
            lines.append(f"  - {reason}")
        if r["risk_notes"]:
            lines.append("- 风险:")
            for note in r["risk_notes"]:
                lines.append(f"  - {note}")
        lines.append("- 证据摘录:")
        for line in r["evidence"].splitlines()[:8]:
            lines.append(f"  > {line[:220]}")
        lines.append("")


def render_md(rows: List[Dict]) -> str:
    lines = []
    lines.append("# 候选信号投研级分层体检")
    lines.append("")
    lines.append(f"报告生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("> 说明：本报告不改变后端门控/选股逻辑，仅基于 replay 结构化字段做分层分析。")
    lines.append("> 如缺少估值/机构一致预期/套牢区/融资拥挤度等深度字段，标注 N/A，不编造。")
    lines.append("")

    by_rating = {}
    for r in rows:
        by_rating.setdefault(r["rating"], []).append(r)

    lines.append("## 总览")
    lines.append("")
    lines.append("| 评级 | 数量 |")
    lines.append("|---|---|")
    for rating in ["strongly_buy", "watch", "avoid"]:
        lines.append(f"| {rating} | {len(by_rating.get(rating, []))} |")
    lines.append("")

    write_section(lines, by_rating.get("strongly_buy", []), "强烈建议买")
    write_section(lines, by_rating.get("watch", []), "观察（等更好买点）")
    write_section(lines, by_rating.get("avoid", []), "不推荐 / 风险")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Layered research quality report for replay candidates.")
    parser.add_argument("--strategy", default="momentum")
    parser.add_argument("--workspaces", nargs="+", default=["agents_workspace_replays"])
    args = parser.parse_args()
    rows = load_replays(args.strategy, args.workspaces)
    md = render_md(rows)
    out_dir = PROJECT_ROOT / "agents_workspace_replays" / args.strategy / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"research_quality_{args.strategy}.md"
    out_file.write_text(md, encoding="utf-8")
    print(f"Report written: {out_file}")
    print(md[:4000])
