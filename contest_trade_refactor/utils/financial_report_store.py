"""Point-in-time financial report payload store.

Financial data is shared across strategies, but reads must remain as-of safe:
payloads are stored by symbol, report period, and the trigger/as-of date that
produced them. Historical replays only reuse cached payloads whose as-of date
is not after the replay trigger date.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from utils.market_data_paths import financial_report_store_dir


_STORE: Optional["FinancialReportStore"] = None
_LOCK = threading.Lock()


def store_enabled() -> bool:
    return str(os.environ.get("CN_FINANCIAL_REPORT_STORE", "1")).lower() not in {"0", "false", "no", "off"}


def _compact_date(value: str) -> str:
    text = str(value or "").strip().split(" ")[0].replace("-", "").replace("/", "")
    return text[:8] if len(text) >= 8 and text[:8].isdigit() else ""


def _stock_key(symbol: str) -> str:
    digits = "".join(ch for ch in str(symbol or "") if ch.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def _safe_key(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value or "").strip())


class FinancialReportStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else financial_report_store_dir()
        self._mem: dict[tuple[str, str, str, str], Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def _period_dir(self, market: str, statement: str, symbol: str, period: str) -> Path:
        return self.root / _safe_key(market) / _safe_key(statement) / _stock_key(symbol) / _safe_key(period)

    def load_latest(
        self,
        *,
        market: str,
        statement: str,
        symbol: str,
        period: str,
        as_of: str,
    ) -> Dict[str, Any]:
        asof_key = _compact_date(as_of)
        if not asof_key:
            return {}
        period_dir = self._period_dir(market, statement, symbol, period)
        if not period_dir.exists():
            return {}
        candidates = []
        for path in period_dir.glob("*.json"):
            cached_asof = _compact_date(path.stem)
            if cached_asof and cached_asof <= asof_key:
                candidates.append((cached_asof, path))
        if not candidates:
            return {}
        cached_asof, path = sorted(candidates)[-1]
        key = (market, statement, _stock_key(symbol), period, cached_asof)
        with self._lock:
            if key in self._mem:
                return dict(self._mem[key])
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}
            if not isinstance(payload, dict):
                return {}
            self._mem[key] = payload
            return dict(payload)

    def save(
        self,
        *,
        market: str,
        statement: str,
        symbol: str,
        period: str,
        as_of: str,
        payload: Dict[str, Any],
    ) -> Path | None:
        asof_key = _compact_date(as_of)
        if not asof_key or not payload:
            return None
        period_dir = self._period_dir(market, statement, symbol, period)
        period_dir.mkdir(parents=True, exist_ok=True)
        enriched = dict(payload)
        enriched.setdefault("symbol", symbol)
        enriched.setdefault("period", period)
        enriched["fetched_as_of"] = asof_key
        path = period_dir / f"{asof_key}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        with self._lock:
            self._mem[(market, statement, _stock_key(symbol), period, asof_key)] = enriched
        return path


def get_financial_report_store() -> FinancialReportStore:
    global _STORE
    with _LOCK:
        if _STORE is None:
            _STORE = FinancialReportStore()
        return _STORE
