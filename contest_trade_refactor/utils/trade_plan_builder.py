"""Candidate-level trade plan builder.

For a single symbol at a given as-of date, compute the pre-trade decision
fields used by 1-5 day swing / momentum plans:
  - RSI (14)
  - VWAP (rolling 5/20 cession volume-weighted price)
  - EMA (8/13/21/50)
  - support / resistance from recent swing lows/highs
  - ATR-based stop, resistance-based first/second targets
  - entry zone, stop loss, take profit, risk/reward ratio
  - simple position size suggestion from per-trade risk
"""

from __future__ import annotations

import math
import re
from statistics import mean
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from utils.cn_price_provider import get_stock_zh_a_hist
from utils.date_utils import get_latest_completed_trading_date, get_trading_date_range
from utils.strong_stock_lifecycle import score_entry_quality, score_weak_to_strong
from loguru import logger


DEFAULT_LOOKBACK_DAYS = 260
MIN_BARS = 30
ATR_MULT = 1.2
RR_MIN = 1.0
# Conservative trade-plan guards (short 3-5D):
# - Don't place a stop that is close enough to be hit by ordinary noise.
# - Don't accept a "support" that is only 0.5% below price if that zone is
#   actually just the daily noise band rather than a structural shelf.
# - Don't present a target that is too close to overwhelm RR, and if volume is
#   dry, be more conservative about how high a target we claim.
MIN_STOP_DIST_PCT = 3.0          # at least 3% below current to be a real stop zone
MAX_STOP_DIST_PCT = 12.0         # beyond this the support is too far / falling knife
NOISE_BUF = 4.0                  # high-ATR names need at least a few % buffer from noise
MIN_TP_DIST_PCT = 4.0            # target should be at least ~4% away, else it's noise
MAX_TP_DIST_PCT = 25.0           # don't promise a moonshot
# We treat the first take-profit as the nearest resistance; if absent, use
# ATR-based extension.  Second target is the second resistance or ATR*2.
MAX_POSITION_PCT = 20.0
BASE_RISK_PCT = 1.0


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = re.sub(r"[^\d.\-+eE]", "", value.strip())
        result = float(value)
        if not math.isfinite(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def _standardize_hist(hist_df: pd.DataFrame | None) -> pd.DataFrame:
    if hist_df is None or hist_df.empty:
        return pd.DataFrame()
    frame = hist_df.copy()
    col_map = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
    }
    renamed = {k: v for k, v in col_map.items() if k in frame.columns}
    if "date" not in renamed and "日期" not in frame.columns:
        return pd.DataFrame()
    frame = frame.rename(columns=renamed)
    if "date" not in frame.columns:
        return pd.DataFrame()
    frame[["open", "close", "high", "low"]] = frame[["open", "close", "high", "low"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if "volume" in frame.columns:
        frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    if "amount" in frame.columns:
        frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = (
        frame.dropna(subset=["date", "close"])
        .drop_duplicates("date", keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )
    return frame


def _calc_ema(close: pd.Series, span: int) -> float:
    if len(close) < span:
        return float("nan")
    return float(close.ewm(span=span, adjust=False).mean().iloc[-1])


def _calc_rsi(close: pd.Series, period: int = 14) -> float:
    if len(close) < period + 1:
        return float("nan")
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean().iloc[-1]
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    return float(100.0 - 100.0 / (1.0 + avg_gain / avg_loss))


def _calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    if len(close) < period + 1:
        return float("nan")
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return float(tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean().iloc[-1])


def _calc_vwap(frame: pd.DataFrame, window: int = 20) -> Optional[float]:
    """VWAP（金融口径）：Σ(typical * amount) / Σ(amount)。

    精确 VWAP 应使用成交额/成交量。因为 A 股成交量单位常为手，而成交额是金额，
    直接用 amount/volume 可能因单位口径不同产生错误，因此我们在“成交额存在且有效”
    时才用金额加权；否则退化为 typical*volume 加权；两者都没有时返回 None，
    不用 close.mean() 冒充 VWAP。
    """
    recent = frame.tail(window)
    if len(recent) < 5:
        return None
    tp = (recent["high"].astype(float) + recent["low"].astype(float) + recent["close"].astype(float)) / 3.0
    price_ok = tp.notna() & (tp > 0)
    if "amount" in recent.columns and recent["amount"].notna().sum() >= 5:
        amt = recent["amount"].astype(float)
        mask = price_ok & (amt > 0)
        if mask.sum() >= 5:
            return float((tp[mask] * amt[mask]).sum() / amt[mask].sum())
    if "volume" in recent.columns and recent["volume"].notna().sum() >= 5:
        vol = recent["volume"].astype(float)
        mask = price_ok & (vol > 0)
        if mask.sum() >= 5:
            return float((tp[mask] * vol[mask]).sum() / vol[mask].sum())
    return None


def _swing_points(hist: pd.DataFrame, lookback: int = 40, left: int = 2, right: int = 2) -> Dict[str, List[float]]:
    """Return list of recent swing lows and highs using local extrema."""
    df = hist.tail(lookback).reset_index(drop=True)
    lows: List[float] = []
    highs: List[float] = []
    if len(df) < left + right + 1:
        return {"lows": lows, "highs": highs}
    for i in range(left, len(df) - right):
        window_low = df["low"].iloc[i - left: i + right + 1]
        window_high = df["high"].iloc[i - left: i + right + 1]
        if df["low"].iloc[i] == window_low.min() and df["low"].iloc[i] > 0:
            lows.append(float(df["low"].iloc[i]))
        if df["high"].iloc[i] == window_high.max() and df["high"].iloc[i] > 0:
            highs.append(float(df["high"].iloc[i]))
    # dedupe close values
    def _dedupe(items: List[float], tolerance: float = 0.005) -> List[float]:
        out: List[float] = []
        for item in sorted(items):
            if not out or abs(item / out[-1] - 1.0) > tolerance:
                out.append(item)
        return out

    return {"lows": _dedupe(lows), "highs": _dedupe(highs)}


def _nearest_below(items: List[float], price: float, tolerance_pct: float = 5.0) -> Optional[float]:
    below = [x for x in items if x < price and (price - x) / price * 100.0 < tolerance_pct]
    return max(below) if below else None


def _nearest_above(items: List[float], price: float, tolerance_pct: float = 15.0) -> Optional[float]:
    above = [x for x in items if x > price and (x - price) / price * 100.0 < tolerance_pct]
    return min(above) if above else None


def _nearest_above_min_distance(items: List[float], price: float, min_dist_pct: float = 0.8, max_dist_pct: float = 25.0) -> Optional[float]:
    above = [
        x for x in items
        if x > price and (x - price) / price * 100.0 >= min_dist_pct
        and (x - price) / price * 100.0 <= max_dist_pct
    ]
    return min(above) if above else None


def _format_price(value: Optional[float], digits: int = 2) -> str:
    if value is None or not math.isfinite(value):
        return "N/A"
    return f"{value:.{digits}f}"


def build_trade_plan(
    symbol_code: str,
    symbol_name: str = "",
    trade_date: Optional[str] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    adjust: str = "qfq",
    risk_budget_pct: float = BASE_RISK_PCT,
) -> Dict[str, Any]:
    """Build a structured 1-5 day trade plan for one A-share symbol."""
    code = str(symbol_code or "").strip()
    match = re.search(r"(\d{6})", code)
    if not match:
        return {"symbol_code": symbol_code, "symbol_name": symbol_name, "status": "error", "error": "invalid_symbol"}
    code = match.group(1)

    if not trade_date:
        trade_date = get_latest_completed_trading_date()
        if not trade_date:
            return {"symbol_code": code, "symbol_name": symbol_name, "status": "error", "error": "no_trade_date"}

    start_date, end_date = get_trading_date_range(
        end_date=trade_date,
        count=lookback_days,
        include_end=True,
    )

    try:
        hist_df = get_stock_zh_a_hist(
            symbol=code,
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
            verbose=False,
        )
    except Exception as exc:
        logger.warning("trade_plan fetch {} failed: {}", code, exc)
        return {
            "symbol_code": code,
            "symbol_name": symbol_name,
            "trade_date": trade_date,
            "status": "error",
            "error": f"data_fetch:{type(exc).__name__}",
        }

    frame = _standardize_hist(hist_df)
    if frame.empty or len(frame) < MIN_BARS:
        return {
            "symbol_code": code,
            "symbol_name": symbol_name,
            "trade_date": trade_date,
            "status": "error",
            "error": "insufficient_history",
            "observation_count": int(len(frame)),
        }

    latest_close = float(frame["close"].iloc[-1])
    prev_close = float(frame["close"].iloc[-2]) if len(frame) >= 2 else latest_close
    high_series = frame["high"].astype(float)
    low_series = frame["low"].astype(float)
    close_series = frame["close"].astype(float)
    volume_series = frame["volume"].astype(float) if "volume" in frame else pd.Series(dtype=float)

    ema8 = _calc_ema(close_series, 8)
    ema13 = _calc_ema(close_series, 13)
    ema21 = _calc_ema(close_series, 21)
    ema50 = _calc_ema(close_series, 50)
    rsi = _calc_rsi(close_series, 14)
    atr = _calc_atr(high_series, low_series, close_series, 14)
    atr_pct = atr / latest_close * 100.0 if latest_close and not np.isnan(atr) else float("nan")
    vwap20 = _calc_vwap(frame, 20)
    vwap5 = _calc_vwap(frame, 5)

    vol5 = float(volume_series.tail(5).mean()) if len(volume_series) >= 5 and volume_series.notna().sum() > 0 else float("nan")
    vol20 = float(volume_series.tail(20).mean()) if len(volume_series) >= 20 and volume_series.notna().sum() > 0 else float("nan")
    today_vol = float(volume_series.iloc[-1]) if volume_series.notna().sum() > 0 else float("nan")
    prev_5d_vol = float(volume_series.iloc[-6:-1].mean()) if len(volume_series) >= 6 and volume_series.notna().sum() > 0 else float("nan")
    amount_series = frame["amount"].astype(float) if "amount" in frame else pd.Series(dtype=float)
    today_amount = float(amount_series.iloc[-1]) if amount_series.notna().sum() > 0 else float("nan")
    prev_5d_avg_amount = float(amount_series.iloc[-6:-1].mean()) if len(amount_series) >= 6 and amount_series.notna().sum() > 0 else float("nan")
    volume_ratio = today_vol / prev_5d_vol if prev_5d_vol and prev_5d_vol > 0 else float("nan")
    amount_ratio = today_amount / prev_5d_avg_amount if prev_5d_avg_amount and prev_5d_avg_amount > 0 else float("nan")
    volume_ma5_ma20_ratio = vol5 / vol20 if vol20 and vol20 > 0 else float("nan")

    swing = _swing_points(frame)
    supports = swing["lows"]
    resistances = swing["highs"]

    # Support: nearest swing low below price; fallback to recent N-low and then ATR.
    support_notes: list[str] = []
    recent_low20 = float(low_series.tail(20).min()) if len(low_series) >= 20 else None
    recent_low60 = float(low_series.tail(60).min()) if len(low_series) >= 60 else None
    atr_dist_pct = (atr_pct if not np.isnan(atr_pct) else 0.0)
    noise_floor = NOISE_BUF * max(1.0, atr_dist_pct / 2.0) if not np.isnan(atr_pct) else NOISE_BUF
    def _usable_support(x: Optional[float]) -> Optional[float]:
        if x is None or x <= 0:
            return None
        dist_pct = (latest_close - x) / latest_close * 100.0
        if dist_pct < MIN_STOP_DIST_PCT:
            support_notes.append(f"support_too_close:{dist_pct:.1f}%")
            return None
        if dist_pct > MAX_STOP_DIST_PCT:
            support_notes.append(f"support_too_deep:{dist_pct:.1f}%")
            return None
        # Don't rest the whole position on a zone that sits barely below us;
        # require at least a small buffer so intraday noise doesn't trigger it.
        if dist_pct < noise_floor:
            support_notes.append(f"support_in_noise:{dist_pct:.1f}%")
            return None
        return x
    support_1 = _usable_support(_nearest_below(supports, latest_close, tolerance_pct=12.0))
    support_2 = _usable_support(_nearest_below([x for x in supports if x != support_1], latest_close, tolerance_pct=15.0))
    if support_1 is None:
        support_1 = _usable_support(recent_low20)
    if support_1 is None and not np.isnan(atr) and atr > 0:
        support_1 = latest_close - max(MIN_STOP_DIST_PCT, min(MAX_STOP_DIST_PCT, 1.2 * atr_pct)) / 100.0 * latest_close
        support_notes.append("atr_fallback")
    # Resistance: never promise a target too close (noise) or too far (unreachable).
    def _usable_resistance(candidate: Optional[float]) -> Optional[float]:
        if candidate is None or candidate <= latest_close:
            return None
        dist_pct = (candidate - latest_close) / latest_close * 100.0
        if dist_pct < MIN_TP_DIST_PCT:
            return None
        if dist_pct > MAX_TP_DIST_PCT:
            support_notes.append("resistance_too_far")
            return None
        return candidate
    resistance_1 = _usable_resistance(_nearest_above_min_distance(resistances, latest_close, min_dist_pct=MIN_TP_DIST_PCT, max_dist_pct=MAX_TP_DIST_PCT))
    resistance_2 = None
    tmp = [x for x in resistances if x > latest_close and x != resistance_1]
    if tmp:
        resistance_2 = _usable_resistance(min(tmp))
    # If volume is not confirmative, a distant swing-high is less credible as a
    # 3-5D target, so we let ATR-ish realistic targets take priority.
    # volume_ratio now = 今日量 / 前5日均量(不含今日); only < 0.8 is clearly dry.
    if not np.isnan(volume_ratio) and volume_ratio < 0.8:
        support_notes.append("low_volume_breakout")

    atr_1 = latest_close + 1.5 * atr if not np.isnan(atr) else None
    atr_2 = latest_close + 2.0 * atr if not np.isnan(atr) else None
    if not resistance_1:
        resistance_1 = atr_1
    # Never let resistance_2 be lower than resistance_1; fallback to ATR extension.
    if resistance_2 is None or (resistance_1 is not None and resistance_2 <= resistance_1):
        resistance_2 = atr_2 if (atr_2 and (resistance_1 is None or atr_2 > resistance_1)) else None

    # Build plan.
    entry_zone_low = None
    entry_zone_high = None
    _vwap_valid = (
        vwap20 is not None and not np.isnan(vwap20)
        and 0.5 * latest_close < vwap20 < 2.0 * latest_close
    )
    vwap_gap_pct = None
    if _vwap_valid and vwap20:
        vwap_gap_pct = (latest_close / vwap20 - 1.0) * 100.0
    if _vwap_valid:
        entry_zone_low = min(vwap20, latest_close)
        entry_zone_high = max(vwap20, latest_close)
    elif not np.isnan(ema21) and ema21 is not None:
        entry_zone_low = min(ema21, latest_close)
        entry_zone_high = max(ema21, latest_close)
    elif not np.isnan(ema13) and ema13 is not None:
        entry_zone_low = min(ema13, latest_close)
        entry_zone_high = max(ema13, latest_close)
    else:
        entry_zone_low = latest_close
        entry_zone_high = latest_close

    stop_loss = None
    if support_1 is not None and support_1 > 0:
        stop_loss = support_1 * 0.995  # just below support
    elif atr and not np.isnan(atr) and latest_close > 0:
        stop_loss = latest_close - ATR_MULT * atr

    take_profit_1 = None
    take_profit_2 = None
    if resistance_1 is not None and resistance_1 > latest_close:
        take_profit_1 = resistance_1
    elif atr and not np.isnan(atr):
        take_profit_1 = latest_close + 1.5 * atr
    if resistance_2 is not None and resistance_2 > latest_close:
        take_profit_2 = resistance_2
    elif atr and not np.isnan(atr):
        take_profit_2 = latest_close + 2.0 * atr
    if (
        take_profit_2 is not None
        and take_profit_1 is not None
        and take_profit_2 <= take_profit_1
        and atr is not None
        and not np.isnan(atr)
    ):
        take_profit_2 = latest_close + 2.0 * atr
    if take_profit_2 is not None and take_profit_1 is not None and take_profit_2 <= take_profit_1:
        take_profit_2 = take_profit_1 * 1.03 if take_profit_1 > 0 else None

    risk_per_share = None
    reward_per_share_1 = None
    rr_1 = None
    if stop_loss is not None and take_profit_1 is not None:
        risk = latest_close - stop_loss
        reward = take_profit_1 - latest_close
        if risk > 0:
            risk_per_share = risk
            reward_per_share_1 = reward
            rr_1 = reward / risk

    rr_ok = rr_1 is not None and rr_1 >= RR_MIN
    stop_pct = (stop_loss / latest_close - 1.0) * 100.0 if stop_loss else None

    position_pct = None
    if risk_per_share and risk_per_share > 0 and latest_close > 0:
        risk_pct_of_price = risk_per_share / latest_close * 100.0
        if risk_pct_of_price > 0:
            raw_position = risk_budget_pct / risk_pct_of_price * 100.0
            # Conservative cap: never exceed max_position_pct. Also never exceed ~12% for
            # a single 1-5 day swing idea by default even if stop is tight.
            position_pct = min(MAX_POSITION_PCT, max(0.0, raw_position))
            position_pct = min(12.0, position_pct)
        else:
            position_pct = 0.0
    else:
        position_pct = 0.0

    entry_trigger = "价格回踩 VWAP/EMA 区间企稳"
    if vwap20 is not None and not np.isnan(vwap20) and latest_close >= vwap20:
        entry_trigger = "回踩 VWAP/EMA 附近企稳，不破支撑"
    elif latest_close > 0 and (prev_close > 0) and latest_close > prev_close:
        entry_trigger = "强势站上近期均线，缩量回踩入场"

    ema_stack_bullish = (
        not np.isnan(ema8)
        and not np.isnan(ema13)
        and not np.isnan(ema21)
        and ema8 > ema13 > ema21
    )
    # Simplify: use price structure directly; no MA5 slope dependency here.
    hh_hl_proxy = bool(close_series.tail(3).is_monotonic_increasing)

    plan = {
        "symbol_code": code,
        "symbol_name": symbol_name or "",
        "trade_date": trade_date,
        "status": "ok",
        "close": round(latest_close, 2),
        "prev_close": round(prev_close, 2),
        "change_pct": round((latest_close / prev_close - 1.0) * 100.0, 2) if prev_close > 0 else None,
        "indicators": {
            "rsi": None if np.isnan(rsi) else round(rsi, 1),
            "vwap_20": None if vwap20 is None or np.isnan(vwap20) else round(vwap20, 2),
            "vwap_5": None if vwap5 is None or np.isnan(vwap5) else round(vwap5, 2),
            "ema8": None if np.isnan(ema8) else round(ema8, 2),
            "ema13": None if np.isnan(ema13) else round(ema13, 2),
            "ema21": None if np.isnan(ema21) else round(ema21, 2),
            "ema50": None if np.isnan(ema50) else round(ema50, 2),
            "ema_stack_bullish": ema_stack_bullish,
            "atr": None if np.isnan(atr) else round(atr, 3),
            "atr_pct": None if np.isnan(atr_pct) else round(atr_pct, 3),
            "volume_ratio": None if np.isnan(volume_ratio) else round(volume_ratio, 2),
            "amount_ratio": None if np.isnan(amount_ratio) else round(amount_ratio, 2),
            "volume_ma5_ma20_ratio": None if np.isnan(volume_ma5_ma20_ratio) else round(volume_ma5_ma20_ratio, 2),
            "vwap_gap_pct": None if vwap_gap_pct is None else round(vwap_gap_pct, 2),
            "hh_hl_proxy": hh_hl_proxy,
        },
        "levels": {
            "support_1": None if support_1 is None else round(support_1, 2),
            "support_2": None if support_2 is None else round(support_2, 2),
            "resistance_1": None if resistance_1 is None else round(resistance_1, 2),
            "resistance_2": None if resistance_2 is None else round(resistance_2, 2),
            "recent_low_20": None if recent_low20 is None else round(float(recent_low20), 2),
            "recent_low_60": None if recent_low60 is None else round(float(recent_low60), 2),
        },
        "plan": {
            "entry_zone_low": None if entry_zone_low is None else round(float(entry_zone_low), 2),
            "entry_zone_high": None if entry_zone_high is None else round(float(entry_zone_high), 2),
            "entry_trigger": entry_trigger,
            "stop_loss": None if stop_loss is None else round(float(stop_loss), 2),
            "stop_loss_pct": None if stop_loss is None else round(float(stop_pct), 2),
            "take_profit_1": None if take_profit_1 is None else round(float(take_profit_1), 2),
            "take_profit_2": None if take_profit_2 is None else round(float(take_profit_2), 2),
            "reward_per_share_1": None if reward_per_share_1 is None else round(float(reward_per_share_1), 3),
            "risk_per_share": None if risk_per_share is None else round(float(risk_per_share), 3),
            "rr_1": None if rr_1 is None else round(rr_1, 2),
            "rr_ok": bool(rr_ok),
            "suggested_position_size_pct": None if position_pct is None else round(float(position_pct), 2),
            "invalidation": "收盘跌破止损位（支撑 1 下方约 0.5%）",
            "entry_state": "weak_to_strong" if _vwap_valid and latest_close >= vwap20 else "pullback_watch",
        },
        "risk": {
            "risk_budget_pct": risk_budget_pct,
            "atr_pct": None if np.isnan(atr_pct) else round(atr_pct, 3),
            "max_position_pct": MAX_POSITION_PCT,
        },
        "horizon": "1-5 天",
        "notes": [
            "RSI>75 或昨日涨幅过大时谨慎追高",
            "VWAP 下方且无支撑时避免左侧买入",
            "止损至少放在支撑下方 0.5%",
        ] + support_notes,
    }
    return plan


def evaluate_trade_plan_quality(
    plan: Dict[str, Any],
    require_rr_min: float = 1.0,
    require_stop_loss: bool = True,
    avoid_below_vwap: bool = True,
    max_stop_loss_pct: float = -8.0,
    require_volume_ratio_min: float = 1.0,
    require_rsi_max: float = 70.0,
    signal_group: str = "",
    signal: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Grade a generated trade plan for suitability as an actionable buy.

    Gray-scale by default: returns pass flag + reasons; does NOT mutate anything
    by itself.  Use it in reporting/backtest to compare plan-pass vs plan-fail.

    规划职责分离：RR/止损/信号档是“交易计划硬门”，VWAP/量比/MA5 等转强信号
    只交给 score_weak_to_strong，价格/风险回报只交给 score_entry_quality，
    避免因子在同一计划里重复计权。
    """
    if not plan or plan.get("status") != "ok":
        return {
            "trade_plan_pass": False,
            "trade_plan_reject_reasons": ["plan_unavailable"],
            "trade_plan_notes": [],
        }
    p = plan.get("plan") or {}
    rr = p.get("rr_1")
    stop_loss = p.get("stop_loss")
    stop_loss_pct = p.get("stop_loss_pct")
    trade_signal = signal or {}
    pass_ = True
    reject: list[str] = []
    notes: list[str] = []
    entry_quality_score = 0.0
    entry_quality_reasons: list[str] = []
    weak_to_strong_score = 0.0
    weak_to_strong_reasons: list[str] = []

    # Small-sample lesson: only buy/consensus-level signals are actionable.
    _sig = str(signal_group or "").lower()
    if _sig and _sig not in {"buy_passed", "consensus", "buy", "strong"}:
        pass_ = False
        reject.append("low_signal_group")

    # 计划级硬门：RR / 止损合法性，属于“能否下单”，不属于重复评分因子
    if rr is None:
        pass_ = False
        reject.append("rr_missing")
    elif rr < require_rr_min:
        pass_ = False
        reject.append(f"rr_below_{require_rr_min}")

    if require_stop_loss and (stop_loss is None or stop_loss <= 0):
        pass_ = False
        reject.append("stop_loss_missing")

    if stop_loss_pct is not None and stop_loss_pct > 0:
        pass_ = False
        reject.append("stop_loss_above_price")

    if stop_loss_pct is not None and stop_loss_pct < max_stop_loss_pct:
        notes.append(f"wide_stop_{stop_loss_pct}")

    # 这两个维度只由专用评分模块回答，不在这里再重复硬判
    quality_score = score_entry_quality(trade_signal, trade_plan=plan, identity=trade_signal.get("strong_stock_lifecycle"))
    entry_quality_score = float(quality_score.get("entry_quality_score", 0.0) or 0.0)
    entry_quality_reasons = list(quality_score.get("entry_quality_reasons") or [])
    confirmation_score = score_weak_to_strong(
        trade_signal,
        trade_plan=plan,
        identity=trade_signal.get("strong_stock_lifecycle"),
        divergence=trade_signal.get("strong_stock_divergence"),
    )
    weak_to_strong_score = float(confirmation_score.get("weak_to_strong_score", 0.0) or 0.0)
    weak_to_strong_reasons = list(confirmation_score.get("weak_to_strong_reasons") or [])

    if entry_quality_score < 70:
        pass_ = False
        reject.append("entry_quality_below_70")
    if weak_to_strong_score < 80:
        pass_ = False
        reject.append("weak_to_strong_below_80")

    return {
        "trade_plan_pass": bool(pass_),
        "trade_plan_reject_reasons": reject,
        "trade_plan_notes": notes,
        "entry_quality_score": round(entry_quality_score, 2),
        "entry_quality_reasons": entry_quality_reasons,
        "weak_to_strong_score": round(weak_to_strong_score, 2),
        "weak_to_strong_reasons": weak_to_strong_reasons,
    }


def attach_trade_plans(
    signals: List[Dict[str, Any]],
    trade_date: Optional[str] = None,
    risk_budget_pct: float = BASE_RISK_PCT,
) -> List[Dict[str, Any]]:
    """Attach trade_plan to each signal, reuse existing technical_factor table when possible."""
    out: List[Dict[str, Any]] = []
    for signal in signals or []:
        code = str(signal.get("symbol_code") or "").strip()
        name = str(signal.get("symbol_name") or "").strip()
        plan = build_trade_plan(code, symbol_name=name, trade_date=trade_date)
        signal_group = str(signal.get("signal_group") or signal.get("buy_decision") or "")
        quality = evaluate_trade_plan_quality(plan, signal_group=signal_group, signal=signal)
        item = dict(signal)
        item["trade_plan"] = plan
        item["trade_plan_pass"] = quality.get("trade_plan_pass", False)
        item["trade_plan_reject_reasons"] = quality.get("trade_plan_reject_reasons", [])
        item["trade_plan_notes"] = quality.get("trade_plan_notes", [])
        item["entry_quality_score"] = quality.get("entry_quality_score", 0.0)
        item["entry_quality_reasons"] = quality.get("entry_quality_reasons", [])
        item["weak_to_strong_score"] = quality.get("weak_to_strong_score", 0.0)
        item["weak_to_strong_reasons"] = quality.get("weak_to_strong_reasons", [])
        out.append(item)
    return out


def format_trade_plan_markdown(plan: Dict[str, Any]) -> str:
    if not plan:
        return "交易计划: 无"
    if plan.get("status") != "ok":
        return f"交易计划: 不可用 ({plan.get('error', plan.get('status', 'unknown'))})"
    inds = plan.get("indicators") or {}
    lv = plan.get("levels") or {}
    p = plan.get("plan") or {}
    return (
        f"RSI={inds.get('rsi', 'N/A')}, "
        f"VWAP20={inds.get('vwap_20', 'N/A')}, "
        f"EMA8/13/21={inds.get('ema8', 'N/A')}/{inds.get('ema13', 'N/A')}/{inds.get('ema21', 'N/A')}, "
        f"量比={inds.get('volume_ratio', 'N/A')}, "
        f"额比={inds.get('amount_ratio', 'N/A')}, "
        f"量趋势={inds.get('volume_ma5_ma20_ratio', 'N/A')}, "
        f"支撑1/2={lv.get('support_1', 'N/A')}/{lv.get('support_2', 'N/A')}, "
        f"压力1/2={lv.get('resistance_1', 'N/A')}/{lv.get('resistance_2', 'N/A')}, "
        f"入场区={p.get('entry_zone_low', 'N/A')}-{p.get('entry_zone_high', 'N/A')}, "
        f"止损={p.get('stop_loss', 'N/A')}({p.get('stop_loss_pct', '')}%), "
        f"目标1/2={p.get('take_profit_1', 'N/A')}/{p.get('take_profit_2', 'N/A')}, "
        f"RR={p.get('rr_1', 'N/A')}, "
        f"仓位建议={p.get('suggested_position_size_pct', 'N/A')}%"
    )
