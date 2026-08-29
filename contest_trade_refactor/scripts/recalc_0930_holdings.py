#!/usr/bin/env python3
"""用收盘快照 + 当日技术面，按新 ADD/退出逻辑重算 9:30 买入持仓。"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_source.technical_indicators_akshare import compute_stock_technical_factor
from scripts.main_trend_holdings import resolve_holdings_from_rows
from strategies.main_trend.engine import MainTrendConfig, MainTrendEngine
from strategies.main_trend.event_logger import log_event
from strategies.main_trend.holdings import update_holdings

BASE = PROJECT_ROOT / "agents_workspace_main_trend"
TRADE_DATE = "20260824"
WRITE_DATES = ("20260824", "20260823")

THEME_ALIASES = {
    "贵金属": ["贵金属"],
    "航运物流": ["港口航运"],
    "航运": ["港口航运"],
    "银行": ["银行"],
    "煤炭": ["煤炭开采加工"],
    "有色": ["工业金属"],
    "有色金属": ["工业金属"],
    "电力设备": ["其他电源设备", "电网设备"],
    "石化": ["油服工程", "石油加工贸易"],
    "石化化工": ["石油加工贸易", "化学制品"],
    "建筑": ["专业工程", "装修建材", "房屋建设"],
    "建筑装饰": ["专业工程", "装修建材"],
    "医药": ["生物制品", "化学制药"],
    "其他电源设备": ["其他电源设备"],
    "自动化设备": ["自动化设备"],
    "半导体": ["半导体"],
}

NAME_BOARD = {
    "西部黄金": "贵金属",
    "招金黄金": "贵金属",
    "山金国际": "贵金属",
    "中金黄金": "贵金属",
    "赤峰黄金": "贵金属",
    "锦江航运": "港口航运",
    "中谷物流": "港口航运",
    "兴通股份": "港口航运",
    "中远海控": "港口航运",
    "盛航股份": "港口航运",
    "渝农商行": "银行",
    "成都银行": "银行",
    "齐鲁银行": "银行",
    "华阳股份": "煤炭开采加工",
    "中国神华": "煤炭开采加工",
    "淮北矿业": "煤炭开采加工",
    "海油工程": "油服工程",
    "中远通": "其他电源设备",
    "晓程科技": "电网设备",
    "华达新材": "工业金属",
    "江河集团": "专业工程",
    "康希诺": "生物制品",
}


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


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_tday_meta() -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    for date in WRITE_DATES:
        path = BASE / date / "tday_pool.json"
        if not path.exists():
            continue
        data = load_json(path)
        for row in data.get("pool") or []:
            code = str(row.get("symbol_code") or "").zfill(6)
            out[code] = {
                "theme": str(row.get("theme") or ""),
                "sector_name": str(row.get("sector_name") or ""),
            }
    return out


def board_lookup() -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    market = load_json(BASE / TRADE_DATE / "market_20260824.json")
    ranked: List[Tuple[str, float]] = []
    seen = set()
    for key in ("sector_top_up", "sector_top_down", "sector_inflow", "sector_outflow"):
        for row in market.get(key) or []:
            name = str(row.get("name") or "")
            chg = _num(row.get("change_pct"))
            if not name or chg is None or name in seen:
                continue
            seen.add(name)
            ranked.append((name, chg))
    try:
        from utils.sector_flow_provider import get_industry_board_data

        df = get_industry_board_data(trade_date=TRADE_DATE, require_flow=False)
        if df is not None and not df.empty:
            name_col = "板块名称" if "板块名称" in df.columns else None
            chg_col = "涨跌幅" if "涨跌幅" in df.columns else None
            if name_col and chg_col:
                ranked = []
                seen = set()
                for _, row in df.iterrows():
                    name = str(row.get(name_col) or "").strip()
                    chg = _num(row.get(chg_col))
                    if not name or chg is None or name in seen:
                        continue
                    seen.add(name)
                    ranked.append((name, chg))
    except Exception as exc:
        print(f"industry board fetch failed, using market snapshot: {exc}")

    ranked.sort(key=lambda x: x[1], reverse=True)
    for i, (name, chg) in enumerate(ranked, start=1):
        lookup[name] = {"change_pct": chg, "rank": i, "count": len(ranked)}
    print(f"sector board rows={len(lookup)}")
    return lookup


def resolve_board(name: str, theme: str, sector_name: str, lookup: Dict[str, Dict[str, Any]]) -> Tuple[str, Optional[Dict[str, Any]]]:
    candidates = []
    if NAME_BOARD.get(name):
        candidates.append(NAME_BOARD[name])
    if sector_name:
        candidates.append(sector_name)
        candidates.extend(THEME_ALIASES.get(sector_name) or [])
    if theme:
        candidates.append(theme)
        candidates.extend(THEME_ALIASES.get(theme) or [])
    for cand in candidates:
        if cand in lookup:
            return cand, lookup[cand]
    return "", None


def fetch_factor(code: str, name: str) -> Optional[Dict[str, Any]]:
    try:
        return compute_stock_technical_factor(code, name, TRADE_DATE, ma_mode="ema")
    except Exception as exc:
        print(f"factor fail {code} {name}: {exc}")
        return None


def enrich_rows(
    rows: List[Dict[str, Any]],
    close_names: Dict[str, Any],
    tday_meta: Dict[str, Dict[str, str]],
    lookup: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    factors: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {
            pool.submit(fetch_factor, str(r.get("symbol_code") or ""), str(r.get("symbol_name") or "")): r
            for r in rows
        }
        for fut in as_completed(futs):
            row = futs[fut]
            code = str(row.get("symbol_code") or "")
            fac = fut.result()
            if fac:
                factors[code] = fac
                print(f"factor ok {code} {row.get('symbol_name')} rs={fac.get('relative_strength_score')} vol={fac.get('volume_ratio')} ma20={fac.get('ma20')}")
            else:
                print(f"factor missing {code} {row.get('symbol_name')}")

    enriched = []
    for row in rows:
        item = dict(row)
        code = str(item.get("symbol_code") or "")
        name = str(item.get("symbol_name") or "")
        snap = close_names.get(code) or close_names.get(code.zfill(6)) or {}
        fac = factors.get(code) or {}
        meta = tday_meta.get(code) or tday_meta.get(code.zfill(6)) or {}
        board_name, board = resolve_board(name, meta.get("theme") or "", meta.get("sector_name") or "", lookup)

        close_px = _num(snap.get("price")) or _num(item.get("current_price"))
        high_px = _num(snap.get("high"))
        if close_px is not None:
            item["current_price"] = close_px
        if high_px is not None:
            item["highest_price"] = max(_num(item.get("highest_price")) or 0.0, high_px)
            item["highest_close"] = max(_num(item.get("highest_close")) or 0.0, close_px or 0.0)
        if _num(snap.get("prev_close")) is not None:
            item["prev_close"] = _num(snap.get("prev_close"))

        ma20 = _num(fac.get("ma20"))
        if ma20 is not None:
            item["ma20"] = ma20

        tp = dict(item.get("trade_plan") or {})
        tp["suggested_position_pct"] = item.get("suggested_position_pct") or tp.get("suggested_position_pct")
        for key in (
            "ma20",
            "volume_ratio",
            "relative_strength_score",
            "relative_strength_20d_pct",
            "relative_strength_60d_pct",
            "relative_strength_cross_section_pct",
            "close_vs_20d_high_pct",
            "close_vs_60d_high_pct",
            "breakout_20d",
            "breakout_60d",
            "ret_5d_pct",
            "ret_20d_pct",
            "atr",
            "atr_pct",
            "close",
            "prev_close",
        ):
            val = fac.get(key)
            if val is not None:
                tp[key] = val
        if close_px is not None:
            tp["close"] = close_px
        if item.get("prev_close") is not None:
            tp["prev_close"] = item["prev_close"]
        if board:
            tp["sector_name"] = board_name
            tp["sector_1d_return"] = board["change_pct"]
            tp["sector_rank"] = board["rank"]
        elif board_name:
            tp["sector_name"] = board_name
        item["trade_plan"] = tp

        rt = dict(item.get("realtime_quote") or {})
        for key in ("open", "high", "low", "vwap", "vwap_state", "bid_support"):
            if snap.get(key) is not None:
                rt[key] = snap.get(key)
        if close_px is not None:
            rt["price"] = close_px
        if _num(rt.get("vwap")) and close_px is not None:
            rt["vwap_state"] = "Above" if close_px >= float(rt["vwap"]) else "Below"
        for key in (
            "volume_ratio",
            "atr",
            "atr_pct",
            "breakout_20d",
            "close_vs_20d_high_pct",
            "close_vs_60d_high_pct",
            "relative_strength_score",
            "relative_strength_20d_pct",
            "relative_strength_60d_pct",
        ):
            if fac.get(key) is not None:
                rt[key] = fac.get(key)
        if board:
            rt["sector_1d_return"] = board["change_pct"]
            rt["sector_rank"] = board["rank"]
        item["realtime_quote"] = rt
        item["theme"] = meta.get("theme") or item.get("theme") or ""
        item["sector_name"] = board_name or meta.get("sector_name") or ""
        enriched.append(item)
    return enriched


def main() -> None:
    holdings_path = BASE / TRADE_DATE / "holdings.json"
    close_path = PROJECT_ROOT / "config" / "manual_execution_20260824_close.json"
    holdings = load_json(holdings_path)
    close_snap = load_json(close_path)
    lookup = board_lookup()
    tday_meta = load_tday_meta()
    rows = enrich_rows(holdings.get("holdings") or [], close_snap.get("names") or {}, tday_meta, lookup)
    holdings["holdings"] = rows
    holdings["count"] = len(rows)

    engine = MainTrendEngine(MainTrendConfig.from_yaml())
    decisions = [d.to_dict() for d in engine.evaluate_exits(resolve_holdings_from_rows(rows, TRADE_DATE), refresh_factors=True, trade_date=TRADE_DATE)]
    decisions.sort(
        key=lambda x: (x.get("action") in ("sell", "exit", "reduce", "add"), x.get("exit_score") or 0),
        reverse=True,
    )
    exit_payload = {
        "as_of_date": TRADE_DATE,
        "positions_count": len(decisions),
        "wave": "0930",
        "logic": "add_setup_confirmation_sector_rs",
        "decisions": decisions,
    }
    merged = update_holdings(holdings, decisions, TRADE_DATE)

    counts: Dict[str, int] = {}
    print("=" * 72)
    for d in decisions:
        status = "HOLD"
        action = str(d.get("action") or "")
        pos = str(d.get("state") or d.get("position_state") or "")
        exit_class = str(d.get("exit_class") or "")
        if exit_class.startswith("SELL") or action in ("sell", "exit") or pos == "EXIT":
            status = "SELL"
        elif exit_class == "REDUCE" or action == "reduce" or pos == "REDUCE":
            status = "REDUCE"
        elif pos == "ADD" or action == "add":
            status = "ADD"
        counts[status] = counts.get(status, 0) + 1
        print(
            f"{status:6} {d.get('symbol_name')}({d.get('symbol_code')}) "
            f"ret={d.get('current_return_pct'):+.2f}% setup={d.get('add_setup_class') or '-'} "
            f"conf={d.get('add_confirmation')} sector={d.get('sector_source')} rs={d.get('rs_source')} | {d.get('reason')}"
        )
    print("=" * 72)
    print("status counts", counts)

    for date in WRITE_DATES:
        day_dir = BASE / date
        write_json(day_dir / "holdings.json", {**merged, "as_of_date": date})
        write_json(day_dir / "exit_decisions.json", {**exit_payload, "as_of_date": date})
        log_event(day_dir, {"event": "holdings_recalc_0930", "date": date, "counts": counts})
        print(f"wrote {day_dir / 'holdings.json'} and exit_decisions.json")


if __name__ == "__main__":
    main()
