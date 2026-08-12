"""Helpers for counting real tool/data failures in system health scoring."""
from __future__ import annotations

import re
from typing import Any, Iterable, List

DATA_FACTOR_FAILURE_MARKERS = (
    "数据获取失败",
    "数据格式异常",
    "LLM分析失败",
)

TOOL_FAILURE_PATTERNS = (
    re.compile(r"接口异常"),
    re.compile(r"连接异常"),
    re.compile(r"执行超时"),
    re.compile(r"执行失败"),
    re.compile(r"数据获取失败"),
    re.compile(r"查询.{0,12}超时"),
    re.compile(r"stock_summary failed", re.I),
    re.compile(r"Tool selection failed", re.I),
    re.compile(r"error_message\s*[:=]", re.I),
    re.compile(r"""['"]success['"]\s*:\s*False"""),
)


def factor_content_is_usable(content: str) -> bool:
    """Return False when a data-factor report is a known fetch-failure placeholder."""
    text = content or ""
    if not text.strip():
        return False
    return not any(marker in text for marker in DATA_FACTOR_FAILURE_MARKERS)


def count_data_factor_tool_errors(data_factors: Iterable[dict]) -> int:
    errors = 0
    for factor in data_factors or []:
        content = factor.get("context_string", "") or ""
        if not factor_content_is_usable(content):
            errors += 1
    return errors


def is_failed_tool_result(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("success") is False:
        return True
    if result.get("error_message"):
        return True
    if result.get("error") and result.get("error_msg"):
        return True
    return False


def count_research_tool_call_errors(tool_calls: Iterable[dict]) -> int:
    errors = 0
    for call in tool_calls or []:
        if is_failed_tool_result(call.get("result")):
            errors += 1
    return errors


def count_tool_failure_mentions_in_text(text: str) -> int:
    if not text:
        return 0
    return sum(1 for pattern in TOOL_FAILURE_PATTERNS if pattern.search(text))


def text_indicates_tool_failure(text: str) -> bool:
    return count_tool_failure_mentions_in_text(text) > 0


def summarize_research_agent_tool_errors(result: Any, tool_calls: List[dict] | None) -> int:
    """Prefer explicit failed tool calls; fall back to thinking text for cached runs."""
    explicit_errors = count_research_tool_call_errors(tool_calls or [])
    if explicit_errors > 0:
        return explicit_errors

    if tool_calls:
        return 0

    thinking = getattr(result, "final_result_thinking", "") or ""
    return count_tool_failure_mentions_in_text(thinking)
