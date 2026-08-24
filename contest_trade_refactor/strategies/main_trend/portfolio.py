"""Portfolio / Theme Exposure：防止 15 只股票实际只暴露 3 个主题。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List


# 东财二级板块 -> 组合主题（粗粒度风险桶）
BOARD_TO_THEME: Dict[str, str] = {
    "贵金属": "贵金属",
    "小金属": "有色金属",
    "工业金属": "有色金属",
    "能源金属": "有色金属",
    "金属新材料": "有色金属",
    "港口航运": "航运物流",
    "机场航运": "航运物流",
    "公路铁路运输": "航运物流",
    "物流": "航运物流",
    "石油加工贸易": "石化化工",
    "油气开采及服务": "石化化工",
    "化学制品": "石化化工",
    "化学原料": "石化化工",
    "化学纤维": "石化化工",
    "农化制品": "石化化工",
    "塑料制品": "石化化工",
    "煤炭开采加工": "煤炭",
    "银行": "银行",
    "证券": "非银金融",
    "保险": "非银金融",
    "多元金融": "非银金融",
    "半导体": "半导体",
    "消费电子": "电子",
    "光学光电子": "电子",
    "元件": "电子",
    "其他电子": "电子",
    "生物制品": "医药",
    "化学制药": "医药",
    "中药": "医药",
    "医疗器械": "医药",
    "医疗服务": "医药",
    "医药商业": "医药",
    "光伏设备": "电力设备",
    "电网设备": "电力设备",
    "电池": "电力设备",
    "风电设备": "电力设备",
    "其他电源设备": "电力设备",
    "自动化设备": "机械设备",
    "通用设备": "机械设备",
    "专用设备": "机械设备",
    "工程机械": "机械设备",
}


def theme_of(sector_name: str, symbol_name: str = "") -> str:
    name = str(sector_name or "").strip()
    symbol = str(symbol_name or "")
    if any(k in symbol for k in ("黄金", "招金", "山金", "中金", "金徽", "恒邦")):
        return "贵金属"
    if any(k in symbol for k in ("航运", "海控", "轮船", "中谷", "盛航", "兴通")):
        return "航运物流"
    if any(k in symbol for k in ("石化", "桐昆", "恒逸", "盛虹", "荣盛")):
        return "石化化工"
    if name in BOARD_TO_THEME:
        return BOARD_TO_THEME[name]
    return name or "未分类"


def apply_theme_caps(
    rows: List[Dict[str, Any]],
    *,
    theme_cap_pct: float = 12.0,
    max_names_per_theme: int = 3,
    position_key: str = "raw_position_pct",
    score_key: str = "pre_score",
) -> List[Dict[str, Any]]:
    """按 PreScore 在主题内排序，先到先得，超主题上限则缩仓或标 THEME_CAP。"""
    grouped: Dict[str, List[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        grouped[str(row.get("theme") or "未分类")].append(i)

    used: Dict[str, float] = defaultdict(float)
    counts: Dict[str, int] = defaultdict(int)
    out = [dict(r) for r in rows]

    order = sorted(range(len(out)), key=lambda i: float(out[i].get(score_key) or 0), reverse=True)
    for i in order:
        row = out[i]
        theme = str(row.get("theme") or "未分类")
        raw = float(row.get(position_key) or 0.0)
        remaining = max(0.0, theme_cap_pct - used[theme])
        over_count = counts[theme] >= max_names_per_theme
        if over_count or remaining <= 0.05:
            row["suggested_position_pct"] = 0.0
            row["portfolio_state"] = "THEME_CAP"
            row["theme_used_pct"] = round(used[theme], 2)
            continue
        sized = min(raw, remaining)
        row["suggested_position_pct"] = round(sized, 2)
        row["portfolio_state"] = "OK" if sized + 1e-9 >= raw else "THEME_TRIM"
        used[theme] += sized
        counts[theme] += 1
        row["theme_used_pct"] = round(used[theme], 2)

    return out


def theme_summary(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        theme = str(row.get("theme") or "未分类")
        bucket = buckets.setdefault(theme, {"theme": theme, "names": 0, "gross_pct": 0.0, "kept_pct": 0.0})
        bucket["names"] += 1
        bucket["gross_pct"] += float(row.get("raw_position_pct") or 0.0)
        if row.get("portfolio_state") != "THEME_CAP":
            bucket["kept_pct"] += float(row.get("suggested_position_pct") or 0.0)
    out = []
    for bucket in buckets.values():
        out.append({
            "theme": bucket["theme"],
            "names": bucket["names"],
            "gross_pct": round(bucket["gross_pct"], 2),
            "kept_pct": round(bucket["kept_pct"], 2),
        })
    return sorted(out, key=lambda x: x["gross_pct"], reverse=True)
