#!/usr/bin/env python3
"""主升浪持仓初始化/更新与通知入口。

用法:
  # 初始化：把 T+1 BUY 固化为持仓（默认写 agents_workspace_main_trend/<date>/holdings.json）
  .venv/bin/python scripts/main_trend_holdings.py --date 20260824 --init

  # 每日更新：跑退出状态机，写入 exit_decisions.json，并合并到 holdings.json
  .venv/bin/python scripts/main_trend_holdings.py --date 20260825 \\
      --holdings agents_workspace_main_trend/20260824/holdings.json \\
      --prices config/manual_execution_20260825.json --update

  # 只在页面展示/通知新状态，不更新持仓文件
  .venv/bin/python scripts/main_trend_holdings.py --date 20260825 --check --prices config/manual_execution_20260825.json

  # 通知只在有 SELL/REDUCE 时发送；全量通知便于调试
  .venv/bin/python scripts/main_trend_holdings.py --date 20260825 --check --prices config/manual_execution_20260825.json --notify
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from strategies.main_trend.dashboard import latest_exit_payload, latest_holdings_payload, latest_t1_payload, latest_tday_payload
from strategies.main_trend.engine import MainTrendConfig, MainTrendEngine
from strategies.main_trend.event_logger import log_event
from strategies.main_trend.holdings import build_from_result_rows, build_from_t1, update_holdings
from strategies.main_trend.notifier import notify
import yaml
from strategies.main_trend.schemas import Holding

BASE = PROJECT_ROOT / "agents_workspace_main_trend"


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        v = float(value)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def to_holding_dict(h: Holding) -> Dict[str, Any]:
    d = {
        "symbol_code": h.symbol_code,
        "symbol_name": h.symbol_name,
        "entry_date": h.entry_date,
        "entry_price": round(h.entry_price, 4) if h.entry_price else None,
        "quantity": h.quantity,
        "holding_days": h.holding_days,
        "highest_price": h.highest_price,
        "highest_close": h.highest_close,
        "current_price": h.current_price,
        "buy_score": h.buy_score,
        "signal_tier": h.signal_tier,
        "trade_plan": h.trade_plan,
        "stop_loss_price": h.stop_loss_price,
        "atr_trailing_stop": h.atr_trailing_stop,
        "prev_close": h.prev_close,
        "ma20": h.ma20,
        "prev_ma20": h.prev_ma20,
        "event_catalyst": h.event_catalyst or {},
        "realtime_quote": h.realtime_quote or {},
        "order_flow_score": h.order_flow_score,
    }
    return d


def resolve_holdings_from_rows(rows: List[Dict[str, Any]], date: str) -> List[Holding]:
    out = []
    for r in rows:
        if not r:
            continue
        code = str(r.get("symbol_code") or "")
        if not code:
            continue
        out.append(Holding(
            symbol_code=code,
            symbol_name=str(r.get("symbol_name") or ""),
            entry_date=str(r.get("entry_date") or date),
            entry_price=_num(r.get("entry_price")) or 0.0,
            quantity=int(r.get("quantity") or 0),
            holding_days=int(r.get("holding_days") or 0),
            highest_price=_num(r.get("highest_price")) or _num(r.get("entry_price")) or 0.0,
            highest_close=_num(r.get("highest_close")),
            current_price=_num(r.get("current_price")),
            buy_score=_num(r.get("buy_score")) or 0.0,
            signal_tier=str(r.get("signal_tier") or "A"),
            trade_plan=r.get("trade_plan") or {},
            stop_loss_price=_num(r.get("stop_loss_price")),
            atr_trailing_stop=_num(r.get("atr_trailing_stop")),
            prev_close=_num(r.get("prev_close")),
            ma20=_num(r.get("ma20")),
            prev_ma20=_num(r.get("prev_ma20")),
            event_catalyst=r.get("event_catalyst") or {},
            realtime_quote=r.get("realtime_quote") or {},
            order_flow_score=_num(r.get("order_flow_score"), 50.0) or 50.0,
        ))
    return out


def apply_prices_to_rows(rows: List[Dict[str, Any]], prices: Dict[str, Any]) -> List[Dict[str, Any]]:
    names = prices.get("names") or {}
    for r in rows:
        code = str(r.get("symbol_code") or "")
        raw = names.get(code) or names.get(code.zfill(6)) or {}
        if not raw:
            continue
        cur = raw.get("price_0935")
        if cur is None:
            cur = raw.get("price") or raw.get("open")
        if cur is not None:
            r["current_price"] = float(cur)
        if r.get("prev_close") is None and raw.get("prev_close") is not None:
            r["prev_close"] = float(raw["prev_close"])
        if r.get("ma20") is None and raw.get("ma20") is not None:
            r["ma20"] = float(raw["ma20"])
        if r.get("prev_ma20") is None and raw.get("prev_ma20") is not None:
            r["prev_ma20"] = float(raw["prev_ma20"])
        if r.get("highest_price") is None:
            r["highest_price"] = r.get("current_price")
        if r.get("highest_close") is None:
            r["highest_close"] = r.get("current_price")
        if r.get("atr") is None and raw.get("atr") is not None:
            r["atr"] = float(raw["atr"])
        rt = dict(r.get("realtime_quote") or {})
        rt.setdefault("atr", raw.get("atr") or r.get("atr"))
        rt.setdefault("atr_pct", raw.get("atr_pct") or r.get("atr_pct"))
        rt.setdefault("vwap_state", raw.get("vwap_state") or r.get("vwap_state"))
        rt.setdefault("bid_support", raw.get("bid_support") or r.get("bid_support"))
        rt.setdefault("order_flow_score", raw.get("order_flow_score") or r.get("order_flow_score") or 50)
        r["realtime_quote"] = rt
    return rows


def _write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="")
    parser.add_argument("--tday", default="")
    parser.add_argument("--t1", default="")
    parser.add_argument("--result", default="", help="result.json 路径；优先用 candidate_pool_t1 构建持仓")
    parser.add_argument("--holdings", default="")
    parser.add_argument("--prices", default="")
    parser.add_argument("--init", action="store_true", help="从 tday_pool + t1_execution 初始化持仓")
    parser.add_argument("--update", action="store_true", help="读持仓 -> 评估退出 -> 合并状态写回")
    parser.add_argument("--check", action="store_true", help="只评估退出并打印/通知，不写 holdings.json")
    parser.add_argument("--output-dir", default="agents_workspace_main_trend")
    parser.add_argument("--notify", action="store_true", help="状态变化时发送通知")
    parser.add_argument("--dry-run-notify", action="store_true", help="只打印通知内容不真的发送")
    parser.add_argument("--no-sell-notify", action="store_true", help="只有 SELL/REDUCE 才通知（默认）")
    parser.add_argument("--notify-all", action="store_true", help="所有状态都通知（调试用）")
    args = parser.parse_args()

    out_base = Path(args.output_dir).expanduser().resolve()
    if not out_base.is_absolute():
        out_base = PROJECT_ROOT / out_base
    component_dir = out_base

    # resolve input paths

    date = str(args.date or "").replace("-", "").replace("/", "")
    if not date:
        # 如果没给 --date，尝试从最新 t1 推断
        latest_t1 = latest_t1_payload(component_dir)
        if latest_t1.get("present"):
            date = latest_t1.get("trade_date") or ""
    if not date and args.t1:
        try:
            t1d = load_json(Path(args.t1).expanduser())
            date = str(t1d.get("trade_date") or "").replace("-", "").replace("/", "")
        except Exception:
            pass
    if not date:
        print("--date required or cannot infer from inputs", file=sys.stderr)
        sys.exit(2)

    # init mode —— 自动发现 tday_pool + t1_execution
    holdings_path = Path(args.holdings).expanduser() if args.holdings else component_dir / date / "holdings.json"
    if args.init:
        tday_path = Path(args.tday).expanduser().resolve() if args.tday else component_dir / date / "tday_pool.json"
        t1_path = Path(args.t1).expanduser().resolve() if args.t1 else component_dir / date / "t1_execution.json"
        if not tday_path.is_absolute():
            tday_path = PROJECT_ROOT / tday_path
        if not t1_path.is_absolute():
            t1_path = PROJECT_ROOT / t1_path
        if not tday_path.exists():
            fallback = latest_tday_payload(out_base)
            if fallback.get("present"):
                tday_path = Path(fallback["path"])
        if not t1_path.exists():
            fallback = latest_t1_payload(out_base)
            if fallback.get("present"):
                t1_path = Path(fallback["path"])
        # 优先从 result.json 的 candidate_pool_t1 / buy_signals 直接构建持仓
        result_path = Path(args.result).expanduser() if args.result else component_dir / date / "result.json"
        result_payload_used = False
        if result_path.exists():
            result_payload = load_json(result_path)
            rows = result_payload.get("candidate_pool_t1") or result_payload.get("buy_signals") or []
            if rows:
                holdings_payload = build_from_result_rows(rows, date=date)
                result_payload_used = True
        if not result_payload_used:
            if not tday_path.exists() or not t1_path.exists():
                print(f"tday or t1 missing: {tday_path} / {t1_path}", file=sys.stderr)
                sys.exit(2)
            tday = load_json(tday_path)
            t1 = load_json(t1_path)
            holdings_payload = build_from_t1(tday, t1, date=date)
        out_path = component_dir / date / "holdings.json"
        if args.holdings:
            out_path = Path(args.holdings).expanduser()
            if not out_path.is_absolute():
                out_path = PROJECT_ROOT / out_path
        _write(out_path, holdings_payload)
        print(f"wrote {out_path} ({holdings_payload['count']} holdings)")
        log_event(out_path.parent, {"event": "holdings_init", "date": date, "count": holdings_payload["count"]})
        return

    # 读取已有持仓 payload
    if args.holdings:
        hp = Path(args.holdings).expanduser()
        if not hp.is_absolute():
            hp = PROJECT_ROOT / hp
        if not hp.exists():
            print(f"holdings file not found: {hp}", file=sys.stderr)
            sys.exit(2)
        holdings_payload = load_json(hp)
    else:
        latest = latest_holdings_payload(out_base)
        if not latest.get("present"):
            print("No holdings found; run --init first or pass --holdings", file=sys.stderr)
            sys.exit(1)
        holdings_path = Path(latest["path"])
        holdings_payload = load_json(holdings_path)

    # prices
    prices: Dict[str, Any] = {}
    if args.prices:
        pp = Path(args.prices).expanduser()
        if not pp.is_absolute():
            pp = PROJECT_ROOT / pp
        if not pp.exists():
            print(f"prices file not found: {pp}", file=sys.stderr)
            sys.exit(2)
        prices = load_json(pp)

    rows = holdings_payload.get("holdings") or []
    rows = apply_prices_to_rows(list(rows), prices)
    holdings_list = resolve_holdings_from_rows(rows, date)
    if not holdings_list:
        print("No holdings rows.", file=sys.stderr)
        sys.exit(1)

    engine = MainTrendEngine(MainTrendConfig.from_yaml())
    decisions = [d.to_dict() for d in engine.evaluate_exits(holdings_list)]
    decisions.sort(key=lambda x: (x.get("action") in ("sell", "exit", "reduce"), x.get("exit_score") or 0), reverse=True)
    exit_payload = {"as_of_date": date or holdings_payload.get("as_of_date") or "", "positions_count": len(holdings_list), "decisions": decisions}

    # write exit decisions
    if date:
        exit_path = component_dir / date / "exit_decisions.json"
    elif holdings_payload.get("as_of_date"):
        exit_path = component_dir / (str(holdings_payload.get("as_of_date")).replace("-", "")) / "exit_decisions.json"
    else:
        exit_path = component_dir / "latest" / "exit_decisions.json"
    _write(exit_path, exit_payload)
    print(f"wrote {exit_path}")

    # merge holdings if update
    if args.update:
        holdings_payload_merged = update_holdings(holdings_payload, decisions, date or holdings_payload.get("as_of_date") or "")
        out_path = (
            Path(args.holdings).expanduser().resolve()
            if args.holdings
            else component_dir / (str(date or holdings_payload.get("as_of_date") or "").replace("-", "")) / "holdings.json"
        )
        if not out_path.is_absolute():
            out_path = PROJECT_ROOT / out_path
        _write(out_path, holdings_payload_merged)
        print(f"wrote {out_path} (updated {len(holdings_payload_merged['holdings'])} holdings)")
        log_event(out_path.parent, {"event": "holdings_update", "date": date, "count": len(holdings_payload_merged["holdings"])})

    # print console
    print("=" * 64)
    level_colors = {"sell": "🔴", "reduce": "🟠", "decay": "🟡", "hold": "⚪", "add": "🟢"}
    for d in decisions:
        mark = level_colors.get(d.get("action") or "hold", "⚪")
        print(f"{mark} {d.get('symbol_name')}({d.get('symbol_code')}) exit={d.get('exit_class') or d.get('state') or 'HOLD'} ret={d.get('current_return_pct') or 0:.1f}% | {d.get('reason')}")

    # notify
    should_notify = args.notify
    if should_notify:
        subject = f"主升浪持仓状态 {date or exit_payload.get('as_of_date') or ''}"
        lines = []
        alert_lines = []
        for d in decisions:
            line = f"{d.get('symbol_name')}({d.get('symbol_code')}) {d.get('exit_class') or d.get('action')} ret={d.get('current_return_pct') or 0:.1f}% {d.get('reason') or ''}"
            if d.get('action') in ("sell", "exit", "reduce"):
                alert_lines.append(line)
            else:
                lines.append(line)
        if alert_lines:
            lines = alert_lines + lines
        if (args.notify_all or alert_lines) and (args.notify or args.dry_run_notify):
            notify_cfg = {}
            try:
                notify_cfg = (yaml.safe_load((PROJECT_ROOT / "strategies" / "main_trend" / "strategy.yaml").read_text(encoding="utf-8")) or {}).get("notify") or {}
            except Exception:
                notify_cfg = {}
            notify(subject, lines, level="warning" if alert_lines else "info", config=notify_cfg, dry_run=args.dry_run_notify)


if __name__ == "__main__":
    main()
