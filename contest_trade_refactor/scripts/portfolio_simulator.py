#!/usr/bin/env python3
"""
Portfolio-level simulated trading engine.

Reads the normalized signal_performance.csv produced by
`scripts/backtest_signal_closed_loop.py` and simulates a simple long-only
portfolio using the system's recommended position sizing.

Current behavior:
  - Simulates `buy_passed` signals only by default (--include-watch / --include-research opt-in)
  - Entry at next-trading-day open (already stored as entry_date / entry_price)
  - Position size from the allocator's recommended_position_size_pct
  - Optional stop-loss / take-profit during holding window
  - Enforces A-share T+1: no exit is allowed on the entry session
  - Sells at the configured holding-session close (default T3) or a later stop/take trigger
  - Applies commission, minimum commission, sell stamp duty and slippage

Outputs:
  agents_workspace/backtest_results/
    portfolio_trades.csv
    portfolio_equity.csv
    portfolio_summary.md

Usage:
  .venv/bin/python scripts/portfolio_simulator.py
  .venv/bin/python scripts/portfolio_simulator.py --include-watch --include-research
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.market_manager import GLOBAL_MARKET_MANAGER
from utils.cn_price_provider import get_stock_zh_a_hist


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        if isinstance(v, str):
            v = v.replace("%", "").replace(",", "")
        f = float(v)
        if math.isnan(f):
            return default
        return f
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


def get_price_map(symbol: str, start_compact: str, end_compact: str) -> Dict[str, Dict[str, Any]]:
    symbol = str(symbol).partition(".")[0]
    try:
        df = get_stock_zh_a_hist(symbol, start_date=start_compact, end_date=end_compact, adjust="qfq", verbose=False)
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    frame = df.copy()
    date_col = "日期" if "日期" in frame.columns else None
    if not date_col:
        return {}
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce").dt.strftime("%Y%m%d")
    frame = frame.drop_duplicates(date_col, keep="last").sort_values(date_col)
    return {str(r[date_col]): r.to_dict() for _, r in frame.iterrows()}


def tier_weight(signal_tier: str, fallback: float = 8.0) -> float:
    tier = str(signal_tier or "").upper()
    if tier.startswith("A"):
        return 15.0
    if tier.startswith("B"):
        return 8.0
    if tier.startswith("C"):
        return 5.0
    return fallback


def recommended_weight(row: pd.Series, cfg: "SimConfig") -> float:
    explicit = safe_float(row.get("recommended_position_size_pct"), 0.0)
    if explicit > 0:
        return min(cfg.max_position_pct, explicit)
    return min(
        cfg.max_position_pct,
        tier_weight(str(row.get("signal_tier") or ""), cfg.default_weight_pct),
    )


def max_drawdown_from_equity(eq: pd.DataFrame, value_col: str = "equity") -> float:
    if eq.empty or value_col not in eq:
        return 0.0
    peak = eq[value_col].cummax()
    dd = (eq[value_col] - peak) / peak * 100
    return float(dd.min())


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

@dataclass
class SimConfig:
    initial_cash: float = 1_000_000.0
    holding_days: int = 3
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    stamp_duty_rate: float = 0.0005
    slippage_bps: float = 2.0
    stop_loss_pct: float = -5.0
    take_profit_pct: float = 8.0
    enable_stop: bool = True
    include_watch: bool = False
    include_research: bool = False
    include_consensus: bool = False
    default_weight_pct: float = 8.0
    max_position_pct: float = 15.0
    min_fill_ratio: float = 0.5


def simulate_signals(df: pd.DataFrame, cfg: SimConfig) -> pd.DataFrame:
    """Simulate trades from the closed-loop CSV rows."""
    if cfg.holding_days < 2:
        raise ValueError("holding_days must be >= 2 for A-share T+1 execution")
    records = []
    available_cash = cfg.initial_cash
    active_positions: List[Dict[str, Any]] = []
    ordered = df.copy()
    if "entry_date" in ordered:
        ordered = ordered.sort_values(["entry_date", "trigger_time"], kind="stable")
    for _, row in ordered.iterrows():
        group = str(row.get("signal_group") or "")
        if group == "buy_passed":
            allowed = True
        elif group == "watch" and cfg.include_watch:
            allowed = True
        elif group == "research" and cfg.include_research:
            allowed = True
        elif group == "consensus" and cfg.include_consensus:
            allowed = True
        else:
            allowed = False
        if not allowed:
            continue

        symbol_raw = str(row.get("symbol_code") or row.get("symbol") or "").partition(".")[0]
        digits = "".join(ch for ch in symbol_raw if ch.isdigit())
        symbol = digits[-6:].zfill(6) if digits else symbol_raw
        entry_compact = str(row.get("entry_date") or "").replace("-", "")[:8]
        if not symbol or len(entry_compact) != 8:
            continue
        entry_price = safe_float(row.get("entry_price"), 0.0)
        if entry_price <= 0:
            continue

        # Release proceeds from positions closed before this entry session.
        still_active = []
        for position in active_positions:
            if str(position["exit_date"]) < entry_compact:
                available_cash += float(position["proceeds"])
            else:
                still_active.append(position)
        active_positions = still_active

        tier = str(row.get("signal_tier") or "").upper()
        weight_pct = recommended_weight(row, cfg)
        requested_budget = cfg.initial_cash * weight_pct / 100.0
        if requested_budget <= 0:
            continue
        if available_cash < requested_budget and available_cash / requested_budget < cfg.min_fill_ratio:
            continue
        budget = min(requested_budget, available_cash)

        future_dates = get_next_trade_dates(entry_compact, max(0, cfg.holding_days - 1))
        dates_in_window = [entry_compact] + future_dates
        if len(dates_in_window) < cfg.holding_days:
            continue
        end = dates_in_window[-1]
        trigger_compact = str(row.get("trigger_date") or entry_compact).replace("-", "")[:8]
        price_map = get_price_map(symbol, trigger_compact, end)
        if entry_compact not in price_map:
            continue

        # A one-price/near-limit-up open is not assumed fillable.
        previous = price_map.get(trigger_compact) or {}
        previous_close = safe_float(previous.get("收盘", previous.get("close")), 0.0)
        entry_row = price_map.get(entry_compact) or {}
        entry_open = safe_float(entry_row.get("开盘", entry_row.get("open")), entry_price)
        limit_pct = 19.5 if symbol.startswith(("300", "688")) else 9.7
        if previous_close > 0 and (entry_open / previous_close - 1.0) * 100.0 >= limit_pct:
            continue

        # Realistic share lot constraint: A-share trades in 100-share lots.
        per_share_entry_cost = entry_price * (1 + cfg.commission_rate + cfg.slippage_bps / 10000.0)
        shares = int(budget / per_share_entry_cost / 100) * 100
        if shares <= 0:
            continue

        buy_cost = entry_price * shares
        commission_buy = max(cfg.minimum_commission, buy_cost * cfg.commission_rate)
        slippage_buy = buy_cost * cfg.slippage_bps / 10000.0
        total_cost = buy_cost + commission_buy + slippage_buy
        if total_cost > available_cash:
            continue
        available_cash -= total_cost

        # Find exit: stop/take within window, else close at last available.
        exit_price = entry_price
        exit_date = entry_compact
        # Prefer the per-candidate trade_plan stop/take over the global defaults.
        plan_stop = safe_float(row.get("trade_plan_stop_loss"), 0.0)
        plan_take = safe_float(row.get("trade_plan_take_profit_1"), 0.0)
        if plan_stop > 0:
            stop_price = plan_stop
        else:
            stop_price = entry_price * (1 + cfg.stop_loss_pct / 100.0)
        if plan_take > 0:
            take_price = plan_take
        else:
            take_price = entry_price * (1 + cfg.take_profit_pct / 100.0)
        max_gain = entry_price
        max_loss = entry_price
        for session_index, d in enumerate(dates_in_window):
            r = price_map.get(d)
            if not r:
                continue
            try:
                opn = safe_float(r.get("开盘", r.get("open", entry_price)), entry_price)
                hi = safe_float(r.get("最高", r.get("high", entry_price)), entry_price)
                lo = safe_float(r.get("最低", r.get("low", entry_price)), entry_price)
                close = safe_float(r.get("收盘", r.get("close", entry_price)), entry_price)
            except Exception:
                continue
            max_gain = max(max_gain, hi)
            max_loss = min(max_loss, lo)
            # A shares bought today cannot be sold until the next trading day.
            # We still retain entry-session highs/lows for excursion statistics.
            if session_index == 0:
                exit_price = close
                exit_date = d
                continue
            if cfg.enable_stop and opn <= stop_price:
                exit_price = opn
                exit_date = d
                break
            if cfg.enable_stop and lo <= stop_price:
                exit_price = stop_price
                exit_date = d
                break
            if cfg.enable_stop and hi >= take_price:
                exit_price = take_price
                exit_date = d
                break
            exit_price = close
            exit_date = d

        commission_sell = max(cfg.minimum_commission, exit_price * shares * cfg.commission_rate)
        stamp_duty = exit_price * shares * cfg.stamp_duty_rate
        slippage_sell = exit_price * shares * cfg.slippage_bps / 10000.0
        proceeds = exit_price * shares - commission_sell - stamp_duty - slippage_sell
        pnl = proceeds - total_cost
        ret_pct = pnl / total_cost * 100 if total_cost else 0

        trade_record = {
            "trigger_time": row.get("trigger_time", ""),
            "symbol": symbol,
            "signal_group": group,
            "signal_tier": tier,
            "entry_date": entry_compact,
            "entry_price": round(entry_price, 4),
            "shares": shares,
            "buy_cost": round(total_cost, 2),
            "position_weight_pct": round(total_cost / cfg.initial_cash * 100.0, 3),
            "exit_date": exit_date,
            "exit_price": round(exit_price, 4),
            "days_held": len([d for d in dates_in_window if d in price_map]),
            "gross_return_pct": round((exit_price - entry_price) / entry_price * 100, 4),
            "pnl": round(pnl, 2),
            "fees": round(commission_buy + commission_sell + stamp_duty + slippage_buy + slippage_sell, 2),
            "return_after_cost_pct": round(ret_pct, 4),
            "max_gain_pct": round((max_gain - entry_price) / entry_price * 100, 4),
            "max_loss_pct": round((max_loss - entry_price) / entry_price * 100, 4),
            "trade_plan_pass": bool(row.get("trade_plan_pass", True)),
            "trade_plan_reject_reasons": str(row.get("trade_plan_reject_reasons") or ""),
        }
        records.append(trade_record)
        active_positions.append({"exit_date": exit_date, "proceeds": proceeds})
    return pd.DataFrame(records)


def build_equity_curve(trades: pd.DataFrame, initial_cash: float) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["date", "equity", "pnl", "drawdown_pct"])
    daily = trades.groupby("exit_date", as_index=False)["pnl"].sum().sort_values("exit_date")
    cash = initial_cash
    rows = [{"date": "START", "equity": cash, "pnl": 0.0}]
    for _, t in daily.iterrows():
        cash += t["pnl"]
        rows.append({"date": t["exit_date"], "equity": cash, "pnl": t["pnl"]})
    eq = pd.DataFrame(rows)
    if eq.empty:
        return eq
    peak = eq["equity"].cummax()
    eq["drawdown_pct"] = (eq["equity"] - peak) / peak * 100
    return eq


def summarize(trades: pd.DataFrame, initial_cash: float) -> Dict[str, Any]:
    if trades.empty:
        return {
            "trades": 0, "won": 0, "lost": 0, "win_rate_pct": 0.0,
            "avg_return_pct": 0.0, "avg_winner_pct": 0.0, "avg_loser_pct": 0.0,
            "total_pnl": 0.0, "return_pct": 0.0, "max_drawdown_pct": 0.0,
            "profit_factor": 0.0,
        }
    won = trades[trades["pnl"] > 0]
    lost = trades[trades["pnl"] < 0]
    total_pnl = trades["pnl"].sum()
    eq = build_equity_curve(trades, initial_cash)
    max_dd = max_drawdown_from_equity(eq)
    gross_win = won["pnl"].sum()
    gross_loss = abs(lost["pnl"].sum()) if len(lost) else 0
    pf = gross_win / gross_loss if gross_loss > 0 else (gross_win if gross_win > 0 else 0)
    return {
        "trades": len(trades),
        "won": len(won),
        "lost": len(lost),
        "win_rate_pct": round(len(won) / len(trades) * 100, 1) if len(trades) else 0.0,
        "avg_return_pct": round(trades['return_after_cost_pct'].mean(), 2),
        "avg_winner_pct": round(won['return_after_cost_pct'].mean(), 2) if len(won) else 0.0,
        "avg_loser_pct": round(lost['return_after_cost_pct'].mean(), 2) if len(lost) else 0.0,
        "total_pnl": round(total_pnl, 2),
        "return_pct": round(total_pnl / initial_cash * 100, 2) if initial_cash else 0.0,
        "max_drawdown_pct": round(max_dd, 2),
        "profit_factor": round(pf, 2),
    }


def write_report(summary: Dict[str, Any], trades: pd.DataFrame, equity: pd.DataFrame, cfg: SimConfig, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Portfolio Simulation Report",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"Initial cash: {cfg.initial_cash:,.2f}",
        f"Commission rate per side: {cfg.commission_rate:.4%}",
        f"Minimum commission per order: {cfg.minimum_commission:.2f}",
        f"Sell stamp duty: {cfg.stamp_duty_rate:.4%}",
        f"Slippage: {cfg.slippage_bps:.2f} bps per side",
        f"Minimum fill ratio: {cfg.min_fill_ratio:.2f}",
        f"Stop loss: {cfg.stop_loss_pct}%",
        f"Take profit: {cfg.take_profit_pct}%",
        f"Enable stop/take: {cfg.enable_stop}",
        "",
        "## Summary",
        "",
        f"Trades: {summary.get('trades', 0)}",
        f"Won: {summary.get('won', 0)}",
        f"Lost: {summary.get('lost', 0)}",
        f"Win rate: {summary.get('win_rate_pct', 0)}%",
        f"Avg return/trade: {summary.get('avg_return_pct', 0)}%",
        f"Avg winner: {summary.get('avg_winner_pct', 0)}%",
        f"Avg loser: {summary.get('avg_loser_pct', 0)}%",
        f"Total P&L: {summary.get('total_pnl', 0):,.2f}",
        f"Strategy return: {summary.get('return_pct', 0)}%",
        f"Max drawdown: {summary.get('max_drawdown_pct', 0)}%",
        f"Profit factor: {summary.get('profit_factor', 0)}",
        "",
    ]
    if not trades.empty:
        lines.append("## Trades")
        lines.append("")
        try:
            lines.append(trades.to_markdown(index=False))
        except Exception:
            lines.extend(trades.to_string(index=False).split("\n"))
        lines.append("")
        lines.append("## Equity curve (at exit dates)")
        lines.append("")
        try:
            lines.append(equity.to_markdown(index=False))
        except Exception:
            lines.extend(equity.to_string(index=False).split("\n"))

    (output_dir / "portfolio_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[report] {output_dir / 'portfolio_summary.md'}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(PROJECT_ROOT / "agents_workspace" / "backtest_results" / "signal_performance.csv"))
    parser.add_argument("--decision-glob", default="",
                        help="Optional glob to raw trade_decision JSON; if provided, first run backtest_signal_closed_loop.py to generate signal_performance.csv.")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "agents_workspace" / "backtest_results"))
    parser.add_argument("--initial-cash", type=float, default=1_000_000)
    parser.add_argument("--holding-days", type=int, default=3)
    parser.add_argument("--commission-pct", type=float, default=0.03, help="commission per side, e.g. 0.03 = 3 bps")
    parser.add_argument("--minimum-commission", type=float, default=5.0)
    parser.add_argument("--stamp-duty-pct", type=float, default=0.05)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--stop-loss-pct", type=float, default=-5.0)
    parser.add_argument("--take-profit-pct", type=float, default=8.0)
    parser.add_argument("--no-stop", action="store_true")
    parser.add_argument("--include-watch", action="store_true")
    parser.add_argument("--include-research", action="store_true")
    parser.add_argument("--include-consensus", action="store_true")
    parser.add_argument("--max-position-pct", type=float, default=15.0)
    parser.add_argument("--min-fill-ratio", type=float, default=0.5,
                        help="Reject scaled-down buys below this fraction of target budget.")
    args = parser.parse_args()

    cfg = SimConfig(
        initial_cash=args.initial_cash,
        holding_days=args.holding_days,
        commission_rate=args.commission_pct / 100.0,
        minimum_commission=args.minimum_commission,
        stamp_duty_rate=args.stamp_duty_pct / 100.0,
        slippage_bps=args.slippage_bps,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=args.take_profit_pct,
        enable_stop=not args.no_stop,
        include_watch=True if args.include_watch else False,
        include_research=True if args.include_research else False,
        include_consensus=args.include_consensus,
        max_position_pct=args.max_position_pct,
        min_fill_ratio=args.min_fill_ratio,
    )

    if args.decision_glob:
        print(f"[note] running closed-loop evaluator on --decision-glob {args.decision_glob}")
        import subprocess
        rc = subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "backtest_signal_closed_loop.py"),
                             "--glob", args.decision_glob, "--parallel", "4"], cwd=PROJECT_ROOT)
        if rc.returncode != 0:
            print("[error] closed-loop evaluator failed")
            sys.exit(rc.returncode)

    input_path = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not input_path.exists():
        print(f"[error] input not found: {input_path}")
        sys.exit(1)

    df = pd.read_csv(input_path)
    print(f"[sim] loaded {len(df)} signals from {input_path.name}")

    allowed_groups = {"buy_passed"}
    if cfg.include_watch:
        allowed_groups.add("watch")
    if cfg.include_research:
        allowed_groups.add("research")
    if cfg.include_consensus:
        allowed_groups.add("consensus")
    if "signal_group" in df.columns:
        df = df[df["signal_group"].astype(str).isin(allowed_groups)].copy()

    # Prefer a single canonical group per trigger_date+symbol so we don't double
    # count the same candidate across watch/research/consensus/buy.
    priority = {"buy_passed": 0, "consensus": 1, "watch": 2, "research": 3}
    if "signal_group" in df.columns:
        df["_priority"] = df["signal_group"].map(priority).fillna(99)
        df = (df.sort_values(["_priority"])
                .drop_duplicates(subset=["trigger_date", "symbol_code"], keep="first")
                .drop(columns=["_priority"]))
        print(f"[sim] after dedup: {len(df)} unique signal candidates")

    trades = simulate_signals(df, cfg)
    print(f"[sim] simulated {len(trades)} trades")
    if trades.empty:
        print("[warn] no trades generated; try --include-watch / --include-research")
    summary = summarize(trades, cfg.initial_cash)
    equity = build_equity_curve(trades, cfg.initial_cash)
    write_report(summary, trades, equity, cfg, output_dir)

    if not trades.empty:
        trades.to_csv(output_dir / "portfolio_trades.csv", index=False)
        equity.to_csv(output_dir / "portfolio_equity.csv", index=False)
        print(f"[result] {output_dir / 'portfolio_trades.csv'}")
        print(f"[result] {output_dir / 'portfolio_equity.csv'}")
    else:
        pd.DataFrame(columns=[
            "trigger_time", "symbol", "signal_group", "signal_tier", "entry_date",
            "entry_price", "shares", "buy_cost", "exit_date", "exit_price", "pnl",
        ]).to_csv(output_dir / "portfolio_trades.csv", index=False)
        equity.to_csv(output_dir / "portfolio_equity.csv", index=False)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
