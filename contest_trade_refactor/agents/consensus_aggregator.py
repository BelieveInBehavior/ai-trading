"""Deterministic multi-agent consensus for research signals.

The aggregator keeps one representative signal per symbol and per research
agent, so repeated research rounds do not accidentally count as extra votes.
It does not replace the ranker's gates or risk veto; it prepares an auditable
consensus record for those downstream checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from agents.signal_schema import parse_probability


@dataclass
class ConsensusConfig:
    enabled: bool = True
    method: str = "weighted_majority"
    min_agent_count: int = 1
    require_majority: bool = True
    max_evidence_per_symbol: int = 25


class ConsensusAggregator:
    BUY_ACTION_KEYWORDS = ["buy", "long", "加仓", "买入", "增持", "做多"]
    SELL_ACTION_KEYWORDS = ["sell", "short", "减仓", "卖出", "做空", "回避"]

    def __init__(self, config: Optional[ConsensusConfig] = None):
        self.config = config or ConsensusConfig()

    def aggregate(
        self,
        research_signals: List[Dict[str, Any]],
        trigger_time: str,
    ) -> List[Dict[str, Any]]:
        if not self.config.enabled or not research_signals:
            return list(research_signals or [])

        # A repeated round from the same agent is one vote, not several votes.
        grouped: Dict[str, Dict[str, Tuple[Dict[str, Any], int, float]]] = {}
        raw_counts: Dict[str, int] = {}
        for index, signal in enumerate(research_signals):
            symbol_key = self._symbol_key(signal)
            if not symbol_key:
                continue
            raw_counts[symbol_key] = raw_counts.get(symbol_key, 0) + 1
            agent_key = self._agent_key(signal, index)
            quality = self._evidence_quality(signal, trigger_time)
            current = grouped.setdefault(symbol_key, {}).get(agent_key)
            candidate = (signal, index, quality)
            if current is None or self._representative_key(candidate) > self._representative_key(current):
                grouped[symbol_key][agent_key] = candidate

        aggregated = [
            self._aggregate_symbol(
                selected=list(agent_signals.values()),
                trigger_time=trigger_time,
                source_signal_count=raw_counts.get(symbol_key, 0),
            )
            for symbol_key, agent_signals in grouped.items()
        ]
        aggregated.sort(
            key=lambda signal: (
                signal.get("consensus_report", {}).get("consensus_confidence", 0.0),
                signal.get("consensus_report", {}).get("buy_vote_weight", 0.0),
                signal.get("probability", 0.0),
            ),
            reverse=True,
        )
        return aggregated

    def _aggregate_symbol(
        self,
        selected: List[Tuple[Dict[str, Any], int, float]],
        trigger_time: str,
        source_signal_count: int,
    ) -> Dict[str, Any]:
        votes = []
        for signal, index, quality in selected:
            vote = self._vote(signal)
            probability = parse_probability(signal.get("probability"))
            weight = max(0.05, quality * (0.25 + 0.75 * probability))
            votes.append(
                {
                    "signal": signal,
                    "index": index,
                    "agent_id": str(signal.get("agent_id") or ""),
                    "agent_name": str(signal.get("agent_name") or ""),
                    "agent_key": self._agent_key(signal, index),
                    "vote": vote,
                    "probability": probability,
                    "evidence_quality": round(quality, 4),
                    "weight": round(weight, 4),
                }
            )

        counts = {action: 0 for action in ("buy", "watch", "sell")}
        weights = {action: 0.0 for action in ("buy", "watch", "sell")}
        for item in votes:
            counts[item["vote"]] += 1
            weights[item["vote"]] += item["weight"]

        total_weight = sum(weights.values())
        winning_action = max(
            weights,
            key=lambda action: (weights[action], counts[action], action == "buy"),
        )
        buy_majority = (
            counts["buy"] >= self.config.min_agent_count
            and weights["buy"] > weights["watch"]
            and weights["buy"] > weights["sell"]
            and (
                not self.config.require_majority
                or weights["buy"] > total_weight / 2.0
            )
        )
        consensus_action = "buy" if buy_majority else winning_action
        if consensus_action == "buy" and not buy_majority:
            consensus_action = "watch"

        base_signal = max(
            votes,
            key=lambda item: (
                item["vote"] == consensus_action,
                item["evidence_quality"],
                item["probability"],
                -item["index"],
            ),
        )["signal"]
        result = dict(base_signal)

        all_evidence = self._merge_evidence(votes)
        limitations = self._merge_text_lists(
            item["signal"].get("limitations") or []
            for item in votes
        )
        quality_warnings = self._merge_text_lists(
            item["signal"].get("data_quality_warnings") or []
            for item in votes
        )
        probabilities = [
            (item["probability"], item["evidence_quality"])
            for item in votes
        ]
        probability_weight = sum(weight for _, weight in probabilities)
        aggregate_probability = (
            sum(probability * weight for probability, weight in probabilities)
            / probability_weight
            if probability_weight
            else 0.5
        )

        result.update(
            {
                "has_opportunity": "yes" if consensus_action == "buy" else "no",
                "action": consensus_action,
                "evidence_list": all_evidence[: self.config.max_evidence_per_symbol],
                "limitations": limitations,
                "probability": round(aggregate_probability, 4),
                "data_quality_warnings": quality_warnings,
                "agent_count": len(votes),
                "supporting_signal_count": len(votes),
                "consensus_report": {
                    "method": self.config.method,
                    "trigger_time": trigger_time,
                    "consensus_action": consensus_action,
                    "winning_action": winning_action,
                    "passed": consensus_action == "buy",
                    "agent_count": len(votes),
                    "source_signal_count": source_signal_count,
                    "buy_vote_count": counts["buy"],
                    "watch_vote_count": counts["watch"],
                    "sell_vote_count": counts["sell"],
                    "buy_vote_weight": round(weights["buy"], 4),
                    "watch_vote_weight": round(weights["watch"], 4),
                    "sell_vote_weight": round(weights["sell"], 4),
                    "total_vote_weight": round(total_weight, 4),
                    "consensus_confidence": round(
                        weights[consensus_action] / total_weight
                        if total_weight
                        else 0.0,
                        4,
                    ),
                    "average_evidence_quality": round(
                        sum(item["evidence_quality"] for item in votes) / len(votes)
                        if votes
                        else 0.0,
                        4,
                    ),
                    "dissenting_agents": [
                        item["agent_key"]
                        for item in votes
                        if item["vote"] != consensus_action
                    ],
                },
                "agent_votes": [
                    {
                        "agent_id": item["agent_id"],
                        "agent_name": item["agent_name"],
                        "agent_key": item["agent_key"],
                        "vote": item["vote"],
                        "probability": item["probability"],
                        "evidence_quality": item["evidence_quality"],
                        "weight": item["weight"],
                        "evidence_count": len(item["signal"].get("evidence_list") or []),
                        "risk_flags": list(item["signal"].get("data_quality_warnings") or []),
                    }
                    for item in votes
                ],
            }
        )
        return result

    def _merge_evidence(
        self,
        votes: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen = set()
        for item in votes:
            signal = item["signal"]
            for evidence in signal.get("evidence_list") or []:
                evidence = dict(evidence or {})
                key = (
                    str(evidence.get("description") or "").strip(),
                    str(evidence.get("time") or "").strip(),
                    str(evidence.get("from_source") or "").strip(),
                )
                if key in seen:
                    continue
                seen.add(key)
                evidence["agent_id"] = item["agent_id"]
                evidence["agent_name"] = item["agent_name"]
                merged.append(evidence)
        return merged

    def _representative_key(
        self,
        candidate: Tuple[Dict[str, Any], int, float],
    ) -> Tuple[int, float, float, int]:
        signal, index, quality = candidate
        try:
            research_round = int(signal.get("research_round") or 0)
        except (TypeError, ValueError):
            research_round = 0
        return (
            research_round,
            quality,
            parse_probability(signal.get("probability")),
            -index,
        )

    def _symbol_key(self, signal: Dict[str, Any]) -> str:
        return str(signal.get("symbol_code") or signal.get("symbol_name") or "").strip()

    def _agent_key(self, signal: Dict[str, Any], index: int) -> str:
        return str(
            signal.get("agent_id")
            or signal.get("agent_name")
            or f"signal_{index}"
        ).strip()

    def _vote(self, signal: Dict[str, Any]) -> str:
        action = str(signal.get("action") or "").strip().lower()
        if any(keyword in action for keyword in self.SELL_ACTION_KEYWORDS):
            return "sell"
        if self._bool_like(signal.get("has_opportunity")) and any(
            keyword in action for keyword in self.BUY_ACTION_KEYWORDS
        ):
            return "buy"
        return "watch"

    def _evidence_quality(self, signal: Dict[str, Any], trigger_time: str) -> float:
        evidence_list = signal.get("evidence_list") or []
        if not evidence_list:
            return 0.2

        trigger_dt = self._parse_datetime(trigger_time)
        quality = min(0.35, 0.15 + len(evidence_list) * 0.05)
        for evidence in evidence_list:
            description = str(evidence.get("description") or "").strip()
            source = str(evidence.get("from_source") or "").strip()
            evidence_dt = self._parse_datetime(str(evidence.get("time") or ""))
            if description:
                quality += 0.08
            if source and source.upper() not in {"N/A", "UNKNOWN", "NONE"}:
                quality += 0.08
            if trigger_dt and evidence_dt:
                quality += 0.06 if evidence_dt <= trigger_dt else -0.25
            elif trigger_dt:
                quality -= 0.04
        return max(0.05, min(1.0, quality))

    def _merge_text_lists(self, lists) -> List[str]:
        merged = []
        seen = set()
        for values in lists:
            for value in values:
                text = str(value or "").strip()
                if text and text not in seen:
                    seen.add(text)
                    merged.append(text)
        return merged

    def _bool_like(self, value: Any) -> bool:
        return str(value).strip().lower() in {
            "1", "true", "yes", "y", "是", "有", "有机会",
        }

    def _parse_datetime(self, text: str) -> Optional[datetime]:
        if not text:
            return None
        normalized = (
            text.strip()
            .replace("/", "-")
            .replace("T", " ")
            .replace("年", "-")
            .replace("月", "-")
            .replace("日", "")
        )
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y%m%d %H:%M:%S",
            "%Y%m%d",
            "%m-%d %H:%M",
        ):
            try:
                parsed = datetime.strptime(normalized, fmt)
                if fmt == "%m-%d %H:%M":
                    parsed = parsed.replace(year=datetime.now().year)
                return parsed
            except ValueError:
                continue
        if normalized.isdigit() and len(normalized) in {10, 13}:
            try:
                return datetime.fromtimestamp(int(normalized[:10]))
            except (OverflowError, OSError, ValueError):
                return None
        return None
