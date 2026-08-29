"""T 日候选池：发现机会，不决定买入。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from strategies.main_trend.portfolio import apply_theme_caps, theme_of, theme_summary
from strategies.main_trend.scoring import compute_pre_score, compute_stops


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        result = float(value)
        if result != result:
            return default
        return result
    except (TypeError, ValueError):
        return default


def price_context_from_factor(factor: Dict[str, Any]) -> Dict[str, Any]:
    close = _num(factor.get("close"))
    atr = _num(factor.get("atr"))
    atr_pct = _num(factor.get("atr_pct"))
    ma20 = _num(factor.get("ma20"))
    dev = _num(factor.get("ma20_deviation_pct"))
    if ma20 is None and close and dev is not None and abs(dev) < 80:
        ma20 = close / (1.0 + dev / 100.0)
    return {
        "close": close,
        "atr": atr,
        "atr_pct": atr_pct,
        "ma20": ma20,
        "ma20_deviation_pct": dev,
    }


def scoring_weights(scoring_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    cfg = scoring_cfg or {}
    return {
        "trend": float(cfg.get("trend_weight", 0.40) or 0.40),
        "sector": float(cfg.get("sector_weight", 0.25) or 0.25),
        "market_sentiment": float(cfg.get("market_sentiment_weight", 0.15) or 0.15),
        "hot_money": float(cfg.get("hot_money_weight", 0.10) or 0.10),
        "catalyst": float(cfg.get("catalyst_weight", 0.10) or 0.10),
    }


def build_tday_row(
    *,
    symbol_code: str,
    symbol_name: str,
    trade_date: str,
    trend_state: str,
    quality_score: Optional[float],
    sector_score: Optional[float],
    sector_grade: str,
    sector_name: str,
    market_sentiment_score: Optional[float] = None,
    hot_money_score: Optional[float] = None,
    catalyst_score: Optional[float] = None,
    has_event: bool = False,
    factor: Optional[Dict[str, Any]] = None,
    raw_position_pct: float = 0.0,
    scoring_cfg: Optional[Dict[str, Any]] = None,
    holding_cfg: Optional[Dict[str, Any]] = None,
    reference_price: Optional[float] = None,
) -> Dict[str, Any]:
    factor = factor or {}
    ctx = price_context_from_factor(factor)
    ref = reference_price if reference_price is not None else ctx.get("close")
    hold = holding_cfg or {}
    scores = compute_pre_score(
        trend_state=trend_state,
        quality_score=quality_score,
        sector_score=sector_score,
        sector_grade=sector_grade,
        market_sentiment_score=market_sentiment_score,
        hot_money_score=hot_money_score,
        catalyst_score=catalyst_score,
        has_event=has_event,
        weights=scoring_weights(scoring_cfg),
    )
    stops = compute_stops(
        ref,
        atr=ctx.get("atr"),
        atr_pct=ctx.get("atr_pct"),
        ma20=ctx.get("ma20"),
        ma20_deviation_pct=ctx.get("ma20_deviation_pct"),
        initial_atr_mult=float(hold.get("initial_atr_mult", 2.5) or 2.5),
        trail_atr_mult=float(hold.get("atr_trailing_mult", 3.0) or 3.0),
    )
    theme = theme_of(sector_name, symbol_name)
    return {
        "symbol_code": symbol_code,
        "symbol_name": symbol_name,
        "trade_date": trade_date,
        "trend_state": trend_state,
        "trend_grade": scores["trend_grade"],
        "trend_score": scores["trend_score"],
        "sector_name": sector_name,
        "sector_grade": scores["sector_grade"] if scores["sector_grade"] else sector_grade,
        "sector_score": scores["sector_score"],
        "market_sentiment_grade": scores["market_sentiment_grade"],
        "market_sentiment_score": scores["market_sentiment_score"],
        "hot_money_grade": scores["hot_money_grade"],
        "hot_money_score": scores["hot_money_score"],
        "catalyst_grade": scores["catalyst_grade"],
        "catalyst_score": scores["catalyst_score"],
        "pre_score": scores["pre_score"],
        "theme": theme,
        "reference_price": stops.get("reference_price"),
        "entry_price": None,
        "initial_stop": stops.get("initial_stop"),
        "initial_stop_pct": stops.get("initial_stop_pct"),
        "trailing_stop": stops.get("trailing_stop"),
        "target_price_1": stops.get("target_price_1"),
        "target_price_2": stops.get("target_price_2"),
        "target_method": stops.get("target_method"),
        "highest_close": stops.get("highest_close"),
        "current_stop": stops.get("current_stop"),
        "ma20": stops.get("ma20"),
        "atr": stops.get("atr"),
        "atr_pct": ctx.get("atr_pct"),
        "raw_position_pct": round(float(raw_position_pct or 0.0), 2),
        "t1_state": "WAIT",
        "action": "WAIT",
    }


def finalize_tday_pool(
    rows: List[Dict[str, Any]],
    *,
    portfolio_cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cfg = portfolio_cfg or {}
    capped = apply_theme_caps(
        rows,
        theme_cap_pct=float(cfg.get("theme_cap_pct", 12.0) or 12.0),
        max_names_per_theme=int(cfg.get("max_names_per_theme", 3) or 3),
        position_key="raw_position_pct",
        score_key="pre_score",
    )
    single_cap = float(cfg.get("max_position_pct", 8.0) or 8.0)
    for row in capped:
        sized = float(row.get("suggested_position_pct") or 0.0)
        if sized > single_cap:
            row["suggested_position_pct"] = round(single_cap, 2)
            if row.get("portfolio_state") == "OK":
                row["portfolio_state"] = "SINGLE_TRIM"
        row["t1_state"] = "WAIT"
        row["action"] = "WAIT"
    capped.sort(key=lambda r: float(r.get("pre_score") or 0), reverse=True)
    return {
        "phase": "tday",
        "note": "T日只发现机会，不产生 BUY。价格是 Reference Price，不是 Entry。",
        "count": len(capped),
        "pool": capped,
        "themes": theme_summary(capped),
    }


def rebuild_from_result(result: Dict[str, Any], *, scoring_cfg=None, holding_cfg=None, portfolio_cfg=None) -> Dict[str, Any]:
    """从已有 result.json 重建 T 日表（不必重扫全市场）。"""
    discovery = result.get("discovery") or {}
    signals = {str(s.get("symbol_code")): s for s in (result.get("buy_signals") or [])}
    rows = []
    for cand in discovery.get("eligible") or []:
        code = str(cand.get("symbol_code") or "")
        sig = signals.get(code) or {}
        quality = ((cand.get("trend_quality_info") or {}) or {}).get("score")
        sector = cand.get("sector_state") or {}
        sentiment = cand.get("market_sentiment_state") or {}
        hot_money = cand.get("hot_money_state") or {}
        catalyst = cand.get("catalyst_state") or {}
        exec_detail = (((sig.get("gates") or {}).get("execution") or {}).get("detail") or {})
        nested = exec_detail.get("detail") or {}
        price = _num(nested.get("price")) or _num(exec_detail.get("price"))
        risk = (((sig.get("gates") or {}).get("risk") or {}).get("detail") or {})
        atr_abs = _num(risk.get("stop_distance_abs"))
        stop_mult = 2.5
        atr = (atr_abs / stop_mult) if atr_abs else None
        factor = {
            "close": price,
            "atr": atr,
            "atr_pct": None,
        }
        if price and _num(risk.get("stop_distance_pct")):
            factor["atr_pct"] = float(risk["stop_distance_pct"]) / stop_mult
        rows.append(
            build_tday_row(
                symbol_code=code,
                symbol_name=str(cand.get("symbol_name") or ""),
                trade_date=str(cand.get("trade_date") or result.get("trade_date") or ""),
                trend_state=str(cand.get("trend_state") or "S0"),
                quality_score=quality,
                sector_score=_num(sector.get("score")),
                sector_grade=str(sector.get("grade") or ""),
                sector_name=str(cand.get("sector_name") or sector.get("sector_name") or ""),
                market_sentiment_score=_num(sentiment.get("score")),
                hot_money_score=_num(hot_money.get("score")),
                catalyst_score=_num(catalyst.get("score"), cand.get("catalyst_score")),
                has_event=bool(catalyst.get("has_event")),
                factor=factor,
                raw_position_pct=float(sig.get("suggested_position_pct") or risk.get("suggested_position_pct") or 0.0),
                scoring_cfg=scoring_cfg,
                holding_cfg=holding_cfg,
                reference_price=price,
            )
        )
    out = finalize_tday_pool(rows, portfolio_cfg=portfolio_cfg)
    out["trade_date"] = str(result.get("trade_date") or "")
    out["rebuilt"] = True
    return out
