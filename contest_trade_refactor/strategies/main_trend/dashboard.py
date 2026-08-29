"""主升浪 Dashboard / 持仓状态聚合。

职责：
  - 读取 T 日候选、T+1 执行、持仓状态、退出决策
  - 生成给前端 /api/main_trend/dashboard 的汇总 JSON
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from strategies.main_trend.holdings import compute_display_status


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        v = float(value)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def _json_load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def find_latest_dir(base: Path, key: str = "tday_pool.json") -> Optional[Path]:
    if not base.exists():
        return None
    dirs = []
    for d in base.iterdir():
        if not d.is_dir():
            continue
        if (d / key).exists() or (d / "tday_pool.json").exists():
            dirs.append(d)
    if not dirs:
        return None
    def sort_key(p: Path):
        try:
            return p.name.replace("-", "").replace("/", "")
        except Exception:
            return p.name
    return sorted(dirs, key=sort_key, reverse=True)[0]


def latest_tday_payload(base: Path) -> Dict[str, Any]:
    day = _find_latest_with_file(base, "tday_pool.json")
    if not day:
        return {"present": False}
    data = _json_load(day / "tday_pool.json", {}) or {}
    return {
        "present": True,
        "trade_date": data.get("trade_date") or day.name,
        "count": data.get("count") or len(data.get("pool") or []),
        "rows": data.get("pool") or [],
        "themes": data.get("themes") or [],
        "phase": data.get("phase", "tday"),
        "path": str(day / "tday_pool.json"),
    }


def latest_t1_payload(base: Path) -> Dict[str, Any]:
    day = _find_latest_with_file(base, "t1_execution.json")
    if not day:
        return {"present": False}
    data = _json_load(day / "t1_execution.json", {}) or {}
    return {
        "present": True,
        "trade_date": data.get("trade_date") or day.name,
        "rows": data.get("rows") or [],
        "index_change_pct": data.get("index_change_pct"),
        "phase": data.get("phase", "t1"),
        "path": str(day / "t1_execution.json"),
    }


def _enrich_holding_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """确保每条持仓带有与 exit 字段一致的 display_status。"""
    out = []
    for r in rows or []:
        row = dict(r)
        row["display_status"] = compute_display_status(row)
        out.append(row)
    return out


def latest_holdings_payload(base: Path) -> Dict[str, Any]:
    day = _find_latest_with_file(base, "holdings.json")
    if not day:
        return {"present": False}
    data = _json_load(day / "holdings.json", {}) or {}
    rows = _enrich_holding_rows(data.get("holdings") or [])
    return {
        "present": True,
        "trade_date": data.get("as_of_date") or day.name,
        "rows": rows,
        "holdings": rows,
        "count": data.get("count") or len(data.get("holdings") or []),
        "last_run": data.get("last_run") or "",
        "path": str(day / "holdings.json"),
    }


def latest_exit_payload(base: Path) -> Dict[str, Any]:
    day = _find_latest_with_file(base, "exit_decisions.json")
    if not day:
        return {"present": False}
    data = _json_load(day / "exit_decisions.json", {}) or {}
    return {
        "present": True,
        "as_of_date": data.get("as_of_date") or day.name,
        "positions_count": data.get("positions_count") or 0,
        "decisions": data.get("decisions") or [],
        "path": str(day / "exit_decisions.json"),
    }


def _find_latest_with_file(base: Path, filename: str) -> Optional[Path]:
    if not base.exists():
        return None
    day_dirs = []
    for d in base.iterdir():
        if d.is_dir() and (d / filename).exists():
            day_dirs.append(d)
    if not day_dirs:
        return None
    def sort_key(p: Path):
        try:
            return p.name.replace("-", "").replace("/", "")
        except Exception:
            return p.name
    return sorted(day_dirs, key=sort_key, reverse=True)[0]


def list_day_dirs(base: Path) -> List[str]:
    """返回 agents_workspace_main_trend 下所有日期目录名（倒序）。"""
    if not base.exists():
        return []
    dirs = []
    for d in base.iterdir():
        if d.is_dir() and len(d.name.replace("-", "")) == 8:
            dirs.append(d.name)
    def sort_key(name: str):
        return name.replace("-", "").replace("/", "")
    return sorted(dirs, key=sort_key, reverse=True)


def _payload_for_date(base: Path, key: str, filename: str, kind: str) -> Dict[str, Any]:
    """读取指定日期目录下的具体文件，若缺失则返回 present=False。"""
    day = base / key
    if not day.is_dir():
        return {"present": False}
    path = day / filename
    if not path.exists():
        return {"present": False}
    data = _json_load(path, {}) or {}
    if kind == "tday":
        return {
            "present": True,
            "trade_date": data.get("trade_date") or day.name,
            "count": data.get("count") or len(data.get("pool") or []),
            "rows": data.get("pool") or [],
            "themes": data.get("themes") or [],
            "phase": data.get("phase", "tday"),
            "path": str(path),
        }
    if kind == "t1":
        return {
            "present": True,
            "trade_date": data.get("trade_date") or day.name,
            "rows": data.get("rows") or [],
            "index_change_pct": data.get("index_change_pct"),
            "phase": data.get("phase", "t1"),
            "path": str(path),
        }
    if kind == "holdings":
        rows = _enrich_holding_rows(data.get("holdings") or [])
        return {
            "present": True,
            "trade_date": data.get("as_of_date") or day.name,
            "rows": rows,
            "holdings": rows,
            "count": data.get("count") or len(data.get("holdings") or []),
            "last_run": data.get("last_run") or "",
            "path": str(path),
        }
    if kind == "exit":
        return {
            "present": True,
            "as_of_date": data.get("as_of_date") or day.name,
            "positions_count": data.get("positions_count") or 0,
            "decisions": data.get("decisions") or [],
            "path": str(path),
        }
    return {"present": False}


def _t2_latest(base: Path, key: str) -> Dict[str, Any]:
    latest = _json_load(base / key / "t2" / "latest.json", {}) or {}
    path = latest.get("path")
    if not path:
        return {}
    t2_dir = Path(path)
    if not t2_dir.is_dir():
        return {}
    latest["dir"] = t2_dir
    return latest


def _apply_t2_override(base: Path, key: str, holdings: Dict[str, Any], exits: Dict[str, Any]) -> tuple:
    """若该日已有 T+2 快照，页面持仓/退出改读 T2，不覆盖原 holdings.json。"""
    latest = _t2_latest(base, key)
    t2_dir = latest.get("dir")
    if not t2_dir:
        return holdings, exits, latest
    hp = t2_dir / "holdings.json"
    ep = t2_dir / "exit_decisions.json"
    if hp.exists():
        data = _json_load(hp, {}) or {}
        rows = _enrich_holding_rows(data.get("holdings") or [])
        holdings = {
            "present": True,
            "trade_date": data.get("as_of_date") or key,
            "rows": rows,
            "holdings": rows,
            "count": data.get("count") or len(rows),
            "last_run": data.get("last_run") or latest.get("logged_at") or "",
            "path": str(hp),
            "phase": "t2",
            "wave": data.get("wave") or latest.get("wave") or "",
        }
    if ep.exists():
        data = _json_load(ep, {}) or {}
        exits = {
            "present": True,
            "as_of_date": data.get("as_of_date") or key,
            "positions_count": data.get("positions_count") or 0,
            "decisions": data.get("decisions") or [],
            "path": str(ep),
            "phase": "t2",
            "wave": data.get("wave") or latest.get("wave") or "",
        }
    return holdings, exits, latest


def build_dashboard(base: Path, date: str = "") -> Dict[str, Any]:
    dates = list_day_dirs(base)
    if date:
        key = str(date).replace("-", "").replace("/", "")
        if key in dates:
            tday = _payload_for_date(base, key, "tday_pool.json", "tday")
            t1 = _payload_for_date(base, key, "t1_execution.json", "t1")
            holdings = _payload_for_date(base, key, "holdings.json", "holdings")
            exits = _payload_for_date(base, key, "exit_decisions.json", "exit")
            holdings, exits, t2 = _apply_t2_override(base, key, holdings, exits)
            date_val = holdings.get("trade_date") or t1.get("trade_date") or tday.get("trade_date") or key
            return {
                "as_of_date": date_val,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "tday_candidates": tday,
                "t1_execution": t1,
                "holdings": holdings,
                "exit_decisions": exits,
                "t2": {
                    "present": bool(t2.get("path")),
                    "wave": t2.get("wave") or "",
                    "logged_at": t2.get("logged_at") or "",
                    "avg_return_pct": t2.get("avg_return_pct"),
                    "counts": t2.get("counts") or {},
                    "path": t2.get("path") or "",
                },
                "available_dates": dates,
                "requested_date": key,
                "requested_day_present": True,
            }
        # 指定日期无目录：仍返回最新 + requested false
        return {
            **build_dashboard(base, date=""),
            "available_dates": dates,
            "requested_date": key,
            "requested_day_present": False,
        }

    if dates:
        # 「最新」= 日期目录中最新的一天（如 20260825 T 日候选），避免 tday/holdings 来自不同目录
        return build_dashboard(base, date=dates[0])

    return {
        "as_of_date": "",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tday_candidates": {"present": False},
        "t1_execution": {"present": False},
        "holdings": {"present": False},
        "exit_decisions": {"present": False},
        "available_dates": dates,
    }
