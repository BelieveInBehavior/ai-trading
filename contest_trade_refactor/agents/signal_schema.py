"""Structured contracts for research and next-day buy signals.

The research agents still support their legacy XML output, but all parsed
signals pass through these models before scoring. This keeps malformed or
ambiguous model output from silently entering the ranking pipeline.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


def parse_probability(value: Any, default: float = 0.5) -> float:
    """Normalize decimal or percentage probabilities into [0, 1]."""
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    try:
        text = str(value).strip()
        if not text:
            return default
        number = float(text.rstrip("%"))
        if "%" in text or number > 1.0:
            number /= 100.0
        return max(0.0, min(1.0, number))
    except (TypeError, ValueError):
        return default


class EvidenceRecord(BaseModel):
    description: str = ""
    time: str = "N/A"
    from_source: str = "N/A"

    class Config:
        extra = "ignore"


class ResearchSignal(BaseModel):
    """Validated signal emitted by a research agent."""

    has_opportunity: str = ""
    action: str = ""
    symbol_code: str = ""
    symbol_name: str = ""
    evidence_list: List[EvidenceRecord] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    probability: float = 0.5
    thinking: str = ""
    data_quality_warnings: List[str] = Field(default_factory=list)

    class Config:
        extra = "ignore"


class BuyDecision(BaseModel):
    """Stable downstream contract for a selected or watched candidate."""

    signal_contract_version: Literal["buy-signal.v1"] = "buy-signal.v1"
    symbol_code: str = ""
    symbol_name: str = ""
    buy_decision: Literal["buy", "watch"] = "watch"
    buy_score: float = 0.0
    probability_value: float = 0.5
    expected_return_t1_pct: float = 0.0
    entry_timing: str = "next_trading_day_open"
    risk_flags: List[str] = Field(default_factory=list)

    class Config:
        extra = "allow"


def _model_dump(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def validate_research_signal(payload: Dict[str, Any], thinking: str = "") -> Dict[str, Any]:
    """Validate and normalize a raw research signal payload."""
    normalized = dict(payload or {})
    normalized["thinking"] = thinking or normalized.get("thinking") or ""
    normalized["probability"] = parse_probability(normalized.get("probability"))

    evidence = normalized.get("evidence_list") or []
    normalized["evidence_list"] = [
        item if isinstance(item, dict) else {"description": str(item)}
        for item in evidence
    ]
    normalized["limitations"] = [
        str(item).strip()
        for item in (normalized.get("limitations") or [])
        if str(item).strip()
    ]

    if hasattr(ResearchSignal, "model_validate"):
        validated = ResearchSignal.model_validate(normalized)
    else:
        validated = ResearchSignal.parse_obj(normalized)
    result = _model_dump(validated)
    result["evidence_list"] = [
        _model_dump(item) if isinstance(item, BaseModel) else item
        for item in validated.evidence_list
    ]
    return result


def validate_buy_decision(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the stable output contract without dropping ranker metadata."""
    normalized = dict(payload or {})
    normalized["probability_value"] = parse_probability(
        normalized.get("probability_value"),
        default=0.5,
    )
    normalized["risk_flags"] = [
        str(item).strip()
        for item in (normalized.get("risk_flags") or [])
        if str(item).strip()
    ]
    if hasattr(BuyDecision, "model_validate"):
        validated = BuyDecision.model_validate(normalized)
    else:
        validated = BuyDecision.parse_obj(normalized)
    result = _model_dump(validated)
    result.update(
        {
            key: value
            for key, value in normalized.items()
            if key not in result
        }
    )
    return result


def _decode_json_candidate(text: str) -> Any:
    """Decode the first JSON object/array in a model response."""
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[index:])
            return value
        except json.JSONDecodeError:
            continue
    return None


def parse_json_signals(text: str, thinking: str = "") -> List[Dict[str, Any]]:
    """Parse the preferred JSON signal format.

    Accepted roots are either a list of signal objects or
    ``{"signals": [...]}``.
    """
    decoded = _decode_json_candidate(text)
    if isinstance(decoded, dict):
        decoded = decoded.get("signals") or decoded.get("signal") or []
    if not isinstance(decoded, list):
        return []

    signals = []
    for item in decoded:
        if not isinstance(item, dict):
            continue
        validated = validate_research_signal(item, thinking=thinking)
        if validated.get("symbol_code") or validated.get("symbol_name"):
            signals.append(validated)
    return signals
