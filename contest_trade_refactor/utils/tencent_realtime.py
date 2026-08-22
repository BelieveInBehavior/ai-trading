"""腾讯财经实时行情（A股）与手动输入兜底。

优先级：腾讯财经实时接口 -> 手动输入（env/config/factor dict）。

腾讯财经 push2/qt.gtimg.cn 单只行情返回典型的 ``~`` 分隔字段：
  0: 未知/市场
  1: 名称
  2: 代码
  3: 最新价
  4: 昨收
  5: 今开
  6: 成交量（手）
  7: 外盘
  8: 内盘
  9~18: 买一~买五/卖一~卖五价格量（顺序因版本略有差异）
  19: 卖一量
  30: 时间
  31: 涨跌
  32: 涨跌幅
  33: 最高
  34: 最低
  36: 成交量(手)
  37: 成交额(万)
  38: 换手率
  39: 市盈率
  45: 量比
  46: 均价（当日 VWAP）
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import requests
from loguru import logger

TENCENT_QT_URL = "https://qt.gtimg.cn/q={code}"
MANUAL_CONFIG = "config/manual_realtime.json"


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())[-6:].zfill(6)


def to_tencent_code(symbol: Any) -> str:
    digits = _digits(symbol)
    if digits.startswith(("60", "68", "90", "92", "51", "58", "50")):
        return f"sh{digits}"
    return f"sz{digits}"


def _as_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if v in (None, "", "-", "--"):
            return default
        text = str(v).strip().replace(",", "")
        if not text or text in {"-", "--"}:
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def parse_tencent_quote(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    match = re.search(r'="([^"]*)"', text)
    if not match:
        return {}
    parts = match.group(1).split("~")
    if len(parts) < 30:
        return {}
    out: Dict[str, Any] = {
        "market": parts[0],
        "symbol_name": parts[1] or "",
        "symbol_code": parts[2] or "",
        "price": _as_float(parts[3]),
        "prev_close": _as_float(parts[4]),
        "open": _as_float(parts[5]),
        "volume": _as_float(parts[6], 0.0),
        "external": _as_float(parts[7], 0.0),
        "internal": _as_float(parts[8], 0.0),
        "bid": _as_float(parts[9]),
        "ask": _as_float(parts[19]),
        "timestamp": parts[30],
        "change": _as_float(parts[31]),
        "change_pct": _as_float(parts[32]),
        "high": _as_float(parts[33]) if len(parts) > 33 else None,
        "low": _as_float(parts[34]) if len(parts) > 34 else None,
        "amount_wan": _as_float(parts[37], 0.0) if len(parts) > 37 else 0.0,
        "turnover_pct": _as_float(parts[38]) if len(parts) > 38 else None,
        "volume_ratio": _as_float(parts[45]) if len(parts) > 45 else None,
        "vwap": _as_float(parts[46]) if len(parts) > 46 else None,
    }
    # 深挖买卖五档
    bids, asks = [], []
    for i in range(5):
        bp = _as_float(parts[11 + i * 2] if len(parts) > 11 + i * 2 else None)
        bv = _as_float(parts[11 + i * 2 + 1] if len(parts) > 11 + i * 2 + 1 else 0.0)
        ap = _as_float(parts[21 + i * 2] if len(parts) > 21 + i * 2 else None)
        av = _as_float(parts[21 + i * 2 + 1] if len(parts) > 21 + i * 2 + 1 else 0.0)
        if bp is not None:
            bids.append([bp, bv])
        if ap is not None:
            asks.append([ap, av])
    out["bids"] = bids
    out["asks"] = asks
    return out


@dataclass
class RealtimeQuote:
    symbol_code: str = ""
    symbol_name: str = ""
    source: str = "manual"
    price: Optional[float] = None
    prev_close: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: float = 0.0
    amount_wan: float = 0.0
    vwap: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    bid_volume: float = 0.0
    ask_volume: float = 0.0
    active_buy_amount: Optional[float] = None
    active_sell_amount: Optional[float] = None
    timestamp: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    @property
    def amount_yuan(self) -> Optional[float]:
        return self.amount_wan * 1e4 if self.amount_wan is not None else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol_code": self.symbol_code,
            "symbol_name": self.symbol_name,
            "source": self.source,
            "price": self.price,
            "prev_close": self.prev_close,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "volume": self.volume,
            "amount_wan": self.amount_wan,
            "vwap": self.vwap,
            "bid": self.bid,
            "ask": self.ask,
            "bid_volume": self.bid_volume,
            "ask_volume": self.ask_volume,
            "active_buy_amount": self.active_buy_amount,
            "active_sell_amount": self.active_sell_amount,
            "timestamp": self.timestamp,
            "detail": self.detail,
        }


def _normalize_manual_quote(d: Dict[str, Any]) -> RealtimeQuote:
    def num(k: str, default: Optional[float] = None) -> Optional[float]:
        return _as_float(d.get(k), default)

    price = num("price")
    if price is None:
        price = num("latest") or num("current")
    prev_close = num("prev_close")
    open_ = num("open")
    high = num("high")
    low = num("low")
    if high is None and price is not None and low is not None:
        high = max(price, low)
    if low is None and price is not None and high is not None:
        low = min(price, high)
    if open_ is None and prev_close is not None and price is not None:
        # 默认 gap=0
        open_ = prev_close
    return RealtimeQuote(
        symbol_code=str(d.get("symbol_code") or ""),
        symbol_name=str(d.get("symbol_name") or ""),
        source=str(d.get("source") or "manual"),
        price=price,
        prev_close=prev_close,
        open=open_,
        high=high,
        low=low,
        volume=num("volume") or 0.0,
        amount_wan=num("amount_wan") or num("amount") or 0.0,
        vwap=num("vwap") or num("average_price"),
        bid=num("bid"),
        ask=num("ask"),
        bid_volume=num("bid_volume") or 0.0,
        ask_volume=num("ask_volume") or 0.0,
        active_buy_amount=num("active_buy_amount"),
        active_sell_amount=num("active_sell_amount"),
        timestamp=str(d.get("timestamp") or ""),
        detail=dict(d),
    )


def _load_manual_config():
    try:
        path = os.environ.get("REQ_TRADE_MANUAL_FILE", "") or os.path.join(
            os.path.dirname(__file__), "..", "config", "manual_realtime.json"
        )
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("读取 manual_realtime 配置失败: {}", exc)
        return {}


def manual_realtime_quote(symbol: Any, manual: Optional[Dict[str, Any]] = None) -> RealtimeQuote:
    digits = _digits(symbol)
    pool: Dict[str, Any] = {}
    env_text = os.environ.get("REQ_TRADE_MANUAL_REALTIME", "")
    if env_text:
        try:
            env_data = json.loads(env_text)
            if isinstance(env_data, dict):
                pool.update(env_data)
        except Exception as exc:
            logger.warning("解析 REQ_TRADE_MANUAL_REALTIME 失败: {}", exc)
    pool.update(_load_manual_config())
    if isinstance(manual, dict):
        pool.update(manual)

    direct: Optional[Dict[str, Any]] = None
    for key, val in pool.items():
        if isinstance(val, dict) and _digits(key) == digits:
            direct = val
            break
    if direct is None and _digits(pool.get("symbol_code")) == digits:
        direct = pool
    if direct is None and (pool.get("price") is not None or pool.get("open") is not None or pool.get("vwap") is not None):
        direct = pool

    if direct is None:
        return RealtimeQuote(symbol_code=digits, source="manual_missing")
    direct = dict(direct)
    direct.setdefault("symbol_code", str(symbol))
    q = _normalize_manual_quote(direct)
    q.symbol_code = str(symbol) or digits
    q.source = "manual"
    return q


def fetch_tencent_quote(symbol: Any, timeout: float = 3.0) -> RealtimeQuote:
    code = to_tencent_code(symbol)
    try:
        resp = requests.get(TENCENT_QT_URL.format(code=code), timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        text = resp.text
        raw = parse_tencent_quote(text)
        if not raw:
            return RealtimeQuote(symbol_code=code, source="tencent_error", detail={"error": "empty_quote"})
        price = raw.get("price")
        prev_close = raw.get("prev_close")
        if price is None or price <= 0:
            return RealtimeQuote(symbol_code=code, source="tencent_error", detail={"error": "invalid_price", "raw": raw})
        volume = raw.get("volume") or 0.0
        amount_wan = raw.get("amount_wan") or 0.0
        vwap = raw.get("vwap")
        if vwap is None and amount_wan and volume:
            vwap = amount_wan * 1e4 / max(1.0, volume * 100.0)  # volume 手->股
        return RealtimeQuote(
            symbol_code=code,
            symbol_name=raw.get("symbol_name") or "",
            source="tencent",
            price=price,
            prev_close=prev_close,
            open=raw.get("open"),
            high=raw.get("high"),
            low=raw.get("low"),
            volume=volume,
            amount_wan=amount_wan,
            vwap=vwap,
            bid=raw.get("bid"),
            ask=raw.get("ask"),
            timestamp=raw.get("timestamp") or "",
            detail=raw,
        )
    except Exception as exc:
        logger.warning("腾讯实时行情失败 {}: {}", symbol, exc)
        return RealtimeQuote(symbol_code=code, source="tencent_error", detail={"error": str(exc)})


def fetch_realtime_quote(
    symbol: Any,
    *,
    prefer: str = "tencent",
    manual: Optional[Dict[str, Any]] = None,
    timeout: float = 3.0,
) -> RealtimeQuote:
    digits = _digits(symbol)
    prefer = str(prefer or "manual").lower()
    manual_q = manual_realtime_quote(symbol, manual=manual)
    if prefer == "manual":
        if manual_q.source == "manual_missing":
            return manual_q
        return manual_q
    if prefer in ("auto", "tencent"):
        q = fetch_tencent_quote(symbol, timeout=timeout)
        if q.source == "tencent" and q.price is not None:
            return q
        if prefer == "tencent":
            if manual_q.source != "manual_missing":
                manual_q.detail["fallback_reason"] = "tencent_failed_manual_used"
                return manual_q
            return q
        if manual_q.source != "manual_missing":
            manual_q.detail["fallback_reason"] = "tencent_failed_manual_used"
            return manual_q
        return q
    return manual_q


def build_quote_payload(q: Optional[RealtimeQuote]) -> Dict[str, Any]:
    return q.to_dict() if q else {}
