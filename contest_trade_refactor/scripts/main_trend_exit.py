#!/usr/bin/env python3
"""主升浪日度退出引擎：输入持仓 JSON / t1_execution，输出 HOLD / REDUCE / SELL 清单。

用法:
  # 从既有 t1_execution.json + 当日实时价格快照评估
  .venv/bin/python scripts/main_trend_exit.py \\
      --holdings agents_workspace_main_trend/20260821/t1_execution.json \\
      --prices config/manual_execution_20260824.json \\
      --date 20260824 --output agents_workspace_main_trend/20260824/exit_decisions.json

  # 直接传持仓字段（用于测试/接口）
  .venv/bin/python scripts/main_trend_exit.py \\
      --holdings /tmp/holdings.json --prices /tmp/prices.json
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

from strategies.main_trend.engine import MainTrendConfig, MainTrendEngine
from strategies.main_trend.schemas import Holding


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        v = float(value)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_holdings(holdings_path: Path, prices_path: Optional[Path], date_compact: str = "") -> List[Holding]:
    price_map = {}
    if prices_path:
        try:
            price_map = _load_json(prices_path)
        except Exception as exc:
            print(f"cannot parse prices file: {exc}", file=sys.stderr)
            price_map = {}
    try:
        hd = _load_json(holdings_path)
    except Exception:
        # 支持直接读取列表
        hd = {"holdings": json.loads(holdings_path.read_text(encoding="utf-8")) if holdings_path.exists() else []}
    raw_rows = []
    if isinstance(hd, list):
        raw_rows = hd
    else:
        raw_rows = hd.get("holdings") or hd.get("rows") or (hd.get("pool") if "pool" in hd else []) or []
        # 兼容 t1_execution.json: rows 数组
        if not raw_rows and "rows" in hd:
            raw_rows = hd["rows"]

    if price_map:
        names = price_map.get("names") or {}
        for row in raw_rows:
            code = str(row.get("symbol_code") or "")
            if not code:
                continue
            raw = names.get(code) or names.get(code.zfill(6)) or {}
            if not raw:
                continue
            if row.get("current_price") is None:
                row["current_price"] = raw.get("price_0935") if raw.get("price_0935") is not None else raw.get("open")
            if row.get("holdings_days") is None and row.get("holding_days") is None:
                row["holding_days"] = 0
            if row.get("prev_close") is None:
                row["prev_close"] = raw.get("prev_close")
            if row.get("ma20") is None and "ma20" not in row:
                # 如果 t1_execution 已带 MA20 则保留；这里不联网补
                row["ma20"] = raw.get("ma20")
            if row.get("realtime_quote") is None:
                row["realtime_quote"] = {
                    "vwap_state": raw.get("vwap_state", ""),
                    "order_flow_score": raw.get("order_flow_score"),
                    "atr_pct": raw.get("atr_pct"),
                }

    holdings_out = []
    for r in raw_rows:
        if not r:
            continue
        code = str(r.get("symbol_code") or "")
        if not code:
            continue
        holdings_out.append(Holding(
            symbol_code=code,
            symbol_name=str(r.get("symbol_name") or ""),
            entry_date=str(r.get("entry_date") or date_compact or ""),
            entry_price=_num(r.get("entry_price"), 0.0) or 0.0,
            quantity=int(r.get("quantity") or 0),
            holding_days=int(r.get("holding_days") or 0),
            highest_price=_num(r.get("highest_price"), 0.0) or 0.0,
            highest_close=_num(r.get("highest_close")),
            current_price=_num(r.get("current_price")),
            buy_score=_num(r.get("buy_score"), 0.0) or 0.0,
            signal_tier=str(r.get("signal_tier") or "A"),
            trade_plan=r.get("trade_plan") or {},
            stop_loss_price=_num(r.get("stop_loss_price")),
            atr_trailing_stop=_num(r.get("atr_trailing_stop")),
            prev_close=_num(r.get("prev_close")),
            ma20=_num(r.get("ma20")),
            prev_ma20=_num(r.get("prev_ma20")),
            event_catalyst=r.get("event_catalyst"),
            realtime_quote=r.get("realtime_quote") or {},
            order_flow_score=_num(r.get("order_flow_score"), 50.0) or 50.0,
        ))
    return holdings_out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings", required=True, help="持仓 JSON 或 t1_execution.json")
    parser.add_argument("--prices", default="", help="当日价格/手工执行快照 JSON，用于回填 current_price/prev_close/ma20")
    parser.add_argument("--date", default="", help="评估日期（YYYY-MM-DD 或 YYYYMMDD）")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    hp = Path(args.holdings).expanduser().resolve()
    if not hp.is_absolute():
        hp = PROJECT_ROOT / hp
    price_map = {}
    if args.prices:
        pp = Path(args.prices).expanduser().resolve()
        if not pp.is_absolute():
            pp = PROJECT_ROOT / pp
        if not pp.exists():
            print(f"--prices file not found: {pp}", file=sys.stderr)
            sys.exit(2)
        try:
            price_map = _load_json(pp)
        except Exception as exc:
            print(f"cannot parse prices file: {exc}", file=sys.stderr)
            sys.exit(2)

    date_compact = str(args.date or "").replace("-", "").replace("/", "")
    holdings = resolve_holdings(hp, Path(args.prices) if args.prices else None, date_compact)
    if not holdings:
        print("No holdings found in input.", file=sys.stderr)
        sys.exit(1)

    engine = MainTrendEngine(MainTrendConfig.from_yaml())
    decisions = [d.to_dict() for d in engine.evaluate_exits(holdings)]
    decisions.sort(key=lambda x: (x.get("action") == "exit" or x.get("action") == "sell", x.get("exit_score") or 0), reverse=True)

    payload = {
        "as_of_date": date_compact or None,
        "positions_count": len(holdings),
        "decisions": decisions,
    }
    if args.output:
        op = Path(args.output).expanduser()
        if not op.is_absolute():
            op = PROJECT_ROOT / op
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {op}")

    # 打印
    print("=" * 72)
    print(f"主升浪退出状态机  as_of_date={date_compact or '?'}  持仓数={len(holdings)}")
    print("=" * 72)
    for d in decisions:
        mark = {
            "sell": "🔴 SELL",
            "exit": "🔴 SELL",
            "reduce": "🟠 REDUCE",
            "decay": "🟡 DECAY",
            "add": "🟢 ADD",
            "hold": "⚪ HOLD",
        }.get(d.get("action"), d.get("action"))
        code = str(d.get("symbol_code") or "")
        name = str(d.get("symbol_name") or "")
        ret = d.get("current_return_pct", 0.0)
        level = d.get("exit_level") or "P4"
        cls = d.get("exit_class") or "HOLD"
        reason = str(d.get("reason") or "")
        trailing = d.get("trailing_stop_price")
        trailing_s = "" if trailing is None else f"  trail={trailing:.2f}"
        print(f"{mark} {level}/{cls} {name}({code}) 收益{ret:+.1f}%{trailing_s}  | {reason}")


if __name__ == "__main__":
    main()
