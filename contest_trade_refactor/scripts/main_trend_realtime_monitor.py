#!/usr/bin/env python3
"""主升浪实时监控 / 收盘前状态检查。

读取最新 holdings.json，用腾讯财经实时行情刷新，跑退出状态机，可选通知。

用法:
  # 实时检查一次，不写文件
  .venv/bin/python scripts/main_trend_realtime_monitor.py --notify --notify-all

  # 收盘前 14:50 跑，且把最新状态写回 holdings.json（覆盖当前价）
  .venv/bin/python scripts/main_trend_realtime_monitor.py --write-back --notify
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from strategies.main_trend.dashboard import latest_holdings_payload
from strategies.main_trend.engine import MainTrendConfig, MainTrendEngine
from strategies.main_trend.schemas import Holding
from strategies.main_trend.notifier import notify
from utils.tencent_realtime import fetch_realtime_quote


def _f(v):
    try:
        return float(v)
    except Exception:
        return None


def build_holdings_with_realtime(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def one(r: Dict[str, Any]) -> Dict[str, Any]:
        code = str(r.get("symbol_code") or "")
        q = fetch_realtime_quote(code, prefer="tencent", timeout=3.0)
        out = dict(r)
        if q and q.price:
            out["current_price"] = q.price
            out["realtime_price"] = q.price
            out["realtime_source"] = q.source
            out["realtime_timestamp"] = q.timestamp
            rt = dict(out.get("realtime_quote") or {})
            if q.vwap:
                rt["vwap_state"] = "Above" if q.price >= q.vwap else "Below"
            rt["atr"] = q.detail.get("atr") if q.detail.get("atr") else rt.get("atr")
            rt["order_flow_score"] = rt.get("order_flow_score") or 50.0
            out["realtime_quote"] = rt
        return out
    with ThreadPoolExecutor(max_workers=12) as pool:
        return list(pool.map(one, rows))


def to_holdings(rows: List[Dict[str, Any]]) -> List[Holding]:
    out = []
    for r in rows:
        try:
            out.append(Holding(
                symbol_code=str(r.get("symbol_code") or ""),
                symbol_name=str(r.get("symbol_name") or ""),
                entry_date=str(r.get("entry_date") or ""),
                entry_price=_f(r.get("entry_price")) or 0.0,
                quantity=int(r.get("quantity") or 0),
                holding_days=int(r.get("holding_days") or 0),
                highest_price=_f(r.get("highest_price")) or _f(r.get("entry_price")) or 0.0,
                highest_close=_f(r.get("highest_close")),
                current_price=_f(r.get("current_price")),
                buy_score=_f(r.get("buy_score")) or 0.0,
                signal_tier=str(r.get("signal_tier") or "A"),
                trade_plan=r.get("trade_plan") or {},
                stop_loss_price=_f(r.get("stop_loss_price")),
                atr_trailing_stop=_f(r.get("atr_trailing_stop")),
                prev_close=_f(r.get("prev_close")),
                ma20=_f(r.get("ma20")),
                prev_ma20=_f(r.get("prev_ma20")),
                event_catalyst=r.get("event_catalyst") or {},
                realtime_quote=r.get("realtime_quote") or {},
                order_flow_score=float(r.get("order_flow_score") or 50),
            ))
        except Exception:
            continue
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings", default="", help="持仓JSON路径；默认取最新目录 holdings.json")
    parser.add_argument("--write-back", action="store_true", help="把最新价写回 holdings.json（收盘前建议）")
    parser.add_argument("--notify", action="store_true", help="发送通知")
    parser.add_argument("--notify-all", action="store_true", help="所有状态都通知（不只 SELL/REDUCE）")
    parser.add_argument("--dry-run-notify", action="store_true", help="只打印通知内容不发送")
    args = parser.parse_args()

    if args.holdings:
        hp = Path(args.holdings).expanduser().resolve()
        if not hp.exists():
            print(f"holdings not found: {hp}", file=sys.stderr); sys.exit(2)
        payload = json.loads(hp.read_text(encoding="utf-8"))
    else:
        payload = latest_holdings_payload(PROJECT_ROOT / "agents_workspace_main_trend")
        if not payload.get("present"):
            print("no holdings found", file=sys.stderr); sys.exit(1)
        hp = Path(payload["path"])

    rows = [dict(r) for r in (payload.get("rows") or payload.get("holdings") or []) if r.get("symbol_code")]
    print(f"loaded {len(rows)} holdings from {hp}")

    rows = build_holdings_with_realtime(rows)
    holdings = to_holdings(rows)
    if not holdings:
        print("no parseable holdings", file=sys.stderr); sys.exit(1)

    engine = MainTrendEngine(MainTrendConfig.from_yaml())
    decisions = [d.to_dict() for d in engine.evaluate_exits(holdings)]

    # 统计
    total_return = sum((h.current_price / h.entry_price - 1.0) * 100.0 for h in holdings if h.current_price and h.entry_price)
    avg_return = total_return / len(holdings)
    sells = [d for d in decisions if d.get("action") in ("sell", "exit")]
    reduces = [d for d in decisions if d.get("action") == "reduce"]

    print("=" * 60)
    print(f"实时监控 {datetime.now().isoformat(timespec='seconds')}  holdings={len(holdings)} avgReturn={avg_return:.2f}% sell={len(sells)} reduce={len(reduces)}")
    for d in decisions:
        mark = {"sell": "🔴", "exit": "🔴", "reduce": "🟠", "add": "🟢", "decay": "🟡", "hold": "⚪"}.get(d.get("action"), "⚪")
        print(f"{mark} {d.get('symbol_name')}({d.get('symbol_code')}) ret={d.get('current_return_pct')}% {d.get('reason')}")

    if args.write_back:
        # 合并最新价和决策到原文件（不删除））
        new_rows = []
        dec_map = {d.get("symbol_code"): d for d in decisions}
        for r in rows:
            code = str(r.get("symbol_code") or "")
            d = dec_map.get(code) or {}
            nr = dict(r)
            nr["position_state"] = d.get("state") or r.get("position_state") or "HOLD"
            nr["exit_action"] = d.get("action") or r.get("exit_action") or "hold"
            nr["exit_class"] = d.get("exit_class") or r.get("exit_class") or ""
            nr["current_return_pct"] = d.get("current_return_pct") or 0.0
            new_rows.append(nr)
        out_payload = dict(payload)
        out_payload["holdings"] = new_rows
        out_payload["last_run"] = datetime.now().isoformat(timespec="seconds")
        out_payload["as_of_date"] = payload.get("as_of_date") or ""
        hp.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote back {hp}")

    # 通知
    if args.notify or args.dry_run_notify:
        lines = []
        alert_lines = []
        for d in decisions:
            line = f"{d.get('symbol_name')}({d.get('symbol_code')}) {d.get('exit_class') or d.get('action')} ret={d.get('current_return_pct') or 0:.1f}% {d.get('reason') or ''}"
            if d.get("action") in ("sell", "exit", "reduce"):
                alert_lines.append(line)
            else:
                lines.append(line)
        if alert_lines:
            lines = alert_lines + lines
        if args.notify_all or alert_lines:
            config = {}
            try:
                import yaml
                config = (yaml.safe_load((PROJECT_ROOT / "strategies" / "main_trend" / "strategy.yaml").read_text(encoding="utf-8")) or {}).get("notify") or {}
            except Exception:
                pass
            notify(f"主升浪实时监控 {datetime.now().strftime('%Y-%m-%d %H:%M')}", lines, level="warning" if alert_lines else "info", config=config, dry_run=args.dry_run_notify)


if __name__ == "__main__":
    main()
