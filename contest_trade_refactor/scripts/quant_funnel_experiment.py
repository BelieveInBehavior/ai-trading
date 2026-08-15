#!/usr/bin/env python3
"""Read-only experiment: compare old hard-filter universe vs new V2 scored universe.

Runs the V2 QuantitativeUniverseScreener over the full market (top_k=large so
every passed name is ranked), then reports:
  - how many names survive the V2 hard-survival layer (vs the old 64)
  - where the old 64 land in the new score ranking
  - how many Top-200 names are MA20>6/8/15%, daily gain>5/8%, Stage1/Stage2/
    other, extension risk < -5 / < -8

This is an experiment only: it does not change production parameters.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from agents.quantitative_universe_screener import (
    QuantitativeScreenerConfig,
    QuantitativeUniverseScreener,
)

OLD_DECISION_PATH = "agents_workspace/results/trade_decisions/2026-08-13_20-30-00.json"
OUTPUT_DIR = Path("agents_workspace_replays/momentum/reports")


def _safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _stage_level(stage: str):
    s = str(stage or "").replace(" ", "").replace("_", "").lower()
    if "stage4" in s:
        return 4
    if "stage3" in s:
        return 3
    if "stage2" in s:
        return 2
    if "stage1" in s:
        return 1
    return 0


def _load_old_64(trigger_time: str) -> list[str]:
    safe = trigger_time.replace(" ", "_").replace(":", "-")
    p = Path("agents_workspace/results/trade_decisions") / f"{safe}.json"
    if not p.exists():
        p = Path(OLD_DECISION_PATH)
    if not p.exists():
        print(f"[warn] old decision file not found: {p}")
        return []
    d = json.load(open(p, encoding="utf-8"))
    return [
        str(c.get("symbol_code") or "")
        for c in (d.get("quantitative_candidates") or [])
        if c.get("symbol_code")
    ]


def _tf(candidate: dict) -> dict:
    return candidate.get("technical_factor") or {}


def _eval(candidate: dict) -> dict:
    ev = candidate.get("quantitative_screen") or candidate.get("screen_eval") or {}
    if isinstance(ev, dict) and "score_breakdown" in ev:
        return ev
    return {}


def _report(candidates: list, old_64: list, screen: dict, trigger_time: str) -> dict:
    top200 = candidates[:200]
    top200_codes = {str(c.get("symbol_code") or "") for c in top200}

    rank_map = {str(c.get("symbol_code") or ""): i for i, c in enumerate(candidates)}
    old_ranks: list[int] = []
    old_in_v2_passed = 0
    for code in old_64:
        if code in rank_map:
            old_ranks.append(rank_map[code] + 1)
            old_in_v2_passed += 1
    old_missing_from_v2_passed = len(old_64) - old_in_v2_passed

    old_64_set = set(old_64)
    top200_include_old64 = sorted(top200_codes.intersection(old_64_set))

    ma20_gt6, ma20_gt8, ma20_gt15 = 0, 0, 0
    chg_gt5, chg_gt8 = 0, 0
    stage1, stage2, stage_other = 0, 0, 0
    ext_neg_below5, ext_neg_beyond8 = 0, 0
    new_names_in_top200: list[dict] = []

    for c in top200:
        tf = _tf(c)
        ev = _eval(c)
        sb = ev.get("score_breakdown") or {}
        ma20 = _safe_float(tf.get("ma20_deviation_pct"))
        chg = _safe_float(tf.get("change_pct"))
        stage = str(tf.get("weinstein_stage") or "")
        ext = _safe_float(sb.get("extension"))

        if ma20 is not None:
            if ma20 > 6:
                ma20_gt6 += 1
            if ma20 > 8:
                ma20_gt8 += 1
            if ma20 > 15:
                ma20_gt15 += 1
        if chg is not None:
            if chg > 5:
                chg_gt5 += 1
            if chg > 8:
                chg_gt8 += 1

        lvl = _stage_level(stage)
        if lvl == 1:
            stage1 += 1
        elif lvl == 2:
            stage2 += 1
        else:
            stage_other += 1

        if ext is not None and ext < -5:
            ext_neg_below5 += 1
        if ext is not None and ext < -8:
            ext_neg_beyond8 += 1

        code = str(c.get("symbol_code") or "")
        if code not in old_64_set:
            new_names_in_top200.append({
                "symbol": code,
                "name": c.get("symbol_name"),
                "score": c.get("quantitative_score"),
                "ma20_dev_pct": tf.get("ma20_deviation_pct"),
                "change_pct": tf.get("change_pct"),
                "stage": tf.get("weinstein_stage"),
                "final_score": sb.get("final"),
                "extension": sb.get("extension"),
            })

    top20 = []
    for i, c in enumerate(candidates[:20], start=1):
        tf = _tf(c)
        ev = _eval(c)
        sb = ev.get("score_breakdown") or {}
        top20.append({
            "rank": i,
            "symbol": c.get("symbol_code"),
            "name": c.get("symbol_name"),
            "quantitative_score": c.get("quantitative_score"),
            "final_score": sb.get("final"),
            "weekly_score": tf.get("weekly_trend_score"),
            "relative_score": tf.get("relative_strength_score"),
            "daily_entry_score": tf.get("daily_entry_score"),
            "ma20_dev_pct": tf.get("ma20_deviation_pct"),
            "change_pct": tf.get("change_pct"),
            "stage": tf.get("weinstein_stage"),
            "extension": sb.get("extension"),
            "long_score": ev.get("long_score"),
            "short_score": ev.get("short_score"),
            "extension_risk": ev.get("extension_risk"),
            "pool": ev.get("pool"),
        })

    # Total pool stats over ALL passed candidates
    from collections import Counter
    pool_stats_passed = Counter()
    best_opportunity_list = []
    core_buy_list = []
    for c in candidates:
        ev = _eval(c)
        pool = ev.get("pool") or "watch"
        pool_stats_passed[pool] += 1
        if pool == "core_buy":
            tfx = _tf(c)
            sbx = ev.get("score_breakdown") or {}
            long_v = ev.get("long_score") or 0
            short_v = ev.get("short_score") or 0
            risk_v = ev.get("extension_risk") or 0
            core_buy_list.append({
                "symbol": c.get("symbol_code"),
                "name": c.get("symbol_name"),
                "long_score": long_v,
                "short_score": short_v,
                "extension_risk": risk_v,
                "blend_score": round(long_v + short_v * 0.5 - risk_v * 0.2, 2),
                "final_score": sbx.get("final"),
                "ma20_dev_pct": tfx.get("ma20_deviation_pct"),
                "change_pct": tfx.get("change_pct"),
                "stage": tfx.get("weinstein_stage"),
            })
        if pool == "best_opportunity":
            tfx = _tf(c)
            sbx = ev.get("score_breakdown") or {}
            long_v = ev.get("long_score") or 0
            short_v = ev.get("short_score") or 0
            risk_v = ev.get("extension_risk") or 0
            best_opportunity_list.append({
                "symbol": c.get("symbol_code"),
                "name": c.get("symbol_name"),
                "long_score": long_v,
                "short_score": short_v,
                "extension_risk": risk_v,
                "blend_score": round(long_v + short_v * 0.5 - risk_v * 0.2, 2),
                "final_score": sbx.get("final"),
                "ma20_dev_pct": tfx.get("ma20_deviation_pct"),
                "change_pct": tfx.get("change_pct"),
                "stage": tfx.get("weinstein_stage"),
            })
    best_opportunity_list.sort(key=lambda x: -(x.get("blend_score") or 0))
    best_opportunity_list = best_opportunity_list[:100]

    old_ranks_sorted = sorted(old_ranks)
    return {
        "trigger_time": trigger_time,
        "universe_count": screen.get("universe_count"),
        "scanned_count": screen.get("scanned_count"),
        "v2_passed_count": screen.get("passed_count"),
        "screen_funnel": screen.get("screen_funnel"),
        "old64_count": len(old_64),
        "old64_in_v2_passed": old_in_v2_passed,
        "old64_missing_in_v2_passed": old_missing_from_v2_passed,
        "top200_count": len(top200),
        "top200_include_old64": top200_include_old64,
        "top200_include_old64_count": len(top200_include_old64),
        "old_rank_min": old_ranks_sorted[0] if old_ranks_sorted else None,
        "old_rank_median": old_ranks_sorted[len(old_ranks_sorted) // 2] if old_ranks_sorted else None,
        "old_rank_max": old_ranks_sorted[-1] if old_ranks_sorted else None,
        "top200_ma20_gt6": ma20_gt6,
        "top200_ma20_gt8": ma20_gt8,
        "top200_ma20_gt15": ma20_gt15,
        "top200_change_gt5": chg_gt5,
        "top200_change_gt8": chg_gt8,
        "top200_stage1": stage1,
        "top200_stage2": stage2,
        "top200_stage_other": stage_other,
        "top200_extension_neg_below5": ext_neg_below5,
        "top200_extension_neg_beyond8": ext_neg_beyond8,
        "top200_new_names_count": len(new_names_in_top200),
        "top20": top20,
        "new_names_in_top200": new_names_in_top200,
        "pool_stats_passed": dict(pool_stats_passed),
        "core_buy_list": core_buy_list,
        "best_opportunity_list": best_opportunity_list,
    }


def _save_report(report: dict, trigger_time: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = trigger_time.replace(" ", "_").replace(":", "-")
    out = OUTPUT_DIR / f"quant_funnel_experiment_{safe}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


async def main() -> int:
    trigger_time = "2026-08-13 20:30:00"
    if len(sys.argv) > 1:
        raw_parts = sys.argv[1:]
        # allow unquoted date+time on the command line
        if len(raw_parts) >= 2 and sys.argv[2][:2].isdigit():
            raw_parts = [" ".join(raw_parts[:2])]
        raw = raw_parts[0].replace("T", " ").replace("_", " ")
        trigger_time = raw

    print(f"[experiment] trigger_time={trigger_time}")

    # V2 hard-survival only; top_k large so we rank every passed name instead of truncating.
    config = QuantitativeScreenerConfig(
        enabled=True,
        max_symbols=0,
        max_concurrency=12,
        top_k=100000,
        history_days=260,
        benchmark_symbol="sh000300",
        # generous ceilings so we can observe how far the old filter was misleading.
        hard_max_ma20_deviation_pct=60.0,
        hard_max_prev_day_gain_pct=20.0,
        hard_min_weekly_score=30.0,
        hard_min_relative_score=25.0,
        hard_min_relative_20d_pct=-50.0,
        require_data_quality=True,
        require_weinstein_stage2=False,
    )
    screener = QuantitativeUniverseScreener(config)
    screen = await screener.screen(trigger_time)
    print(
        f"[experiment] status={screen.get('status')} "
        f"universe={screen.get('universe_count')} "
        f"scanned={screen.get('scanned_count')} "
        f"passed={screen.get('passed_count')}"
    )
    if screen.get("status") != "ok":
        print(screen.get("context_string"))
        print(json.dumps(screen.get("errors", []), ensure_ascii=False, indent=2))
        return 1

    candidates = screen.get("candidates") or []
    old_64 = _load_old_64(trigger_time)
    print(f"[experiment] old64={len(old_64)} v2_passed={len(candidates)} top200={len(candidates[:200])}")

    report = _report(candidates, old_64, screen, trigger_time)
    out = _save_report(report, trigger_time)
    print(f"[experiment] wrote {out}")

    summary_keys = [
        "universe_count", "scanned_count", "v2_passed_count",
        "old64_count", "old64_in_v2_passed", "old64_missing_in_v2_passed",
        "top200_count", "top200_include_old64_count",
        "old_rank_min", "old_rank_median", "old_rank_max",
        "top200_ma20_gt6", "top200_ma20_gt8", "top200_ma20_gt15",
        "top200_change_gt5", "top200_change_gt8",
        "top200_stage1", "top200_stage2", "top200_stage_other",
        "top200_extension_neg_below5", "top200_extension_neg_beyond8",
        "top200_new_names_count",
    ]
    print(json.dumps({k: report[k] for k in summary_keys}, ensure_ascii=False, indent=2))
    print("\nTop 20:")
    print(json.dumps(report["top20"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
