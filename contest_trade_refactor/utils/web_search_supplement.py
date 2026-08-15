"""Use Doubao/Volcengine web search to supplement failed structured market data."""

from __future__ import annotations

from typing import Any

# AkShare 结构化拉取失败/稀疏时触发联网搜索补充
AKSHARE_FAILURE_MARKERS = (
    "数据获取失败",
    "数据格式异常",
    "获取失败:",
    "分析失败:",
    "LLM分析失败",
    "数据为空",
    "明细为空",
    "无数据",
    "数据暂缺",
    "暂未披露",
    "净买额0.00",
    "最近可用净买额",
    "无法获取",
    "不可用",
)


def content_needs_web_supplement(
    content: str,
    extra_markers: tuple[str, ...] = (),
) -> bool:
    text = (content or "").strip()
    if not text:
        return True
    markers = AKSHARE_FAILURE_MARKERS + extra_markers
    return any(marker in text for marker in markers)


async def fetch_web_search_context(
    query: str,
    trigger_time: str,
    *,
    topk: int = 5,
    section_title: str = "联网搜索补充",
) -> str:
    """Return formatted markdown section from search_web, or empty string."""
    query = (query or "").strip()
    if not query or not trigger_time:
        return ""

    try:
        from tools.search_web import search_web

        raw = await search_web.ainvoke(
            {"query": query, "topk": topk, "trigger_time": trigger_time}
        )
        text = _extract_search_text(raw)
        if not text:
            return ""
        return f"\n\n### {section_title}\n来源：豆包搜索联网补充\n\n{text}\n"
    except Exception as exc:
        return f"\n\n### {section_title}\n联网搜索补充失败: {exc}\n"


async def append_web_search_supplement(
    content: str,
    *,
    query: str,
    trigger_time: str,
    section_title: str = "联网搜索补充",
    topk: int = 5,
    extra_markers: tuple[str, ...] = (),
) -> str:
    """Append Doubao web search when AkShare structured content is missing or failed."""
    if not content_needs_web_supplement(content, extra_markers):
        return content
    supplement = await fetch_web_search_context(
        query=query,
        trigger_time=trigger_time,
        topk=topk,
        section_title=section_title,
    )
    return content + supplement if supplement else content


async def web_search_fallback_dataframe(
    *,
    title: str,
    query: str,
    trigger_time: str,
    section_title: str = "联网搜索补充",
    pub_time: str,
    topk: int = 5,
    **extra_fields: Any,
) -> "pd.DataFrame":
    """Build a report DataFrame purely from web search when AkShare path fails entirely."""
    import pandas as pd

    block = await fetch_web_search_context(
        query=query,
        trigger_time=trigger_time,
        topk=topk,
        section_title=section_title,
    )
    if not block.strip():
        return pd.DataFrame()
    content = (
        f"## {title}\n\n"
        "AkShare 结构化数据不可用，以下为豆包联网搜索补充：\n"
        f"{block}"
    )
    row: dict[str, Any] = {
        "title": title,
        "content": content,
        "pub_time": pub_time,
        "url": None,
    }
    row.update(extra_fields)
    return pd.DataFrame([row])


def _extract_search_text(raw: Any) -> str:
    if isinstance(raw, dict):
        data = raw.get("data")
        if isinstance(data, str) and data.strip():
            return data.strip()
        if raw.get("success") is False:
            return ""
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return ""
