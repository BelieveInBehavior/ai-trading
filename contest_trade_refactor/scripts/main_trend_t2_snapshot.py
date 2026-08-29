#!/usr/bin/env python3
"""T+2 持仓监控：拉实时行情、跑退出状态机、按时间点落盘。

默认读取 agents_workspace_main_trend/20260824/holdings.json（T+1 收盘持仓），
写入 agents_workspace_main_trend/20260824/t2/<YYYYMMDD>_<HHMM>/
以及 config/manual_execution_<YYYYMMDD>_<HHMM>.json。

用法:
  .venv/bin/python scripts/main_trend_t2_snapshot.py
  .venv/bin/python scripts/main_trend_t2_snapshot.py --wave 1430
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.main_trend_holdings import resolve_holdings_from_rows, to_holding_dict
from strategies.main_trend.engine import MainTrendConfig, MainTrendEngine
from strategies.main_trend.event_logger import log_event
from strategies.main_trend.holdings import compute_display_status, update_holdings
from utils.tencent_realtime import fetch_realtime_quote

BASE = PROJECT_ROOT / "agents_workspace_main_trend"
INDEX_CODES = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    "sh000300": "沪深300",
    "sh000016": "上证50",
    "sh000905": "中证500",
    "sh000852": "中证1000",
    "sh000688": "科创50",
}


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_indices() -> Dict[str, Any]:
    q = ",".join(INDEX_CODES)
    url = f"https://qt.gtimg.cn/q={q}"
    out: Dict[str, Any] = {}
    try:
        text = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"}).text
    except Exception as exc:
        return {"error": str(exc)}
    for line in text.split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        code = key.replace("v_", "")
        parts = raw.strip('"; \n').split("~")
        if len(parts) < 6:
            continue
        price = _f(parts[3])
        prev = _f(parts[4])
        chg = None
        if price is not None and prev:
            chg = round((price / prev - 1.0) * 100.0, 2)
        out[INDEX_CODES.get(code, code)] = {
            "code": code,
            "name": parts[1] or INDEX_CODES.get(code, code),
            "price": price,
            "prev_close": prev,
            "open": _f(parts[5]),
            "change_pct": chg,
        }
    return out


def quote_to_row(q: Any) -> Dict[str, Any]:
    if not q:
        return {}
    px = _f(q.price)
    vwap = _f(q.vwap)
    return {
        "name": q.symbol_name,
        "price": px,
        "prev_close": _f(q.prev_close),
        "open": _f(q.open),
        "high": _f(q.high),
        "low": _f(q.low),
        "change_pct": (
            round((px / q.prev_close - 1.0) * 100.0, 4)
            if px and _f(q.prev_close)
            else None
        ),
        "amount_wan": _f(q.amount_wan),
        "vwap": vwap,
        "volume_ratio": _f((q.detail or {}).get("volume_ratio")),
        "vwap_state": "Above" if px is not None and vwap and px >= vwap else ("Below" if px is not None and vwap else ""),
        "bid_support": "强" if px is not None and vwap and px >= vwap else "弱",
        "ts": q.timestamp,
        "source": q.source,
    }


def apply_quote(row: Dict[str, Any], snap: Dict[str, Any], holding_days: int) -> Dict[str, Any]:
    item = dict(row)
    px = _f(snap.get("price"))
    high = _f(snap.get("high"))
    if px is not None:
        item["current_price"] = px
        item["highest_price"] = max(_f(item.get("highest_price")) or 0.0, high or px)
        item["highest_close"] = max(_f(item.get("highest_close")) or 0.0, px)
    if snap.get("prev_close") is not None:
        item["prev_close"] = snap["prev_close"]
    item["holding_days"] = holding_days
    rt = dict(item.get("realtime_quote") or {})
    for key in ("open", "high", "low", "vwap", "vwap_state", "bid_support", "price", "volume_ratio"):
        if snap.get(key) not in (None, ""):
            rt[key] = snap[key]
    if px is not None:
        rt["price"] = px
    item["realtime_quote"] = rt
    return item


def seed_previous_day_guards(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """用源持仓中的上一日收盘盘口补齐次日警戒位。

    T+2 拉实时行情前，源持仓的 realtime_quote 仍代表 T+1 收盘，因此这里
    只补缺失值；已有警戒位绝不被盘中波次覆盖。
    """
    seeded = []
    for row in rows:
        item = dict(row)
        tp = dict(item.get("trade_plan") or {})
        rt = item.get("realtime_quote") or {}
        prev_vwap = _f(rt.get("vwap")) or _f(tp.get("vwap")) or _f(tp.get("vwap_20"))
        prev_high = _f(rt.get("high")) or _f(tp.get("high"))
        if tp.get("next_day_guard_vwap") is None and prev_vwap is not None:
            tp["next_day_guard_vwap"] = round(prev_vwap, 4)
        if tp.get("next_day_guard_high") is None and prev_high is not None:
            tp["next_day_guard_high"] = round(prev_high, 4)
        item["trade_plan"] = tp
        seeded.append(item)
    return seeded


def status_of(d: Dict[str, Any]) -> str:
    return compute_display_status(
        {
            "exit_action": d.get("action"),
            "exit_class": d.get("exit_class"),
            "position_state": d.get("state") or d.get("position_state"),
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings", default="agents_workspace_main_trend/20260824/holdings.json")
    parser.add_argument("--trade-date", default="20260825", help="T+2 交易日")
    parser.add_argument("--wave", default="", help="时间点 HHMM；默认用当前时间")
    parser.add_argument("--holding-days", type=int, default=1, help="相对入场的持仓天数，T+2 默认 1")
    args = parser.parse_args()

    now = datetime.now()
    wave = str(args.wave or now.strftime("%H%M"))
    trade_date = str(args.trade_date).replace("-", "")
    stamp = f"{trade_date}_{wave}"

    hp = Path(args.holdings)
    if not hp.is_absolute():
        hp = PROJECT_ROOT / hp
    payload = json.loads(hp.read_text(encoding="utf-8"))
    raw_rows = seed_previous_day_guards(
        [dict(r) for r in (payload.get("holdings") or []) if r.get("symbol_code")]
    )
    print(f"loaded {len(raw_rows)} holdings from {hp}")

    def one(r: Dict[str, Any]) -> Dict[str, Any]:
        code = str(r.get("symbol_code") or "")
        q = fetch_realtime_quote(code, prefer="tencent", timeout=3.0)
        return quote_to_row(q)

    with ThreadPoolExecutor(max_workers=12) as pool:
        snaps = list(pool.map(one, raw_rows))

    quotes = {str(r.get("symbol_code") or ""): s for r, s in zip(raw_rows, snaps)}
    rows = [apply_quote(r, quotes.get(str(r.get("symbol_code") or "")) or {}, args.holding_days) for r in raw_rows]
    holdings = resolve_holdings_from_rows(rows, trade_date)
    if not holdings:
        print("no parseable holdings", file=sys.stderr)
        sys.exit(1)

    engine = MainTrendEngine(MainTrendConfig.from_yaml())
    # 先刷昨日因子（MA/RS），再写回盘中现价，避免 refresh 用昨日收盘覆盖实时价。
    holdings = engine.refresh_holding_factors(holdings, trade_date=trade_date)
    for h in holdings:
        snap = quotes.get(h.symbol_code) or {}
        px = _f(snap.get("price"))
        if px is None:
            continue
        h.current_price = px
        if _f(snap.get("high")) is not None:
            h.highest_price = max(h.highest_price or 0.0, float(snap["high"]))
        h.highest_close = max(h.highest_close or 0.0, px)
        rt = dict(h.realtime_quote or {})
        for key in ("open", "high", "low", "vwap", "vwap_state", "bid_support", "price", "volume_ratio"):
            if snap.get(key) not in (None, ""):
                rt[key] = snap[key]
        rt["price"] = px
        h.realtime_quote = rt
    # 15:00 才把今日 VWAP/高点固化给下一交易日；盘中波次始终使用昨日警戒位。
    persist_guard = wave >= "1500"
    decisions = [
        d.to_dict()
        for d in engine.evaluate_exits(
            holdings,
            refresh_factors=False,
            trade_date=trade_date,
            persist_next_day_guard=persist_guard,
        )
    ]
    decisions.sort(
        key=lambda x: (status_of(x) in ("SELL", "REDUCE", "ADD"), x.get("exit_score") or 0),
        reverse=True,
    )
    # 使用刷新后的 Holding 写盘，保留 MA10、最新因子和日终警戒位。
    evaluated_rows = [to_holding_dict(h) for h in holdings]
    merged = update_holdings({**payload, "holdings": evaluated_rows}, decisions, trade_date)
    merged["phase"] = "t2"
    merged["wave"] = wave
    merged["as_of_date"] = trade_date
    merged["source_holdings"] = str(hp)
    merged["holding_days"] = args.holding_days

    counts = Counter(status_of(d) for d in decisions)
    rets = [float(d.get("current_return_pct") or 0.0) for d in decisions]
    avg_ret = sum(rets) / len(rets) if rets else 0.0
    indices = fetch_indices()

    summary = {
        "phase": "t2",
        "trade_date": trade_date,
        "wave": wave,
        "logged_at": now.isoformat(timespec="seconds"),
        "source_holdings": str(hp),
        "count": len(decisions),
        "avg_return_pct": round(avg_ret, 2),
        "counts": dict(counts),
        "indices": indices,
        "rows": [
            {
                "symbol_code": d.get("symbol_code"),
                "symbol_name": d.get("symbol_name"),
                "status": status_of(d),
                "exit_class": d.get("exit_class") or d.get("action"),
                "current_return_pct": d.get("current_return_pct"),
                "current_price": quotes.get(str(d.get("symbol_code") or ""), {}).get("price"),
                "reason": d.get("reason"),
            }
            for d in decisions
        ],
    }

    day_dir = hp.parent
    out_dir = day_dir / "t2" / stamp
    write_json(out_dir / "holdings.json", merged)
    write_json(
        out_dir / "exit_decisions.json",
        {
            "as_of_date": trade_date,
            "wave": wave,
            "phase": "t2",
            "positions_count": len(decisions),
            "logic": "add_setup_confirmation_sector_rs",
            "decisions": decisions,
        },
    )
    write_json(out_dir / "quotes.json", quotes)
    write_json(out_dir / "summary.json", summary)
    write_json(day_dir / "t2" / "latest.json", {**summary, "path": str(out_dir)})

    names = {}
    for r, snap in zip(raw_rows, snaps):
        code = str(r.get("symbol_code") or "")
        names[code] = {
            "symbol_name": r.get("symbol_name") or snap.get("name"),
            "open": snap.get("open"),
            "price": snap.get("price"),
            "price_0935": snap.get("price"),
            "prev_close": snap.get("prev_close"),
            "high": snap.get("high"),
            "low": snap.get("low"),
            "vwap": snap.get("vwap"),
            "vwap_state": snap.get("vwap_state"),
            "bid_support": snap.get("bid_support"),
        }
    write_json(
        PROJECT_ROOT / "config" / f"manual_execution_{stamp}.json",
        {
            "trade_date": trade_date,
            "snapshot_time": wave,
            "phase": "t2",
            "pulled_at": now.isoformat(timespec="seconds"),
            "index_change_pct": (indices.get("上证指数") or {}).get("change_pct"),
            "names": names,
        },
    )

    log_event(
        day_dir,
        {
            "event": "t2_snapshot",
            "date": trade_date,
            "wave": wave,
            "counts": dict(counts),
            "avg_return_pct": round(avg_ret, 2),
            "path": str(out_dir),
        },
    )

    print("=" * 72)
    print(f"T+2 {trade_date} wave={wave} n={len(decisions)} avg={avg_ret:+.2f}% counts={dict(counts)}")
    sh = indices.get("上证指数") or {}
    sz = indices.get("深证成指") or {}
    cy = indices.get("创业板指") or {}
    print(f"指数 上证{sh.get('change_pct')} 深成{sz.get('change_pct')} 创业{cy.get('change_pct')}")
    for d in decisions:
        status = status_of(d)
        mark = {"SELL": "🔴", "REDUCE": "🟠", "DECAY": "🟡", "ADD": "🟢", "HOLD": "⚪"}.get(status, "⚪")
        print(
            f"{mark} {status:6} {d.get('symbol_name')}({d.get('symbol_code')}) "
            f"ret={float(d.get('current_return_pct') or 0):+.2f}% | {d.get('reason')}"
        )
    print("=" * 72)
    print(f"wrote {out_dir}")


if __name__ == "__main__":
    main()
