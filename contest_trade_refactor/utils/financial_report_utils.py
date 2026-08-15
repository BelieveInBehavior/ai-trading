"""Lightweight financial statement enrichment for candidate signals.

Uses the existing akshare company income tool to fetch recent income
statements for CN stocks and attach a compact `financial_report` payload to
signals. The goal is to catch cases where media claims a big +YoY but the
latest official income statement shows a decline/small number.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List

from loguru import logger


COMPANY_INCOME_TOOL = None


def _latest_report_periods(trigger_time: str, count: int = 4) -> List[str]:
    """Return plausible latest report periods (YYYYMMDD) before trigger time."""
    try:
        year_s, month_s, _ = trigger_time.split(" ")[0].split("-")
        year = int(year_s)
        month = int(month_s)
    except Exception:
        return []

    cur_q = (month - 1) // 3  # 0..3 for quarter ends 03/06/09/12
    candidates = []
    for offset in range(count):
        q_abs = cur_q - offset
        y = year
        while q_abs < 0:
            q_abs += 4
            y -= 1
        month_end = [3, 6, 9, 12][q_abs]
        day = {3: 31, 6: 30, 9: 30, 12: 31}[month_end]
        candidates.append(f"{y}{month_end:02d}{day:02d}")
    return candidates



def _strip_future_dates(text: str, trigger_time: str) -> str:
    """Remove any line containing a date strictly after trigger_time."""
    if not text:
        return text
    try:
        from datetime import datetime
        trigger_dt = datetime.strptime(str(trigger_time).strip(), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return text
    kept = []
    for ln in text.splitlines():
        bad = False
        for m in re.finditer(r"\b(20\d{2}[-/]?\d{2}[-/]?\d{2})\b", ln):
            raw = m.group(1).replace("/", "-")
            try:
                dt = datetime.strptime(raw, "%Y%m%d") if len(raw) == 8 else datetime.strptime(raw, "%Y-%m-%d")
            except Exception:
                continue
            if dt > trigger_dt:
                bad = True
                break
        if not bad:
            kept.append(ln)
    return "\n".join(kept)


async def fetch_income_yoy(
    symbol: str,
    trigger_time: str,
    period: str,
    sem: asyncio.Semaphore,
) -> Dict[str, Any]:
    global COMPANY_INCOME_TOOL
    if COMPANY_INCOME_TOOL is None:
        try:
            from tools.corp_info_akshare import company_income
            COMPANY_INCOME_TOOL = company_income
        except Exception as exc:
            logger.warning("Failed to import company_income: {}", exc)
            return {}

    async with sem:
        try:
            result = await COMPANY_INCOME_TOOL.ainvoke({
                "market": "CN-Stock",
                "symbol": symbol,
                "period": period,
                "trigger_time": trigger_time,
            })
        except Exception as exc:
            logger.warning("company_income failed {} {}: {}", symbol, period, exc)
            return {}

        text = str(result) if result is not None else ""
        if not text or "error" in text.lower():
            return {}

        lines = text.splitlines()
        header_line = next((ln for ln in lines if "净利润同比" in ln), "")
        if not header_line:
            return {}
        header_cells = [h.strip() for h in header_line.strip().strip("|").split("|")] if header_line else []

        for line in lines:
            if "|" not in line or "净利润" in line:
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) != len(header_cells) and len(cells) < len(header_cells):
                continue

            def pick(key_subs):
                for i, h in enumerate(header_cells):
                    if i >= len(cells):
                        break
                    if any(k in h for k in key_subs):
                        raw = cells[i].replace(",", "").replace("元", "").strip()
                        m = re.match(r"^-?\d+(?:\.\d+)?$", raw)
                        if m:
                            return float(m.group(0))
                return None

            yoy = pick(["净利润同比"])
            if yoy is None:
                continue
            net = pick(["净利润"])
            rev_yoy = pick(["营业总收入同比"])
            return {
                "period": period,
                "net_profit": net,
                "net_profit_yoy": yoy,
                "revenue_yoy": rev_yoy,
                "raw_preview": _strip_future_dates(text, trigger_time)[:1200],
            }
    return {}


async def enrich_signals_with_financial_report(
    signals: List[Dict[str, Any]],
    trigger_time: str,
    period_count: int = 3,
    concurrency: int = 4,
) -> List[Dict[str, Any]]:
    """Attach recent income-statement YOY data to each signal if available."""
    if not signals:
        return signals
    sem = asyncio.Semaphore(max(1, int(concurrency)))

    async def _one(sig):
        code = str(sig.get("symbol_code") or "")
        if "." not in code:
            return sig
        periods = _latest_report_periods(trigger_time, period_count)
        for period in periods:
            payload = await fetch_income_yoy(
                symbol=code,
                trigger_time=trigger_time,
                period=period,
                sem=sem,
            )
            if payload:
                enriched = dict(sig)
                enriched["financial_report"] = payload
                enriched["financial_report_net_profit_yoy"] = payload.get("net_profit_yoy")
                enriched["financial_report_revenue_yoy"] = payload.get("revenue_yoy")
                return enriched
        return sig

    enriched = []
    for sig in signals:
        try:
            enriched.append(await _one(sig))
        except Exception as exc:
            logger.warning("financial enrich failed {}: {}", sig.get("symbol_code"), exc)
            enriched.append(sig)
    return enriched
