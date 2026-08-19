#!/usr/bin/env python3
"""
策略级统一回测 / 对比入口。

同一套回测引擎，不同策略通过自己的策略包 strategies/<name>/ 声明默认回测参数。
默认读取已有 replay 的 backtest_results/signal_performance.csv 生成对比；
加上 --run-replay 可对指定区间重新跑 replay（复用 replay_historical_no_future.py）。

用法:
  .venv/bin/python scripts/strategy_backtest.py --strategy momentum
  .venv/bin/python scripts/strategy_backtest.py --strategies momentum,swing --compare
  .venv/bin/python scripts/strategy_backtest.py --strategy momentum --run-replay \
      --start 2026-06-01 --end 2026-08-18 --output-root agents_workspace_strategies
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.strategies import get_strategy, get_strategies


def _compact(value: Any) -> str:
    return str(value or "").strip().replace("-", "").replace("/", "")[:8]


def _history(cfg: dict, start: str, end: str) -> Tuple[str, str]:
    bt = cfg.get("backtest") or {}
    s = _compact(start or bt.get("default_start") or "2026-06-01")
    e = _compact(end or bt.get("default_end") or "2026-08-18")
    return s, e


def _symbols_limit(cfg: dict, cli: Optional[int]) -> int:
    if cli is not None:
        return int(cli)
    return int((cfg.get("backtest") or {}).get("symbols_limit") or 0)


def _concurrency(cfg: dict, cli: Optional[int]) -> int:
    if cli is not None:
        return int(cli)
    return int((cfg.get("backtest") or {}).get("concurrency") or 4)


def _horizons(cfg: dict) -> Tuple[int, ...]:
    bt = cfg.get("backtest") or {}
    raw = bt.get("horizons") or (1, 3, 5)
    if isinstance(raw, str):
        return tuple(int(x) for x in raw.split(",") if str(x).strip().isdigit())
    return tuple(int(x) for x in raw)


def resolve_strategy_names() -> list[str]:
    return [s["id"] for s in get_strategies()]


def _collect_signal_csvs(workspace: Path) -> List[Path]:
    if not workspace.exists():
        return []
    return sorted(workspace.glob("**/backtest_results/signal_performance.csv"))


def _discover_existing_signal_frames(strategy: str) -> List[Path]:
    """扩展现有 replay/backtest 工作区中该策略的 signal_performance.csv。"""
    roots = [PROJECT_ROOT / "agents_workspace_replays", PROJECT_ROOT / "agents_workspace"]
    out: List[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for cs in root.rglob("backtest_results/signal_performance.csv"):
            if strategy in str(cs).lower() and cs not in out:
                out.append(cs)
    # 兜底兜：包含 strategy 列的 CSV 也可作为候选，后续按列过滤。
    for root in roots:
        if not root.exists():
            continue
        for cs in root.rglob("backtest_results/signal_performance.csv"):
            if cs in out:
                continue
            try:
                with open(cs, "r", encoding="utf-8") as f:
                    header = f.readline()
                if "strategy" in header:
                    out.append(cs)
            except Exception:
                continue
    generic = PROJECT_ROOT / "agents_workspace" / "backtest_results" / "signal_performance.csv"
    if generic.exists() and generic not in out:
        out.append(generic)
    return out


def _load_signal_frame(workspace: Path) -> pd.DataFrame:
    frames = []
    for p in _collect_signal_csvs(workspace):
        try:
            df = pd.read_csv(p)
        except Exception:
            continue
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _metrics(strategy: str, workspace: Path, horizons: Tuple[int, ...]) -> Dict[str, Any]:
    df = _load_signal_frame(workspace)
    if df.empty:
        discovered = _discover_existing_signal_frames(strategy)
        frames = []
        for path in discovered:
            try:
                d = pd.read_csv(path)
            except Exception:
                continue
            if d.empty:
                continue
            if "strategy" in d.columns:
                d = d[d["strategy"].astype(str).str.lower() == strategy.lower()]
            if not d.empty:
                frames.append(d)
        if frames:
            df = pd.concat(frames, ignore_index=True)
            workspace = Path("discovered:" + ",".join(str(p) for p in discovered))
    out: Dict[str, Any] = {
        "strategy": strategy,
        "workspace": str(workspace),
        "rows": int(len(df)),
        "buy_signals": 0,
    }
    if df.empty:
        return out
    if "signal_group" in df.columns:
        out["buy_signals"] = int((df["signal_group"] == "buy_passed").sum())
    if "trigger_date" in df.columns:
        dates = sorted([str(x)[:8] for x in df["trigger_date"].dropna()])
        out["start_date"] = dates[0] if dates else None
        out["end_date"] = dates[-1] if dates else None
    for h in horizons:
        col = f"t{h}_return_pct"
        if col not in df.columns:
            continue
        vals = df[col].dropna()
        if vals.empty:
            continue
        out[f"t{h}_n"] = int(len(vals))
        out[f"t{h}_avg_pct"] = round(float(vals.mean()), 4)
        out[f"t{h}_win_rate_pct"] = round(float((vals > 0).mean()) * 100.0, 2)
        out[f"t{h}_median_pct"] = round(float(vals.median()), 4)
        out[f"t{h}_best_pct"] = round(float(vals.max()), 4)
        out[f"t{h}_worst_pct"] = round(float(vals.min()), 4)
    if "max_drawdown_pct" in df.columns:
        out["avg_max_drawdown_pct"] = round(float(df["max_drawdown_pct"].mean()), 4)
    if "trade_plan_pass" in df.columns:
        out["trade_plan_pass_rate_pct"] = round(float(df["trade_plan_pass"].fillna(False).mean()) * 100.0, 2)
    return out


def _run_replay_with_subprocess(strategy: str, start_compact: str, end_compact: str,
                                symbols_limit: int, concurrency: int, output_dir: Path) -> None:
    """调用 replay_historical_no_future.py 主入口，避免其 subprocess 内部 sys.path 副作用。"""
    script = PROJECT_ROOT / "scripts" / "replay_historical_no_future.py"
    vpy = PROJECT_ROOT / ".venv" / "bin" / "python"
    cmd = [
        str(vpy if vpy.exists() else sys.executable),
        "-u",
        str(script),
        "--strategy", strategy,
        "--start-date", _fmt_compact(start_compact),
        "--end-date", _fmt_compact(end_compact),
        "--output-dir", str(output_dir),
        "--symbols-limit", str(symbols_limit),
        "--concurrency", str(concurrency),
    ]
    print(f"[replay] {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True, env=os.environ.copy())


def _fmt_compact(value: str) -> str:
    value = _compact(value)
    if len(value) != 8:
        return value
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def _write_compare_metrics(metrics: List[Dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "strategy_metrics.csv"
    pd.DataFrame(metrics).to_csv(out, index=False)
    return out


def _write_markdown(metrics: List[Dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Strategy Backtest Comparison",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "| strategy | rows | buy_signals | t1_avg | t3_avg | t5_avg | t1_win | t3_win | t5_win | avg_max_dd |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in metrics:
        lines.append(
            f"| {m.get('strategy','')} | {m.get('rows','')} | {m.get('buy_signals','')} "
            f"| {m.get('t1_avg_pct','')} | {m.get('t3_avg_pct','')} | {m.get('t5_avg_pct','')} "
            f"| {m.get('t1_win_rate_pct','')} | {m.get('t3_win_rate_pct','')} | {m.get('t5_win_rate_pct','')} "
            f"| {m.get('avg_max_drawdown_pct','')} |"
        )
    out = output_dir / "strategy_comparison.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", default=None)
    parser.add_argument("--strategies", default="")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--symbols-limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--output-root", default="agents_workspace_strategies")
    parser.add_argument("--run-replay", action="store_true")
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args()

    targets: List[str] = []
    if args.strategy:
        targets.append(args.strategy)
    if args.strategies:
        targets.extend([x.strip() for x in args.strategies.split(",") if x.strip()])
    if not targets:
        targets = resolve_strategy_names()
    if not targets:
        print("No strategies passed and none discovered.", file=sys.stderr)
        sys.exit(1)

    output_root = Path(args.output_root).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)

    metrics: List[Dict[str, Any]] = []
    for name in targets:
        try:
            cfg = get_strategy(name)
        except Exception as exc:
            print(f"[error] load strategy {name}: {exc}", file=sys.stderr)
            continue
        hz = _horizons(cfg)
        sl = _symbols_limit(cfg, args.symbols_limit)
        cc = _concurrency(cfg, args.concurrency)
        workspace = output_root / name
        if args.run_replay:
            s, e = _history(cfg, args.start, args.end)
            _run_replay_with_subprocess(name, s, e, sl, cc, workspace)
        m = _metrics(name, workspace, hz)
        metrics.append(m)
        print(json.dumps(m, ensure_ascii=False), flush=True)

    if not metrics:
        print("No metrics collected.", file=sys.stderr)
        sys.exit(1)

    reports = output_root / "reports"
    csv_path = _write_compare_metrics(metrics, reports)
    md_path = _write_markdown(metrics, reports)
    print(f"[result] {csv_path}")
    print(f"[result] {md_path}")
    if args.compare:
        print(md_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
