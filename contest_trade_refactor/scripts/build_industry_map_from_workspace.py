"""从现有 agents_workspace 的 trade_decisions / data reports 中提取“股票 → 行业/板块”映射。

不需要 Tushare。利用 Research Agent 证据里的板块描述，例如：
    "XX板块涨3.99%，YY作为龙头直接受益"
将板块名与当前股票关联，投票生成 industry_map.json，供 sector_enrichment 使用。

输出：utils/cache/market_manager/industry_map.json
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "utils" / "cache" / "market_manager" / "industry_map.json"

# 板块/行业候选词后面的后缀
_SECTOR_SUFFIX = re.compile(r"([\u4e00-\u9fa5A-Za-z0-9（）()]+?)(?:板块|概念|行业)")
_STOCK_CODE = re.compile(r"(\d{6}(?:\.(?:SH|SZ|BJ))?)")


def _iter_signal_sections(obj):
    """Yield tuples (symbol_code, symbol_name, list_of_evidence_text)."""
    if isinstance(obj, dict):
        for key in ("research_signals", "consensus_signals", "buy_signals", "watchlist", "best_signals"):
            val = obj.get(key)
            if isinstance(val, list):
                for item in val:
                    if not isinstance(item, dict):
                        continue
                    code = str(item.get("symbol_code") or item.get("symbol") or "").strip()
                    name = str(item.get("symbol_name") or item.get("name") or "").strip()
                    if not code and not name:
                        continue
                    evidence_texts = []
                    for ev in (item.get("evidence_list") or []):
                        text = " ".join(
                            str(ev.get("description") or "")
                            for ev in [ev] if isinstance(ev, dict)
                        )
                        evidence_texts.append(text)
                    # limitations may also name sectors
                    for lim in (item.get("limitations") or []):
                        evidence_texts.append(str(lim))
                    yield code, name, evidence_texts
        # quantitative candidates contain symbol_code/symbol_name but no sector text
        qc = obj.get("quantitative_candidates")
        if isinstance(qc, list):
            for item in qc:
                if isinstance(item, dict):
                    yield str(item.get("symbol_code") or "").strip(), str(item.get("symbol_name") or "").strip(), []


def extract_sector_mentions(text: str):
    return [m.group(1).strip() for m in _SECTOR_SUFFIX.finditer(text) if m.group(1).strip()]


def _load_known_sector_names() -> set[str]:
    known = set()
    for csv_path in (ROOT / "agents_workspace" / "factor_store" / "sector_fund_flow").glob("*.csv"):
        try:
            import pandas as pd
            df = pd.read_csv(csv_path)
            if "symbol_code" in df.columns:
                known.update(str(x).strip() for x in df["symbol_code"].dropna() if str(x).strip())
        except Exception as exc:
            logger.warning("加载 known sectors csv 失败 {}: {}", csv_path, exc)
    return known


def _resolve_sector(mention: str, known: set[str]) -> str | None:
    if not mention:
        return None
    # Longest known sector contained in mention wins
    candidates = [k for k in known if k and k in mention]
    if not candidates:
        return None
    return max(candidates, key=len)


def build_mapping() -> dict[str, str]:
    all_files = sorted((ROOT / "agents_workspace" / "results" / "trade_decisions").glob("*.json"))
    known_sectors = _load_known_sector_names()
    if not all_files:
        logger.warning("未发现 trade_decisions")
        return {}

    votes: dict[str, Counter] = defaultdict(Counter)  # symbol_code -> Counter(sector)
    name_by_code: dict[str, str] = {}
    for path in all_files:
        try:
            obj = json.load(open(path, encoding="utf-8"))
        except Exception as exc:
            logger.warning("读取失败 {}: {}", path, exc)
            continue
        for code, name, evidence_texts in _iter_signal_sections(obj):
            code = _normalize_symbol(code)
            if not code:
                continue
            if name:
                name_by_code[code] = name
            # only use sector mentions from sector_fund_flow_trend_agent-like or where text contains 板块
            for text in evidence_texts:
                if ("板块" not in text and "行业" not in text) or ("主力" not in text and "净流入" not in text and "涨" not in text):
                    continue
                # 如果文本里明确出现股票名，才更可靠；但 sector agent evidence 本身就代表该股票。
                for raw in extract_sector_mentions(text):
                    sector = _resolve_sector(raw, known_sectors)
                    if sector and sector != name:
                        votes[code][sector] += 1

    mapping = {}
    for code, counter in votes.items():
        if not counter:
            continue
        top, count = counter.most_common(1)[0]
        # 可以要求至少出现 1 次
        if count >= 1:
            mapping[code] = top

    logger.info("提取到 {} 只股票的行业/板块映射", len(mapping))
    return mapping


def _normalize_symbol(code: str) -> str:
    code = str(code or "").strip().upper()
    if not code:
        return ""
    m = _STOCK_CODE.search(code)
    if not m:
        return ""
    raw = m.group(1)
    if "." in raw:
        return raw
    if raw.startswith("6"):
        return f"{raw}.SH"
    if raw.startswith(("8", "4", "92")):
        return f"{raw}.BJ"
    return f"{raw}.SZ"


def main() -> None:
    mapping = build_mapping()
    if not mapping:
        logger.error("没有生成任何映射，请确认 agents_workspace/results/trade_decisions 存在且包含 evidence 中的板块词。")
        sys.exit(1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {OUT}")
    for i, (k, v) in enumerate(mapping.items()):
        if i >= 30:
            print("...")
            break
        print(k, v)


if __name__ == "__main__":
    main()
