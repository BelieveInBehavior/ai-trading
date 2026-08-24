#!/usr/bin/env python3
"""从已有 result.json 重建 T 日候选表（不必重扫全市场）。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from strategies.main_trend.engine import MainTrendConfig
from strategies.main_trend.event_logger import log_tday_pool
from strategies.main_trend.tday import rebuild_from_result


def _fmt(value, digits=2):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def print_table(pool: list) -> None:
    header = (
        f"{'股票':<8} {'代码':<8} {'Trend':<5} {'Sector':<6} {'Catalyst':<8} "
        f"{'Pre':>5} {'Ref':>8} {'InitStop':>8} {'主题':<8} {'主题仓':>6} {'状态':<6}"
    )
    print(header)
    print("-" * len(header))
    for row in pool:
        print(
            f"{str(row.get('symbol_name') or '')[:8]:<8} "
            f"{str(row.get('symbol_code') or ''):<8} "
            f"{str(row.get('trend_state') or ''):<5} "
            f"{str(row.get('sector_grade') or ''):<6} "
            f"{str(row.get('catalyst_grade') or ''):<8} "
            f"{_fmt(row.get('pre_score')):>5} "
            f"{_fmt(row.get('reference_price')):>8} "
            f"{_fmt(row.get('initial_stop')):>8} "
            f"{str(row.get('theme') or '')[:8]:<8} "
            f"{_fmt(row.get('suggested_position_pct')):>6} "
            f"{str(row.get('t1_state') or 'WAIT'):<6}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", default="agents_workspace_main_trend/20260821/result.json")
    args = parser.parse_args()
    path = Path(args.result).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    result = json.loads(path.read_text(encoding="utf-8"))
    cfg = MainTrendConfig.from_yaml()
    out = rebuild_from_result(result, scoring_cfg=cfg.scoring, holding_cfg=cfg.holding, portfolio_cfg=cfg.portfolio)
    dest_dir = path.parent
    (dest_dir / "tday_pool.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log_tday_pool(dest_dir, out.get("trade_date") or "", out.get("pool") or [], out.get("themes") or [])
    print(f"trade_date={out.get('trade_date')}  count={out.get('count')}  phase=tday  (全部 WAIT)")
    print()
    print("主题敞口")
    for theme in out.get("themes") or []:
        print(f"  {theme['theme']}: {theme['names']}只  原始{theme['gross_pct']}%  保留{theme['kept_pct']}%")
    print()
    print("T日候选池")
    print_table(out.get("pool") or [])


if __name__ == "__main__":
    main()
