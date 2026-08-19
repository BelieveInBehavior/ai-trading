r"""全市场行业成分抓取脚本（AkShare / 东财行业板块）。

用法：
    .venv/bin/python scripts/fetch_industry_map_akshare.py \
        --limit 5 \              # 只抓前5个行业，用于冒烟/sample
        --include-concept       # 可选：额外抓概念板块
        --out utils/cache/market_manager/industry_map.json

输出：
    { "600519.SH": "白酒", "300750.SZ": "电池", ... }

说明：
    - 优先使用 akshare_cached（按小时缓存）；
    - 抓取失败会记录 warning，不中断其他行业；
    - 最后与现有 industry_map 合并，避免覆盖历史手工映射。
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "utils" / "cache" / "market_manager" / "industry_map.json"

import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _norm_code(value) -> str:
    text = str(value or "").strip().upper()
    m = re.search(r"(\d{6})", text)
    if not m:
        return ""
    raw = m.group(1)
    if raw.startswith("6"):
        return f"{raw}.SH"
    if raw.startswith(("8", "4", "92")):
        return f"{raw}.BJ"
    return f"{raw}.SZ"


def _board_name(row) -> str:
    for col in ("板块名称", "名称", "name", "行业", "板块"):
        if col in row:
            return str(row[col]).strip()
    return ""


def _load_industry_names() -> list[str]:
    from utils.akshare_utils import akshare_cached

    try:
        df = akshare_cached.run("stock_board_industry_name_em", {}, verbose=False)
    except Exception as exc:
        logger.error("获取行业板块列表失败: {}", exc)
        raise

    if df is None or df.empty:
        raise RuntimeError("stock_board_industry_name_em 返回空")

    names = []
    for _, row in df.iterrows():
        name = _board_name(row)
        if name:
            names.append(name)
    logger.info("行业板块列表: {} 个", len(names))
    return names


def _fetch_board_cons(board_name: str) -> list[str]:
    from utils.akshare_utils import akshare_cached

    try:
        df = akshare_cached.run("stock_board_industry_cons_em", {"symbol": board_name}, verbose=False)
    except Exception as exc:
        logger.warning("获取行业 [{}] 成分股失败: {}", board_name, exc)
        return []

    if df is None or df.empty:
        logger.warning("行业 [{}] 成分股为空", board_name)
        return []

    codes = []
    # typical akshare cons columns: 代码, 名称, 最新价, 涨跌幅 ...
    for col in ("代码", "code", "股票代码"):
        if col in df.columns:
            codes = [_norm_code(c) for c in df[col]]
            break
    if not codes:
        logger.warning("行业 [{}] 未找到代码列: {}", board_name, list(df.columns))
        return []
    return [c for c in codes if c]


def _load_existing(out_path: Path) -> dict:
    if not out_path.exists():
        return {}
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("读取已有 industry_map 失败: {}", exc)
        return {}


def build_industry_map(limit: Optional[int] = None, sleep: float = 0.3) -> dict:
    names = _load_industry_names()
    if limit and limit > 0:
        names = names[:limit]

    mapping: dict[str, str] = {}
    for idx, name in enumerate(names, 1):
        codes = _fetch_board_cons(name)
        for code in codes:
            mapping[code] = name
        if idx % 20 == 0 or idx == len(names):
            logger.info("进度: {}/{} 行业", idx, len(names))
        time.sleep(sleep)

    logger.info("AkShare 行业成分抓取完成: {} 只股票", len(mapping))
    return mapping


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=str, default=str(DEFAULT_OUT))
    ap.add_argument("--sleep", type=float, default=0.3)
    args = ap.parse_args()

    out_path = Path(args.out)
    try:
        new_map = build_industry_map(limit=args.limit, sleep=args.sleep)
    except Exception as exc:
        logger.error("行业成分抓取失败，保留原映射不变: {}", exc)
        return 1
    old_map = _load_existing(out_path)
    merged = dict(old_map)
    updated = 0
    for code, industry in new_map.items():
        if merged.get(code) != industry:
            merged[code] = industry
            updated += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("写入 {} 条映射，新增/更新 {} 只", len(merged), updated)


if __name__ == "__main__":
    main()

