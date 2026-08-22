"""Structured contracts for research and next-day buy signals.

The research agents still support their legacy XML output, but all parsed
signals pass through these models before scoring. This keeps malformed or
ambiguous model output from silently entering the ranking pipeline.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Optional, Union

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
    """Validated signal emitted by a research agent.

    Catalyst output follows the final architecture: LLM produces only structured
    event variables; the deterministic engine decides on eligibility/position/risk.
    """

    has_opportunity: Union[str, bool] = ""
    action: str = ""
    symbol_code: str = ""
    symbol_name: str = ""
    event_type: Optional[str] = ""
    event_date: Optional[str] = ""
    event_summary: Optional[str] = ""
    event_level: Optional[str] = "B"

    # --- Catalyst × Price Reaction structured fields (Engine consumes) ---
    event_level: str = "B"
    freshness: float = 0.0
    company_specific: bool = False
    credibility: float = 0.0
    source_quality: str = "unknown"
    earnings_impact: float = 0.0
    expected_return_pct: Optional[float] = None
    actual_return_pct: Optional[float] = None
    gap_pct: Optional[float] = None
    intraday_return_pct: Optional[float] = None
    price_reaction: str = "neutral"

    # Legacy fields backfilled / preserved
    catalyst_certainty: float = 0.0
    catalyst_market_impact: float = 0.0
    price_in_status: str = ""
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


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v in (None, ""):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _normalize_catalyst_structured(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Back-fill new structured catalyst fields from legacy LLM fields and vice versa.

    LLM produces only structured event variables. The deterministic engine consumes
    these structured fields; legacy `catalyst_certainty` / `catalyst_market_impact`
    are mapped into event_level / credibility / earnings_impact so old model output
    still flows into the new engine without being dropped.
    """
    out = dict(payload or {})
    event_type = str(out.get("event_type") or "").strip().lower()
    has_event = bool(event_type and event_type != "none")
    if not has_event:
        out["event_level"] = ""
        out["freshness"] = 0.0
        out["company_specific"] = False
        out["credibility"] = 0.0
        out["source_quality"] = "unknown"
        out["earnings_impact"] = 0.0
        out["price_reaction"] = "neutral"
        return out

    if not out.get("event_level"):
        legacy_impact = _to_float(out.get("catalyst_market_impact"), 0.0)
        legacy_certainty = _to_float(out.get("catalyst_certainty"), 0.0)
        combined = (legacy_impact + legacy_certainty) / 2.0
        out["event_level"] = (
            "S" if combined >= 8 else "A" if combined >= 6.5 else "B" if combined >= 4.5 else "C"
        )

    if (out.get("credibility") is None or _to_float(out.get("credibility"), -1) < 0) and out.get("catalyst_certainty") is not None:
        out["credibility"] = max(0.0, min(1.0, _to_float(out["catalyst_certainty"], 0.0) / 10.0))

    if (out.get("earnings_impact") is None or _to_float(out.get("earnings_impact"), -1) < 0) and out.get("catalyst_market_impact") is not None:
        out["earnings_impact"] = max(0.0, min(1.0, _to_float(out["catalyst_market_impact"], 0.0) / 10.0))

    if not out.get("source_quality"):
        out["source_quality"] = "unknown"

    if out.get("price_reaction") in (None, ""):
        reaction = str(out.get("price_in_status") or "").lower()
        if reaction in ("not yet visible", "partly priced"):
            out["price_reaction"] = "positive"
        elif reaction == "fully priced":
            out["price_reaction"] = "neutral"
        elif reaction == "unknown":
            out["price_reaction"] = "neutral"
        else:
            out["price_reaction"] = "neutral"

    if out.get("expected_return_pct") is None and out.get("gap_pct") is not None:
        out["expected_return_pct"] = _to_float(out["gap_pct"], 0.0)
    return out


def validate_research_signal(payload: Dict[str, Any], thinking: str = "") -> Dict[str, Any]:
    """Validate and normalize a raw research signal payload."""
    payload = _normalize_catalyst_structured(payload or {})
    normalized = dict(payload or {})
    normalized["thinking"] = thinking or normalized.get("thinking") or ""
    normalized["probability"] = parse_probability(normalized.get("probability"))
    ho = normalized.get("has_opportunity")
    if isinstance(ho, bool):
        normalized["has_opportunity"] = "yes" if ho else "no"
    elif ho is not None:
        normalized["has_opportunity"] = str(ho)

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


def _decode_all_json_candidates(text: str):
    """Decode all top-level JSON objects/arrays in a model response.

    Research agents sometimes emit multiple independent JSON blocks in the
    same final result (multiple ``signals`` arrays). Only taking the first block
    silently drops valid signals, so we return all top-level values.
    """
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    decoder = json.JSONDecoder()
    out = []
    idx = 0
    while idx < len(cleaned):
        ch = cleaned[idx]
        if ch not in "[{":
            idx += 1
            continue
        try:
            value, end = decoder.raw_decode(cleaned[idx:])
            out.append(value)
            idx += end
        except json.JSONDecodeError:
            idx += 1
    return out


def _extract_signals_from_decoded(decoded):
    if isinstance(decoded, list):
        return decoded
    if isinstance(decoded, dict):
        if "signals" in decoded or "signal" in decoded or "signals_list" in decoded:
            return (
                decoded.get("signals")
                or decoded.get("signal")
                or decoded.get("signals_list")
                or []
            )
        # When the full JSON array is malformed, the decoder recovers individual
        # signal objects as top-level dicts. Treat them as one-item signal lists
        # so we don't silently drop the whole candidate.
        if decoded.get("symbol_code") or decoded.get("symbol_name"):
            return [decoded]
    return []


def _extract_signals_arrays_legacy(text: str):
    """Extract every ``"signals": [...]`` array in a raw model response.

    Research agents sometimes emit multiple ``signals`` keys inside a single
    JSON object. python's ``json`` decoder silently keeps only the last duplicate
    key, which drops earlier candidates, so we scan the raw text with a regex
    before/independently of full-JSON decoding.
    """
    arrays = []
    pattern = re.compile(r'"signals"\s*:\s*\[')
    decoder = json.JSONDecoder()
    for match in pattern.finditer(text or ""):
        start = match.end() - 1  # points at '['
        end = _find_json_array_end(text, start)
        if end is None:
            continue
        chunk = text[start:end + 1]
        try:
            value = json.loads(chunk)
        except Exception:
            try:
                value, _ = decoder.raw_decode(chunk)
            except Exception:
                continue
        if isinstance(value, list):
            arrays.extend(value)
    return arrays


def _find_json_array_end(text: str, start: int) -> int:
    """Return the index of the closing bracket for a JSON array starting at start."""
    depth = 0
    i = start
    n = len(text)
    in_string = False
    escaped = False
    while i < n:
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '\"':
                in_string = False
        else:
            if ch == '\"':
                in_string = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return None


def parse_json_signals(text: str, thinking: str = "") -> List[Dict[str, Any]]:
    """Parse the preferred JSON signal format.

    Accepts one or more top-level JSON blocks, either a list of signal objects
    or ``{"signals": [...]}``.  Multiple blocks are merged so valid signals
    emitted later in a report are not lost. Also handles raw text in which the
    same ``signals`` key is duplicated inside one JSON object.
    """
    candidates = _decode_all_json_candidates(text) or []
    combined: List[Any] = list(_extract_signals_arrays_legacy(text))
    for decoded in candidates:
        combined.extend(_extract_signals_from_decoded(decoded))

    signals = []
    seen = set()
    for item in combined:
        if not isinstance(item, dict):
            continue
        if not (item.get("symbol_code") or item.get("symbol_name")):
            # Skip partial JSON fragments (e.g. evidence dicts recovered after
            # an LLM malformed a parent array).
            continue
        try:
            validated = validate_research_signal(item, thinking=thinking)
        except Exception:
            continue
        if validated.get("symbol_code") or validated.get("symbol_name"):
            key = (
                str(validated.get("symbol_code") or "")
                + "|"
                + str(validated.get("symbol_name") or "")
                + "|"
                + str(validated.get("event_summary") or "")[:40]
            )
            if key in seen:
                continue
            seen.add(key)
            signals.append(validated)
    return signals
