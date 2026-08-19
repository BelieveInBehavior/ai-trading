#!/usr/bin/env python3
"""
Closed-loop signal performance evaluator.

Goal: turn agent-generated buy/watch/rejected signals into measurable forward
returns so thresholds can be validated.

For each historical trade_decision JSON:
  - extract every signal (buy_passed, watch, research_rejected, consensus)
  - fetch forward prices (qfq) after trigger date
  - compute next-trading-day-open entry and T+1/T+3/T+5 forward returns,
    max gain and max loss
  - write normalized CSV + JSONL + markdown summary + threshold candidate IC

Usage:
  .venv/bin/python scripts/backtest_signal_closed_loop.py
  .venv/bin/python scripts/backtest_signal_closed_loop.py --glob "..." --horizons 1,3,5
"""

from __future__ import annotations

import argparse
import asyncio
import glob as pyglob
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.market_manager import GLOBAL_MARKET_MANAGER
from utils.cn_price_provider import get_stock_zh_a_hist


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_symbol(symbol: Any) -> str:
    text = str(symbol or "").strip().partition(".")[0]
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 6:
        return digits[-6:]
    return text.upper()


def compact_ts(value: Any) -> Optional[str]:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) >= 8 and digits[:4].isdigit():
        return digits[:8]
    return None


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        text = str(value).strip().replace("%", "")
        if not text:
            return default
        return float(text)
    except Exception:
        return default


def get_next_trade_dates(trigger_compact: str, count: int) -> List[str]:
    trade_dates = GLOBAL_MARKET_MANAGER.get_trade_date(market_name="CN-Stock")
    trade_dates = [str(td).replace("-", "").replace("/", "") for td in trade_dates]
    out: List[str] = []
    for td in trade_dates:
        if td > trigger_compact:
            out.append(td)
            if len(out) >= count:
                break
    return out


def row_map_from_frame(df: Optional[pd.DataFrame]) -> Dict[str, Dict[str, Any]]:
    if df is None or df.empty:
        return {}
    frame = df.copy()
    date_col = "日期" if "日期" in frame.columns else ("date" if "date" in frame.columns else None)
    if not date_col:
        return {}
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce").dt.strftime("%Y%m%d")
    frame = frame.dropna(subset=[date_col]).drop_duplicates(date_col, keep="last").sort_values(date_col)
    return {str(r[date_col]): r.to_dict() for _, r in frame.iterrows()}


def compute_forward_returns(
    row_map: Dict[str, Dict[str, Any]],
    entry_date: str,
    horizon_dates: List[str],
) -> Optional[Dict[str, Any]]:
    sample = next(iter(row_map.values()), {}) or {}
    open_col = "开盘" if "开盘" in sample else "open"
    close_col = "收盘" if "收盘" in sample else "close"
    high_col = "最高" if "最高" in sample else "high"
    low_col = "最低" if "最低" in sample else "low"

    def _val(d, col):
        r = row_map.get(d)
        if not r:
            return None
        try:
            return float(r.get(col))
        except Exception:
            return None

    entry_open = _val(entry_date, open_col)
    if not entry_open or entry_open <= 0:
        return None

    closes = {d: _val(d, close_col) for d in horizon_dates}
    # Only require the closes we actually need. Missing future dates are left as None
    # so reports can still include signals that are still maturing.
    available = [v for v in closes.values() if v is not None and v > 0]
    if not available or not closes.get(horizon_dates[0]):
        return None

    max_high = entry_open
    min_low = entry_open
    for d in horizon_dates:
        r = row_map.get(d)
        if not r:
            continue
        try:
            hi = float(r.get(high_col) or entry_open)
            lo = float(r.get(low_col) or entry_open)
            max_high = max(max_high, hi)
            min_low = min(min_low, lo)
        except Exception:
            pass

    def pct(a, b):
        return round((b - a) / a * 100.0, 4) if a else 0.0

    return {
        "entry_date": entry_date,
        "entry_price": round(entry_open, 4),
        "exit_t1_date": horizon_dates[0],
        "exit_t3_date": horizon_dates[2],
        "exit_t5_date": horizon_dates[4],
        "t1_close": round(closes[horizon_dates[0]], 4) if closes.get(horizon_dates[0]) else None,
        "t3_close": round(closes[horizon_dates[2]], 4) if len(horizon_dates) > 2 and closes.get(horizon_dates[2]) else None,
        "t5_close": round(closes[horizon_dates[4]], 4) if len(horizon_dates) > 4 and closes.get(horizon_dates[4]) else None,
        "t1_return_pct": pct_cls(entry_open, closes[horizon_dates[0]]) if horizon_dates[0] in closes and closes[horizon_dates[0]] else None,
        "t3_return_pct": pct_cls(entry_open, closes[horizon_dates[2]]) if len(horizon_dates) > 2 and horizon_dates[2] in closes and closes[horizon_dates[2]] else None,
        "t5_return_pct": pct_cls(entry_open, closes[horizon_dates[4]]) if len(horizon_dates) > 4 and horizon_dates[4] in closes and closes[horizon_dates[4]] else None,
        "max_gain_pct": pct_cls(entry_open, max_high),
        "max_loss_pct": pct_cls(entry_open, min_low),
        "max_drawdown_pct": pct_cls(entry_open, min_low),
    }


def pct_cls(a: float, b: float) -> float:
    return round((b - a) / a * 100.0, 4) if a else 0.0


# ---------------------------------------------------------------------------
# Signal loading
# ---------------------------------------------------------------------------

def load_all_signals(glob_pattern: str) -> List[Dict[str, Any]]:
    files = sorted(Path(p) for p in pyglob.glob(glob_pattern))
    if not files:
        print(f"[warn] no files match {glob_pattern!r}")
        return []
    all_sigs: List[Dict[str, Any]] = []
    for path in files:
        sigs = extract_signals_from_file(path)
        if sigs:
            all_sigs.extend(sigs)
    # One economic prediction per trigger+symbol.  The previous implementation
    # counted watch/research/consensus copies as independent observations,
    # inflating sample size and factor statistics.
    priority = {"buy_passed": 0, "watch": 1, "consensus": 2, "research": 3}
    grouped: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in all_sigs:
        key = (
            r.get("__trigger_compact"),
            str(r.get("symbol_code") or r.get("symbol_name") or ""),
        )
        grouped.setdefault(key, []).append(r)
    uniq = []
    for records in grouped.values():
        records.sort(key=lambda item: priority.get(str(item.get("__group")), 99))
        chosen = dict(records[0])
        chosen["source_groups"] = sorted({str(item.get("__group")) for item in records})
        uniq.append(chosen)
    print(f"[load] {len(uniq)} unique signals from {len(files)} files")
    return uniq


def extract_signals_from_file(path: Path) -> List[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"[skip] {path.name}: {exc}")
        return []
    if not isinstance(payload, dict):
        return []

    trigger_ts = str(payload.get("trigger_time") or "")
    trigger_compact = compact_ts(trigger_ts)
    if not trigger_compact:
        return []
    logic_version = payload.get("logic_version") or {}
    strategy_info = payload.get("strategy") or {}
    logic_strategy = logic_version.get("strategy_id") if isinstance(logic_version, dict) else ""
    payload_strategy = strategy_info.get("id") if isinstance(strategy_info, dict) else ""
    strategy = str(logic_strategy or payload_strategy or "")

    groups = [
        ("buy_passed", payload.get("buy_signals") or payload.get("best_signals") or []),
        ("watch", payload.get("watchlist") or []),
        ("research", payload.get("research_signals") or []),
        ("consensus", payload.get("consensus_signals") or []),
    ]
    records: List[Dict[str, Any]] = []
    for group, sig_list in groups:
        for sig in sig_list:
            if not isinstance(sig, dict):
                continue
            key = str(sig.get("symbol_code") or sig.get("symbol_name") or "").strip()
            if not key:
                continue
            rec = dict(sig)
            rec["__trigger_ts"] = trigger_ts
            rec["__trigger_compact"] = trigger_compact
            rec["__group"] = group
            rec["source_file"] = path.name
            rec["source_path"] = str(path)
            rec["strategy"] = strategy
            rec["trigger_time"] = trigger_ts
            rec["symbol_name_raw"] = sig.get("symbol_name")
            records.append(rec)
    return records


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    output_dir: Path = PROJECT_ROOT / "agents_workspace" / "backtest_results"
    horizons: Sequence[int] = (1, 3, 5)
    parallel: int = 4
    min_samples: int = 10


def trade_plan_of(rec: Dict[str, Any]) -> Dict[str, Any]:
    plan = rec.get("trade_plan")
    if isinstance(plan, dict):
        return plan
    # Some older rows stored it nested in scorecard.
    sc = rec.get("scorecard")
    if isinstance(sc, dict):
        plan = sc.get("trade_plan")
        if isinstance(plan, dict):
            return plan
    return {}


def _populate_trade_plan_cols(out: Dict[str, Any], rec: Dict[str, Any]) -> None:
    pl = trade_plan_of(rec)
    if not pl:
        out["trade_plan_status"] = pl.get("status", "missing")
        return
    inds = pl.get("indicators") or {}
    lv = pl.get("levels") or {}
    p = pl.get("plan") or {}
    out["trade_plan_status"] = pl.get("status", "ok")
    out["trade_plan_rsi"] = inds.get("rsi")
    out["trade_plan_vwap20"] = inds.get("vwap_20")
    out["trade_plan_ema8"] = inds.get("ema8")
    out["trade_plan_ema13"] = inds.get("ema13")
    out["trade_plan_ema21"] = inds.get("ema21")
    out["trade_plan_volume_ratio"] = inds.get("volume_ratio")
    out["trade_plan_amount_ratio"] = inds.get("amount_ratio")
    out["trade_plan_volume_ma5_ma20_ratio"] = inds.get("volume_ma5_ma20_ratio")
    out["trade_plan_support_1"] = lv.get("support_1")
    out["trade_plan_support_2"] = lv.get("support_2")
    out["trade_plan_resistance_1"] = lv.get("resistance_1")
    out["trade_plan_resistance_2"] = lv.get("resistance_2")
    out["trade_plan_entry_zone_low"] = p.get("entry_zone_low")
    out["trade_plan_entry_zone_high"] = p.get("entry_zone_high")
    out["trade_plan_stop_loss"] = p.get("stop_loss")
    out["trade_plan_stop_loss_pct"] = p.get("stop_loss_pct")
    out["trade_plan_take_profit_1"] = p.get("take_profit_1")
    out["trade_plan_take_profit_2"] = p.get("take_profit_2")
    out["trade_plan_rr_1"] = p.get("rr_1")
    out["trade_plan_rr_ok"] = p.get("rr_ok")
    out["trade_plan_pass"] = rec.get("trade_plan_pass", pl.get("trade_plan_pass", False))
    reasons = rec.get("trade_plan_reject_reasons") or pl.get("trade_plan_reject_reasons")
    out["trade_plan_reject_reasons"] = reasons


def scorecard_of(rec: Dict[str, Any]) -> Dict[str, Any]:
    sc = rec.get("next_day_factor_scorecard")
    if not isinstance(sc, dict):
        sc = rec.get("scorecard")
    if not isinstance(sc, dict):
        sc = {}
    return sc


def evaluate_one(rec: Dict[str, Any], settings: Settings) -> Optional[Dict[str, Any]]:
    trigger_compact = rec.get("__trigger_compact") or compact_ts(rec.get("trigger_time"))
    symbol_raw = rec.get("symbol_code") or rec.get("symbol_name") or ""
    symbol = normalize_symbol(symbol_raw)
    if not symbol or not trigger_compact:
        return None

    nxt = get_next_trade_dates(trigger_compact, settings.horizons[-1])
    if len(nxt) < settings.horizons[-1]:
        rec["_eval_error"] = "not_enough_future"
        return None
    entry_date = nxt[0]
    # T1 is the close of the entry session (next trading-day open -> close),
    # T3/T5 are the third/fifth session closes from that same entry.
    horizon_dates = nxt
    start = trigger_compact
    end = horizon_dates[-1]

    try:
        df = get_stock_zh_a_hist(symbol, start_date=start, end_date=end, adjust="qfq", verbose=False)
    except Exception as exc:
        rec["_eval_error"] = f"fetch_error:{exc}"
        return None
    if df is None or df.empty:
        rec["_eval_error"] = "empty_price"
        return None
    row_map = row_map_from_frame(df)
    if entry_date not in row_map:
        rec["_eval_error"] = f"missing_entry_{entry_date}"
        return None
    fwd = compute_forward_returns(row_map, entry_date, horizon_dates)
    if not fwd:
        out = dict(rec)
        out["symbol_code"] = normalize_symbol(symbol_raw)
        out["symbol_raw"] = rec.get("symbol_code")
        out["evaluated"] = False
        out["_eval_error"] = "pending_not_mature"
        out["entry_date"] = entry_date
        out["entry_price"] = None
        out["signal_group"] = out.get("__group") or ""
        out["buy_decision"] = str(rec.get("buy_decision") or "").strip().lower()
        return out

    out = dict(rec)
    out["symbol_code"] = normalize_symbol(symbol_raw)
    out["symbol_raw"] = rec.get("symbol_code")
    out["evaluated"] = True
    out.update(fwd)
    _populate_trade_plan_cols(out, rec)

    # For this closed-loop framework we define "hit" as T1 return > 0 for all
    # buy/watch candidate groups. Later we can distinguish by action.
    out["hit"] = out.get("t1_return_pct", 0) > 0

    sc = scorecard_of(rec)
    for k, v in sc.items():
        if k not in out:
            out[k] = v

    # Ensure holding days/rule are present (may come direct on rec)
    if "recommended_holding_days" not in out or "holding_rule" not in out:
        try:
            from agents.signal_tier_classifier import _holding_days, _holding_rule
            synthetic = {"next_day_factor_scorecard": sc}
            if "recommended_holding_days" not in out:
                out["recommended_holding_days"] = _holding_days(synthetic)
            if "holding_rule" not in out:
                out["holding_rule"] = _holding_rule(synthetic)
        except Exception:
            out.setdefault("recommended_holding_days", 2)
            out.setdefault("holding_rule", "T+1_2_fast_exit")

    for col in [
        "weekly_trend_score", "relative_strength_score", "daily_entry_score",
        "catalyst_score", "capital_flow_score", "technical_score",
        "market_regime_score", "tradeability_score", "risk_reward_score",
        "data_quality_score", "ma20_deviation_pct", "prev_day_gain_pct",
        "consensus_score", "future_evidence_count", "flow_data_available",
        "primary_catalyst", "signal_tier", "tier_confidence",
        "recommended_position_size_pct", "buy_score", "probability_value",
        "probability", "expected_return_t1_pct", "expected_net_edge_pct",
        "expected_upside_pct", "expected_downside_pct", "payoff_ratio",
        "forward_opportunity_score", "fundamental_score", "valuation_score",
        "atr_pct", "daily_volatility_20d_pct",
    ]:
        if col not in out:
            out[col] = sc.get(col) if col in sc else out.get(col)

    out["signal_group"] = out.get("__group") or ""
    out["buy_decision"] = str(rec.get("buy_decision") or "").strip().lower()
    return out


async def evaluate_all(records: List[Dict[str, Any]], settings: Settings) -> List[Dict[str, Any]]:
    sem = asyncio.Semaphore(settings.parallel)

    async def worker(rec):
        async with sem:
            return await asyncio.to_thread(evaluate_one, rec, settings)

    results = await asyncio.gather(*[worker(r) for r in records])
    ok = [r for r in results if r]
    print(f"[eval] evaluated {len(ok)}/{len(records)}")
    return ok


def classify_pending(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return records marked pending (not enough future data yet) for a pending CSV.

    We re-run evaluate_one but keep non-None with _eval_error. Since evaluate_one returns None
    on cannot_compute_forward, we do a lighter check: whether entry date exists but no future
    close yet. For simplicity, re-invoke and pick those where entry was found but no fwd computed.
    """
    # No-op for now; kept for explicit pipeline.
    return records


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

CSV_COLS = [
    "trigger_time", "trigger_date", "source_file", "symbol_code", "symbol_name_raw",
    "signal_group", "buy_decision", "signal_tier", "buy_score", "probability_value",
    "expected_return_t1_pct", "expected_net_edge_pct", "expected_upside_pct",
    "expected_downside_pct", "payoff_ratio", "entry_date", "entry_price",
    "t1_close", "t3_close", "t5_close",
    "t1_return_pct", "t3_return_pct", "t5_return_pct",
    "max_gain_pct", "max_loss_pct", "max_drawdown_pct",
    "weekly_trend_score", "relative_strength_score", "daily_entry_score",
    "catalyst_score", "capital_flow_score", "technical_score",
    "market_regime_score", "tradeability_score", "risk_reward_score",
    "data_quality_score", "ma20_deviation_pct", "prev_day_gain_pct",
    "flow_data_available", "primary_catalyst", "consensus_score",
    "future_evidence_count", "tier_confidence", "recommended_position_size_pct",
    "recommended_holding_days", "holding_rule",
    "entry_quality_score", "crowding_score", "entry_quality_delta",
    "forward_opportunity_score", "fundamental_score", "valuation_score",
    "atr_pct", "daily_volatility_20d_pct",
    "trade_plan_status", "trade_plan_rsi", "trade_plan_vwap20",
    "trade_plan_ema8", "trade_plan_ema13", "trade_plan_ema21",
    "trade_plan_volume_ratio", "trade_plan_amount_ratio", "trade_plan_volume_ma5_ma20_ratio",
    "trade_plan_support_1", "trade_plan_support_2",
    "trade_plan_resistance_1", "trade_plan_resistance_2",
    "trade_plan_entry_zone_low", "trade_plan_entry_zone_high",
    "trade_plan_stop_loss", "trade_plan_stop_loss_pct",
    "trade_plan_take_profit_1", "trade_plan_take_profit_2",
    "trade_plan_rr_1", "trade_plan_rr_ok",
    "trade_plan_pass", "trade_plan_reject_reasons",
    "strategy", "_eval_error",
]


def to_rows(evaluated: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for r in evaluated:
        row = {}
        for col in CSV_COLS:
            row[col] = r.get(col)
        row["trigger_date"] = compact_ts(r.get("__trigger_compact") or r.get("trigger_time"))
        if "symbol_name_raw" not in r and "symbol_name" in r:
            row["symbol_name_raw"] = r.get("symbol_name")
        rows.append(row)
    return rows


def write_summary(evaluated: List[Dict[str, Any]], settings: Settings) -> None:
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(to_rows(evaluated))
    pending_count = len([r for r in (globals().get("_last_pending") or []) if r])
    lines = [
        "# Signal Closed-Loop Performance",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Evaluated signals: {len(evaluated)}",
        f"Pending signals (not enough future close yet): {pending_count}",
        "",
    ]

    horizons = list(settings.horizons) or [1, 3, 5]
    lines.append("## Overall")
    lines.append("| Horizon | N | WinRate | Avg | Median | MaxGainAvg | MaxLossAvg |")
    lines.append("|---|---|---|---|---|---|---|")
    for h in horizons:
        col = f"t{h}_return_pct"
        if col not in df.columns:
            continue
        vals = df[col].dropna()
        if len(vals) == 0:
            continue
        lines.append(
            f"| {h} | {len(vals)} | {((vals > 0).mean()*100):.1f}% | {vals.mean():.2f}% | "
            f"{vals.median():.2f}% | {safe_float(df['max_gain_pct'].mean()):.2f}% | "
            f"{safe_float(df['max_drawdown_pct'].mean()):.2f}% |"
        )

    lines.append("")
    lines.append("## By signal group (T1)")
    lines.append("| Group | N | WinRate | AvgT1 | AvgT3 | AvgT5 | AvgMaxLoss |")
    lines.append("|---|---|---|---|---|---|---|")
    for grp in ["buy_passed", "watch", "research", "consensus"]:
        sub = df[df["signal_group"] == grp]
        if sub.empty:
            continue
        t1 = sub["t1_return_pct"].dropna()
        lines.append(
            f"| {grp} | {len(sub)} | {((t1 > 0).mean() * 100):.1f}% | "
            f"{t1.mean():.2f}% | {safe_float(sub['t3_return_pct'].mean()):.2f}% | "
            f"{safe_float(sub['t5_return_pct'].mean()):.2f}% | {safe_float(sub['max_drawdown_pct'].mean()):.2f}% |"
        )

    lines.append("")
    lines.append("## By tier")
    lines.append("| Tier | N | WinRate | AvgT1 | AvgT3 | AvgT5 | AvgMaxDD |")
    lines.append("|---|---|---|---|---|---|---|")
    if "signal_tier" in df.columns:
        for tier, sub in df.groupby("signal_tier"):
            if tier == "" or sub.empty:
                continue
            t1 = sub["t1_return_pct"].dropna()
            lines.append(
                f"| {tier}| {len(sub)} | {((t1 > 0).mean()*100):.1f}% | "
                f"{t1.mean():.2f}% | {safe_float(sub['t3_return_pct'].mean()):.2f}% | "
                f"{safe_float(sub['t5_return_pct'].mean()):.2f}% | {safe_float(sub['max_drawdown_pct'].mean()):.2f}% |"
            )

    lines.append("")
    lines.append("## Top / Bottom T5")
    lines.append("| Trigger | Symbol | Group | T1 | T3 | T5 |")
    lines.append("|---|---|---|---|---|---|")
    if "t5_return_pct" in df.columns and len(df):
        df_t5 = df.copy()
        df_t5["t5_return_pct"] = pd.to_numeric(df_t5["t5_return_pct"], errors="coerce")
        df_t5 = df_t5.dropna(subset=["t5_return_pct"])
        tb = pd.concat([df_t5.nlargest(10, "t5_return_pct"), df_t5.nsmallest(10, "t5_return_pct")])
        for _, r in tb.iterrows():
            lines.append(
                f"| {r.get('trigger_time','')} | {r.get('symbol_code','')} | {r.get('signal_group','')} | "
                f"{safe_float(r.get('t1_return_pct')):.2f} | {safe_float(r.get('t3_return_pct')):.2f} | "
                f"{safe_float(r.get('t5_return_pct')):.2f} |"
            )

    path = output_dir / "signal_closed_loop_summary.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[report] {path}")


def write_ic_candidates(evaluated: List[Dict[str, Any]], settings: Settings) -> None:
    output_dir = Path(settings.output_dir)
    df = pd.DataFrame(to_rows(evaluated))
    if df.empty or "t1_return_pct" not in df.columns:
        return
    candidate_cols = [
        "buy_score", "probability_value", "probability", "weekly_trend_score",
        "relative_strength_score", "daily_entry_score", "catalyst_score",
        "capital_flow_score", "market_regime_score", "risk_reward_score",
        "tradeability_score", "data_quality_score", "ma20_deviation_pct",
        "prev_day_gain_pct",
    ]
    rows = []
    for col in candidate_cols:
        if col not in df.columns:
            continue
        s = df[[col, "t1_return_pct"]].dropna()
        if len(s) < 3 or s[col].nunique() <= 1:
            continue
        try:
            ic = s[col].corr(s["t1_return_pct"])
            if math.isnan(ic):
                continue
        except Exception:
            continue
        try:
            q = pd.qcut(s[col], q=4, duplicates="drop")
            grouped = s.groupby(q, observed=True)["t1_return_pct"].agg(["mean", "count"])
            q1 = grouped.iloc[0]["mean"] if len(grouped) >= 2 else None
            q4 = grouped.iloc[-1]["mean"] if len(grouped) >= 2 else None
            monotonic = bool(len(grouped) >= 2 and safe_float(q4, 0) > safe_float(q1, 0))
        except Exception:
            q1 = q4 = None
            monotonic = False
        rows.append({
            "factor": col,
            "ic_t1": round(ic, 4),
            "n": len(s),
            "q1_avg_t1": round(safe_float(q1), 4) if q1 is not None else None,
            "q4_avg_t1": round(safe_float(q4), 4) if q4 is not None else None,
            "monotonic_q1_q4_up": monotonic,
        })
    if not rows:
        return
    pd.DataFrame(rows).sort_values("ic_t1", ascending=False).to_csv(
        output_dir / "threshold_ic_candidates.csv", index=False
    )
    print(f"[report] {output_dir / 'threshold_ic_candidates.csv'}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def amain() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--glob", default="agents_workspace/results/trade_decisions/*.json")
    parser.add_argument("--workspace", default="agents_workspace")
    parser.add_argument("--horizons", default="1,3,5")
    parser.add_argument("--min-samples", type=int, default=10)
    parser.add_argument("--parallel", type=int, default=4)
    args = parser.parse_args()

    horizons = [int(x) for x in str(args.horizons).split(",") if x.strip()]
    workspace = Path(args.workspace)
    settings = Settings(
        output_dir=str(workspace / "backtest_results"),
        horizons=horizons,
        parallel=args.parallel,
        min_samples=args.min_samples,
    )
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)

    records = load_all_signals(args.glob)
    if not records:
        print("No signals to evaluate.")
        return

    all_results = await evaluate_all(records, settings)
    mature = [r for r in all_results if r.get("t1_return_pct") is not None and r.get("_eval_error") != "pending_not_mature"]
    pending = [r for r in all_results if r.get("_eval_error") == "pending_not_mature" or r.get("t1_return_pct") is None]
    print(f"[eval] mature={len(mature)} pending={len(pending)}")
    if pending:
        pending_path = Path(settings.output_dir) / "signal_performance_pending.csv"
        pd.DataFrame(to_rows(pending)).to_csv(pending_path, index=False)
        print(f"[result] {pending_path}")

    if not mature:
        print("[warn] no mature evaluated signals yet; wrote pending only.")
        return
    evaluated = mature
    globals()["_last_pending"] = pending
    write_summary(evaluated, settings)
    write_ic_candidates(evaluated, settings)

    csv_path_full_path = Path(settings.output_dir) / "signal_performance.csv"
    pd.DataFrame(to_rows(evaluated)).to_csv(csv_path_full_path, index=False)
    print(f"[result] {csv_path_full_path}")

    jsonl_path = Path(settings.output_dir) / "signal_performance.jsonl"
    lines = []
    seen = set()
    for r in evaluated + pending:
        key = (
            r.get("__trigger_compact") or compact_ts(r.get("trigger_time")),
            r.get("symbol_code"),
            r.get("__group") or r.get("signal_group"),
        )
        if key in seen:
            continue
        seen.add(key)
        lines.append(json.dumps(r, ensure_ascii=False))
    with open(jsonl_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))
    print(f"[result] {jsonl_path}")
    print("[done]")


if __name__ == "__main__":
    asyncio.run(amain())
