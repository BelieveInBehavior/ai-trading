"""
基于 akshare 的技术指标数据源
纯量化计算，不使用任何 LLM 调用
计算主要指数和活跃个股的技术指标：日线/周线 MA, RSI, MACD, 布林带, ATR, 量比和相对强度
"""
import pandas as pd
import numpy as np
import asyncio
import traceback
from datetime import datetime
from data_source.data_source_base import DataSourceBase
from utils.akshare_utils import akshare_cached
from utils.cn_price_provider import get_index_daily, get_stock_zh_a_hist
from utils.data_quality import normalize_market_frame
from loguru import logger
from utils.date_utils import get_latest_completed_trading_date, get_trading_date_range


KLINE_DAYS = 260
CACHE_VERSION = "technical_indicators_akshare_v5_volratio_fix"


def _compute_rsi(closes: pd.Series, period: int = 14) -> float:
    """计算RSI指标"""
    try:
        if len(closes) < period + 1:
            return float('nan')
        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=period, min_periods=period).mean().iloc[-1]
        avg_loss = loss.rolling(window=period, min_periods=period).mean().iloc[-1]
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
    except Exception:
        return float('nan')


def _compute_macd(closes: pd.Series) -> tuple[float, float, float]:
    """计算MACD指标 (DIF, DEA, MACD柱)"""
    try:
        if len(closes) < 26:
            return (float('nan'), float('nan'), float('nan'))
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd_hist = 2 * (dif - dea)
        return (float(dif.iloc[-1]), float(dea.iloc[-1]), float(macd_hist.iloc[-1]))
    except Exception:
        return (float('nan'), float('nan'), float('nan'))


def _compute_bollinger(closes: pd.Series, period: int = 20) -> tuple[float, float, float]:
    """计算布林带 (上轨, 中轨, 下轨)"""
    try:
        if len(closes) < period:
            return (float('nan'), float('nan'), float('nan'))
        mid = closes.rolling(window=period).mean().iloc[-1]
        std = closes.rolling(window=period).std().iloc[-1]
        upper = mid + 2 * std
        lower = mid - 2 * std
        return (float(upper), float(mid), float(lower))
    except Exception:
        return (float('nan'), float('nan'), float('nan'))


def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    """计算ATR(平均真实波幅)"""
    try:
        if len(close) < period + 1:
            return float('nan')
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period, min_periods=period).mean().iloc[-1]
        return float(atr)
    except Exception:
        return float('nan')


def format_stock_technical_factor_line(factor: dict) -> str:
    def fmt(value, digits: int, signed: bool = False) -> str:
        if value is None or pd.isna(value):
            return "N/A"
        sign = "+" if signed else ""
        return f"{float(value):{sign}.{digits}f}"

    change_pct = factor.get("change_pct")
    change_str = f"{fmt(change_pct, 2, signed=True)}%" if change_pct is not None and not pd.isna(change_pct) else "N/A"
    close_above_ma5 = factor.get('close_above_ma5')
    ret5 = factor.get('ret_5d_pct')
    breakout = factor.get('breakout_20d')
    return (
        f"{factor.get('symbol_name')}({factor.get('symbol_code')}): "
        f"收盘{fmt(factor.get('close'), 2)}, "
        f"涨跌幅{change_str}, "
        f"MA5{'上' if close_above_ma5 else '下'}, "
        f"MA20距离{fmt(factor.get('ma20_deviation_pct'), 1, signed=True)}%, "
        f"5日{fmt(ret5, 1, signed=True)}%, "
        f"20日突破={'是' if breakout else '否'}, "
        f"RSI={fmt(factor.get('rsi'), 1)}, "
        f"MACD={fmt(factor.get('macd'), 3)}, "
        f"量比={fmt(factor.get('volume_ratio'), 2)}, "
        f"额比={fmt(factor.get('amount_ratio'), 2)}, "
        f"短线分={fmt(factor.get('short_setup_score'), 1)}, "
        f"量趋势={fmt(factor.get('volume_ma5_ma20_ratio'), 2)}, "
        f"布林={factor.get('bollinger')}"
    )


def _prepare_price_frame(
    frame: pd.DataFrame | None,
    date_columns: tuple[str, ...],
    close_columns: tuple[str, ...],
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["date", "close"])

    date_column = next((column for column in date_columns if column in frame.columns), None)
    close_column = next((column for column in close_columns if column in frame.columns), None)
    if not date_column or not close_column:
        return pd.DataFrame(columns=["date", "close"])

    prepared = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_column], errors="coerce"),
            "close": pd.to_numeric(frame[close_column], errors="coerce"),
        }
    )
    prepared = (
        prepared.dropna(subset=["date", "close"])
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    return prepared


def _return_pct(series: pd.Series, lookback: int) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) <= lookback:
        return None
    base = float(values.iloc[-lookback - 1])
    latest = float(values.iloc[-1])
    if base <= 0:
        return None
    return (latest / base - 1.0) * 100.0


def _compute_weekly_factor(price_frame: pd.DataFrame) -> dict:
    if price_frame.empty:
        return {
            "weekly_data_available": False,
            "weekly_trend": "missing",
            "weekly_trend_score": None,
        }

    weekly_close = (
        price_frame.set_index("date")["close"]
        .resample("W-FRI")
        .last()
        .dropna()
    )
    if len(weekly_close) < 20:
        return {
            "weekly_data_available": False,
            "weekly_trend": "missing",
            "weekly_trend_score": None,
            "weekly_observation_count": int(len(weekly_close)),
        }

    weekly_ma10 = weekly_close.rolling(10).mean()
    weekly_ma20 = weekly_close.rolling(20).mean()
    latest_close = float(weekly_close.iloc[-1])
    latest_ma10 = float(weekly_ma10.iloc[-1])
    latest_ma20 = float(weekly_ma20.iloc[-1])
    slope_base = weekly_ma20.iloc[-5] if len(weekly_ma20) >= 25 else weekly_ma20.iloc[0]
    slope_pct = (
        (latest_ma20 / float(slope_base) - 1.0) * 100.0
        if pd.notna(slope_base) and float(slope_base) > 0
        else None
    )

    score = 50.0
    if latest_close > latest_ma20:
        score += 15.0
    else:
        score -= 15.0
    if latest_close > latest_ma10:
        score += 8.0
    else:
        score -= 8.0
    if latest_ma10 > latest_ma20:
        score += 12.0
    else:
        score -= 12.0
    if slope_pct is not None:
        score += 15.0 if slope_pct > 0 else -15.0

    score = max(0.0, min(100.0, score))
    trend = "bullish" if score >= 65 else "bearish" if score <= 35 else "neutral"
    return {
        "weekly_data_available": True,
        "weekly_trend": trend,
        "weekly_trend_score": round(score, 2),
        "weekly_close": round(latest_close, 4),
        "weekly_ma10": round(latest_ma10, 4),
        "weekly_ma20": round(latest_ma20, 4),
        "weekly_ma20_slope_pct": round(slope_pct, 3) if slope_pct is not None else None,
        "weekly_close_vs_ma20_pct": round((latest_close / latest_ma20 - 1.0) * 100.0, 3),
        "weekly_observation_count": int(len(weekly_close)),
    }


def _compute_weinstein_phase(price_frame: pd.DataFrame) -> dict:
    """Approximate Weinstein stages from weekly closes and a 30-week average."""

    missing = {
        "weinstein_data_available": False,
        "weinstein_stage": "unknown",
        "weinstein_stage_score": None,
    }
    if price_frame.empty:
        return missing

    weekly_close = (
        price_frame.set_index("date")["close"]
        .resample("W-FRI")
        .last()
        .dropna()
    )
    if len(weekly_close) < 35:
        return {
            **missing,
            "weinstein_observation_count": int(len(weekly_close)),
        }

    weekly_ma30 = weekly_close.rolling(30).mean()
    latest_close = float(weekly_close.iloc[-1])
    latest_ma30 = float(weekly_ma30.iloc[-1])
    slope_base = weekly_ma30.iloc[-6]
    if pd.isna(slope_base) or float(slope_base) <= 0:
        return {
            **missing,
            "weinstein_observation_count": int(len(weekly_close)),
        }

    slope_pct = (latest_ma30 / float(slope_base) - 1.0) * 100.0
    close_vs_ma30_pct = (latest_close / latest_ma30 - 1.0) * 100.0
    recent_close = weekly_close.tail(8)
    recent_ma30 = weekly_ma30.tail(8)
    above_ratio = float((recent_close > recent_ma30).mean())

    if close_vs_ma30_pct > 0 and slope_pct >= 1.0:
        stage = "stage_2_uptrend"
    elif close_vs_ma30_pct < 0 and slope_pct <= -1.0:
        stage = "stage_4_decline"
    elif slope_pct <= 1.0 and close_vs_ma30_pct >= 0:
        stage = "stage_3_top"
    else:
        stage = "stage_1_base"

    score = 50.0
    score += 25.0 if stage == "stage_2_uptrend" else 0.0
    score += 15.0 if close_vs_ma30_pct > 0 else -15.0
    score += 10.0 if slope_pct > 0 else -10.0
    score = max(0.0, min(100.0, score))
    return {
        "weinstein_data_available": True,
        "weinstein_stage": stage,
        "weinstein_stage_score": round(score, 2),
        "weinstein_ma30": round(latest_ma30, 4),
        "weinstein_ma30_slope_pct": round(slope_pct, 3),
        "weinstein_close_vs_ma30_pct": round(close_vs_ma30_pct, 3),
        "weinstein_above_ma30_ratio_8w": round(above_ratio, 3),
        "weinstein_observation_count": int(len(weekly_close)),
    }


def _compute_relative_strength_factor(
    stock_frame: pd.DataFrame,
    benchmark_symbol: str = "sh000300",
    benchmark_frame: pd.DataFrame | None = None,
) -> dict:
    result = {
        "relative_strength_available": False,
        "relative_strength_benchmark": benchmark_symbol,
        "relative_strength_score": None,
        "relative_strength_20d_pct": None,
        "relative_strength_60d_pct": None,
    }
    if stock_frame.empty:
        return result

    if benchmark_frame is None:
        try:
            if not stock_frame.empty:
                start_date = stock_frame["date"].min().strftime("%Y%m%d")
                end_date = stock_frame["date"].max().strftime("%Y%m%d")
            else:
                start_date = end_date = None
            benchmark_raw = get_index_daily(
                benchmark_symbol,
                start_date=start_date,
                end_date=end_date,
                verbose=False,
            )
            benchmark_frame = _prepare_price_frame(
                benchmark_raw,
                date_columns=("date",),
                close_columns=("close",),
            )
        except Exception as exc:
            logger.warning("获取相对强度基准 {} 失败: {}", benchmark_symbol, exc)
            return result

    if benchmark_frame.empty:
        return result

    aligned = stock_frame.merge(
        benchmark_frame,
        on="date",
        how="inner",
        suffixes=("_stock", "_benchmark"),
    )
    if len(aligned) <= 60:
        return result

    stock_returns = {}
    benchmark_returns = {}
    relative_returns = {}
    for lookback in (20, 60):
        stock_return = _return_pct(aligned["close_stock"], lookback)
        benchmark_return = _return_pct(aligned["close_benchmark"], lookback)
        if stock_return is None or benchmark_return is None:
            continue
        stock_returns[lookback] = stock_return
        benchmark_returns[lookback] = benchmark_return
        relative_returns[lookback] = stock_return - benchmark_return

    if not relative_returns:
        return result

    rs20 = relative_returns.get(20)
    rs60 = relative_returns.get(60)
    score = 50.0
    if rs20 is not None:
        score += rs20 * 2.0
    if rs60 is not None:
        score += rs60
    result.update(
        {
            "relative_strength_available": rs20 is not None and rs60 is not None,
            "relative_strength_score": round(max(0.0, min(100.0, score)), 2),
            "relative_strength_20d_pct": round(rs20, 3) if rs20 is not None else None,
            "relative_strength_60d_pct": round(rs60, 3) if rs60 is not None else None,
            "stock_return_20d_pct": round(stock_returns[20], 3) if 20 in stock_returns else None,
            "stock_return_60d_pct": round(stock_returns[60], 3) if 60 in stock_returns else None,
            "benchmark_return_20d_pct": round(benchmark_returns[20], 3) if 20 in benchmark_returns else None,
            "benchmark_return_60d_pct": round(benchmark_returns[60], 3) if 60 in benchmark_returns else None,
            "relative_strength_observation_count": int(len(aligned)),
        }
    )
    return result



def _compute_long_term_factors(closes: pd.Series, latest_close: float) -> dict:
    """MA50/MA200 偏离与 52 周高位距离，用于长期质量评估。"""
    ma = {}
    for period in (50, 200):
        if len(closes) >= period:
            avg = float(closes.rolling(period).mean().iloc[-1])
            if avg > 0:
                ma[f"ma{period}_deviation_pct"] = round((latest_close / avg - 1.0) * 100.0, 2)
            else:
                ma[f"ma{period}_deviation_pct"] = None
        else:
            ma[f"ma{period}_deviation_pct"] = None
    high52 = float(closes.tail(252).max()) if len(closes) > 0 else latest_close
    ma["distance_to_52w_high_pct"] = round((latest_close / high52 - 1.0) * 100.0, 2) if high52 > 0 else None
    ma["ma50_slope_pct"] = None
    if len(closes) >= 55:
        base = float(closes.rolling(50).mean().iloc[-6])
        latest50 = float(closes.rolling(50).mean().iloc[-1])
        if base > 0:
            ma["ma50_slope_pct"] = round((latest50 / base - 1.0) * 100.0, 2)
    return ma


def compute_stock_technical_factor_from_history(
    hist_df: pd.DataFrame | None,
    symbol_code: str,
    symbol_name: str,
    trade_date: str,
    relative_strength_benchmark: str = "sh000300",
    benchmark_frame: pd.DataFrame | None = None,
) -> dict | None:
    """Compute multi-timeframe factors from an already fetched daily history."""
    code = str(symbol_code or "").strip()
    code_match = pd.Series([code]).astype(str).str.extract(r"(\d{6})", expand=False).iloc[0]
    if pd.isna(code_match) or not code_match or hist_df is None or hist_df.empty:
        return None
    code = code_match.zfill(6)
    if not {"日期", "开盘", "收盘", "最高", "最低", "成交量"}.issubset(hist_df.columns):
        return None

    hist_df, quality_report = normalize_market_frame(
        hist_df,
        as_of_date=trade_date,
        min_rows=20,
        require_ohlcv=True,
    )
    if not quality_report.valid:
        logger.warning(
            "拒绝 {} 技术因子: {}",
            symbol_code,
            ",".join(quality_report.errors),
        )
        return None

    hist_df = hist_df.sort_values("日期").reset_index(drop=True)
    price_frame = _prepare_price_frame(
        hist_df,
        date_columns=("日期", "date"),
        close_columns=("收盘", "close"),
    )
    closes = pd.to_numeric(hist_df["收盘"], errors="coerce")
    highs = pd.to_numeric(hist_df["最高"], errors="coerce")
    lows = pd.to_numeric(hist_df["最低"], errors="coerce")
    volumes = pd.to_numeric(hist_df["成交量"], errors="coerce")

    if closes.dropna().shape[0] < 20:
        return None

    current_close = float(closes.iloc[-1])
    if "涨跌幅" in hist_df.columns:
        change_pct = pd.to_numeric(hist_df["涨跌幅"].iloc[-1], errors="coerce")
        change_pct = None if pd.isna(change_pct) else float(change_pct)
    else:
        change_pct = None

    ma20 = float(closes.rolling(20).mean().iloc[-1])
    ma20_dist = (current_close - ma20) / ma20 * 100 if ma20 > 0 else float("nan")
    rsi = _compute_rsi(closes, 14)
    dif, dea, macd_hist = _compute_macd(closes)
    atr = _compute_atr(highs, lows, closes, 14)
    atr_pct = atr / current_close * 100.0 if current_close > 0 and not np.isnan(atr) else float("nan")
    daily_returns = closes.pct_change().dropna()
    daily_volatility_20d_pct = (
        float(daily_returns.tail(20).std(ddof=0) * 100.0)
        if len(daily_returns) >= 10
        else float("nan")
    )

    today_vol = float(volumes.iloc[-1]) if len(volumes) >= 1 else float("nan")
    prev_5d_vol = float(volumes.iloc[-6:-1].mean()) if len(volumes) >= 6 else float("nan")
    vol_5 = float(volumes.tail(5).mean())
    vol_20 = float(volumes.tail(20).mean())
    amounts_series = (
        pd.to_numeric(hist_df["成交额"], errors="coerce")
        if "成交额" in hist_df.columns
        else pd.Series(dtype=float)
    )
    today_amount = float(amounts_series.iloc[-1]) if len(amounts_series) >= 1 else float("nan")
    prev_5d_avg_amount = float(amounts_series.iloc[-6:-1].mean()) if len(amounts_series) >= 6 else float("nan")
    volume_ratio = today_vol / prev_5d_vol if prev_5d_vol and prev_5d_vol > 0 else float("nan")
    amount_ratio = today_amount / prev_5d_avg_amount if prev_5d_avg_amount and prev_5d_avg_amount > 0 else float("nan")
    volume_ma5_ma20_ratio = vol_5 / vol_20 if vol_20 and vol_20 > 0 else float("nan")

    boll_upper, boll_mid, boll_lower = _compute_bollinger(closes, 20)
    if not np.isnan(boll_upper):
        if current_close >= boll_upper:
            boll_pos = "上轨上方"
        elif current_close >= boll_mid:
            boll_pos = "中上"
        elif current_close >= boll_lower:
            boll_pos = "中下"
        else:
            boll_pos = "下轨下方"
    else:
        boll_pos = "N/A"

    ma5 = float(closes.rolling(5).mean().iloc[-1]) if len(closes) >= 5 else float("nan")
    ma10 = float(closes.rolling(10).mean().iloc[-1]) if len(closes) >= 10 else float("nan")
    close_above_ma5 = bool(current_close > ma5) if not np.isnan(ma5) else False
    # MA5 slope: compare latest MA5 to the MA5 from 3 bars earlier (approximates初速)
    ma5_slope_base = float(closes.rolling(5).mean().iloc[-4]) if len(closes) >= 7 else float("nan")
    ma5_slope_pct = (
        (ma5 / ma5_slope_base - 1.0) * 100.0
        if not np.isnan(ma5_slope_base) and ma5_slope_base > 0
        else float("nan")
    )
    ret_1d_pct = _return_pct(closes, 1)
    ret_3d_pct = _return_pct(closes, 3)
    ret_5d_pct = _return_pct(closes, 5)
    ret_10d_pct = _return_pct(closes, 10)
    ret_20d_pct = _return_pct(closes, 20)
    recent_20d_high = float(closes.tail(20).max()) if len(closes) >= 20 else float("nan")
    recent_60d_high = float(closes.tail(60).max()) if len(closes) >= 60 else float("nan")
    close_vs_20d_high_pct = (
        (current_close / recent_20d_high - 1.0) * 100.0
        if not np.isnan(recent_20d_high) and recent_20d_high > 0
        else float("nan")
    )
    close_vs_60d_high_pct = (
        (current_close / recent_60d_high - 1.0) * 100.0
        if not np.isnan(recent_60d_high) and recent_60d_high > 0
        else float("nan")
    )
    breakout_20d = bool(
        not np.isnan(close_vs_20d_high_pct)
        and close_vs_20d_high_pct >= -0.5
    )
    breakout_60d = bool(
        not np.isnan(close_vs_60d_high_pct)
        and close_vs_60d_high_pct >= -0.5
    )

    weekly_factor = _compute_weekly_factor(price_frame)
    weinstein_factor = _compute_weinstein_phase(price_frame)
    relative_strength_factor = _compute_relative_strength_factor(
        price_frame,
        benchmark_symbol=relative_strength_benchmark,
        benchmark_frame=benchmark_frame,
    )
    daily_entry_score = 50.0
    if current_close > ma20:
        daily_entry_score += 12.0
    else:
        daily_entry_score -= 12.0
    if macd_hist > 0:
        daily_entry_score += 12.0
    else:
        daily_entry_score -= 12.0
    if volume_ratio >= 1.0:
        daily_entry_score += 8.0
    if rsi >= 75:
        daily_entry_score -= 10.0
    elif rsi < 35:
        daily_entry_score -= 4.0
    daily_entry_score = max(0.0, min(100.0, daily_entry_score))

    # T+3~T+5 short-term setup score
    short_setup_score = 50.0
    short_setup_score += 12.0 if close_above_ma5 else -12.0
    if not np.isnan(ma5_slope_pct):
        short_setup_score += 8.0 if ma5_slope_pct > 0 else -8.0
    if ret_5d_pct is not None:
        if 1.0 <= ret_5d_pct <= 10.0:
            short_setup_score += 12.0
        elif 10.0 < ret_5d_pct <= 20.0:
            short_setup_score += 8.0
        elif ret_5d_pct > 30.0:
            short_setup_score -= 10.0
        elif ret_5d_pct < 0.0:
            short_setup_score -= 12.0
        else:
            short_setup_score -= 2.0
    if change_pct is not None:
        if 3.0 <= float(change_pct) <= 15.0:
            short_setup_score += 5.0
        elif float(change_pct) > 15.0 and not breakout_60d:
            short_setup_score -= 8.0
    if not np.isnan(volume_ratio):
        if volume_ratio >= 1.2:
            short_setup_score += 6.0
        elif volume_ratio < 0.8:
            short_setup_score -= 5.0
    if not np.isnan(amount_ratio):
        if amount_ratio >= 1.2:
            short_setup_score += 4.0
    if breakout_20d:
        short_setup_score += 6.0
    short_setup_score = max(0.0, min(100.0, short_setup_score))

    # Long-term structure factors (MA50/MA200/52w, used by long_score)
    long_factors = _compute_long_term_factors(closes, current_close)

    factor = {
        "symbol_code": code,
        "symbol_name": symbol_name,
        "report_date": trade_date,
        "close": current_close,
        "change_pct": change_pct,
        "ma20_deviation_pct": None if np.isnan(ma20_dist) else round(float(ma20_dist), 1),
        "close_above_ma5": close_above_ma5,
        "ma5_slope_pct": None if np.isnan(ma5_slope_pct) else round(float(ma5_slope_pct), 3),
        "ret_1d_pct": ret_1d_pct,
        "ret_3d_pct": ret_3d_pct,
        "ret_5d_pct": ret_5d_pct,
        "ret_10d_pct": ret_10d_pct,
        "ret_20d_pct": ret_20d_pct,
        "close_vs_20d_high_pct": None if np.isnan(close_vs_20d_high_pct) else round(float(close_vs_20d_high_pct), 3),
        "close_vs_60d_high_pct": None if np.isnan(close_vs_60d_high_pct) else round(float(close_vs_60d_high_pct), 3),
        "breakout_20d": breakout_20d,
        "breakout_60d": breakout_60d,
        "short_setup_score": round(short_setup_score, 2),
        "rsi": None if np.isnan(rsi) else round(float(rsi), 1),
        "macd": None if np.isnan(macd_hist) else round(float(macd_hist), 3),
        "atr": None if np.isnan(atr) else round(float(atr), 4),
        "atr_pct": None if np.isnan(atr_pct) else round(float(atr_pct), 3),
        "daily_volatility_20d_pct": (
            None
            if np.isnan(daily_volatility_20d_pct)
            else round(float(daily_volatility_20d_pct), 3)
        ),
        "volume_ratio": None if np.isnan(volume_ratio) else round(float(volume_ratio), 2),
        "amount_ratio": None if np.isnan(amount_ratio) else round(float(amount_ratio), 2),
        "volume_ma5_ma20_ratio": None if np.isnan(volume_ma5_ma20_ratio) else round(float(volume_ma5_ma20_ratio), 2),
        "bollinger": boll_pos,
        "daily_entry_score": round(daily_entry_score, 2),
        "long_term_structure": long_factors,
        "data_quality_valid": quality_report.valid,
        "data_quality_status": quality_report.status,
        "data_quality_errors": quality_report.errors,
        "data_quality_warnings": quality_report.warnings,
        "data_quality_last_date": quality_report.last_date,
        "observation_count": int(len(hist_df)),
    }
    factor.update(weekly_factor)
    factor.update(weinstein_factor)
    factor.update(relative_strength_factor)
    factor["source_line"] = format_stock_technical_factor_line(factor)
    return factor


def compute_stock_technical_factor(
    symbol_code: str,
    symbol_name: str,
    trade_date: str,
    start_date: str | None = None,
    end_date: str | None = None,
    adjust: str = "qfq",
    relative_strength_benchmark: str = "sh000300",
) -> dict | None:
    """拉取单只股票 K 线并计算与技术指标报告一致的因子。"""
    code = str(symbol_code or "").strip()
    code_match = pd.Series([code]).astype(str).str.extract(r"(\d{6})", expand=False).iloc[0]
    if pd.isna(code_match) or not code_match:
        return None
    code = code_match.zfill(6)

    if not start_date or not end_date:
        start_date, end_date = get_trading_date_range(
            end_date=trade_date,
            count=KLINE_DAYS,
            include_end=True,
        )

    hist_df = get_stock_zh_a_hist(
        symbol=code,
        start_date=start_date,
        end_date=end_date,
        adjust=adjust,
        verbose=False,
    )

    if hist_df is None or hist_df.empty or len(hist_df) < 20:
        return None

    return compute_stock_technical_factor_from_history(
        hist_df=hist_df,
        symbol_code=symbol_code,
        symbol_name=symbol_name,
        trade_date=trade_date,
        relative_strength_benchmark=relative_strength_benchmark,
    )


class TechnicalIndicatorsAkshare(DataSourceBase):
    def __init__(self):
        super().__init__("technical_indicators_akshare")

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        try:
            trade_date = get_latest_completed_trading_date(trigger_time)
            df = self.get_data_cached(trigger_time)
            if (
                df is not None
                and self.cached_data_has_trade_date(df, trade_date)
                and self._has_current_cache_version(df)
                and not self._has_failed_active_stock_data(df)
            ):
                return df
            if df is not None:
                logger.warning("技术指标缓存过期或缺少活跃个股数据，重新拉取")

            logger.info(f"获取 {trade_date} 的技术指标数据")

            # 获取日期区间 (260个交易日，覆盖约20周周线和60日相对强度)
            start_date, end_date = get_trading_date_range(
                end_date=trade_date,
                count=KLINE_DAYS,
                include_end=True,
            )

            # 1. 计算大盘指数技术指标
            index_report = self._compute_index_indicators(trade_date, start_date, end_date)

            # 2. 计算活跃个股技术指标
            stock_report = self._compute_active_stock_indicators(trade_date, start_date, end_date)

            # 3. 组合报告
            report = f"<!-- cache_version:{CACHE_VERSION} -->\n\n"
            report += f"## 技术指标分析报告 ({trade_date})\n\n"
            report += index_report
            report += "\n\n"
            report += stock_report
            report = await self.maybe_web_search_supplement(
                report,
                query=f"A股技术面{trade_date}",
                trigger_time=trigger_time,
                section_title="技术指标联网补充",
            )

            data = [{
                "title": f"{trade_date}:技术指标分析报告",
                "content": report,
                "pub_time": trigger_time,
                "url": None
            }]
            df = pd.DataFrame(data)
            self.save_data_cached(trigger_time, df)
            return df

        except Exception as e:
            traceback.print_exc()
            logger.error(f"获取技术指标数据失败: {e}")
            trade_date = get_latest_completed_trading_date(trigger_time)
            return await self.akshare_web_search_fallback(
                title=f"{trade_date}:技术指标分析报告",
                query=f"A股技术面{trade_date}",
                trigger_time=trigger_time,
                section_title="技术指标联网补充",
            )

    @staticmethod
    def _has_failed_active_stock_data(df: pd.DataFrame) -> bool:
        """Return True when cached report only contains a failed active-stock section."""
        try:
            content = "\n".join(str(x) for x in df.get("content", []))
        except Exception:
            return False
        return (
            "### 活跃个股技术面" in content
            and (
                "获取失败:" in content
                or "无法获取个股实时数据" in content
                or "数据缺少成交额字段" in content
            )
        )

    @staticmethod
    def _has_current_cache_version(df: pd.DataFrame) -> bool:
        try:
            content = "\n".join(str(x) for x in df.get("content", []))
        except Exception:
            return False
        return f"cache_version:{CACHE_VERSION}" in content

    def _compute_index_indicators(self, trade_date: str, start_date: str, end_date: str) -> str:
        """计算三大指数的技术指标"""
        indices = {
            "sh000001": "上证指数",
            "sz399006": "创业板指",
            "sh000688": "科创50",
        }

        start_dt = pd.to_datetime(start_date, format='%Y%m%d')
        end_dt = pd.to_datetime(end_date, format='%Y%m%d')

        lines = ["### 大盘指数技术面"]

        for symbol, name in indices.items():
            try:
                df = akshare_cached.run(
                    func_name="stock_zh_index_daily",
                    func_kwargs={"symbol": symbol},
                    verbose=False
                )

                if df is None or df.empty:
                    lines.append(f"{name}: 数据获取失败")
                    continue

                df['date'] = pd.to_datetime(df['date'])
                df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)].sort_values('date').reset_index(drop=True)

                if len(df) < 20:
                    lines.append(f"{name}: 数据不足")
                    continue

                closes = df['close'].astype(float)
                highs = df['high'].astype(float)
                lows = df['low'].astype(float)
                volumes = df['volume'].astype(float)

                current_close = float(closes.iloc[-1])

                # MA
                ma5 = float(closes.rolling(5).mean().iloc[-1])
                ma10 = float(closes.rolling(10).mean().iloc[-1])
                ma20 = float(closes.rolling(20).mean().iloc[-1])
                ma60 = float(closes.rolling(60).mean().iloc[-1]) if len(closes) >= 60 else float('nan')

                # MA 状态判定
                def ma_status(current, ma_val):
                    if np.isnan(ma_val):
                        return "N/A"
                    diff_pct = (current - ma_val) / ma_val * 100
                    if abs(diff_pct) < 0.3:
                        return "交叉"
                    elif current > ma_val:
                        return "多头"
                    else:
                        return "空头"

                # RSI
                rsi = _compute_rsi(closes, 14)

                # MACD
                dif, dea, macd_hist = _compute_macd(closes)

                # 量比 = 当日量 / 前5日均量(不含当日); 额比 = 当日额/前5日均额; 量趋势 = MA5/MA20
                today_vol = float(volumes.iloc[-1]) if len(volumes) >= 1 else float('nan')
                prev_5d_vol = float(volumes.iloc[-6:-1].mean()) if len(volumes) >= 6 else float('nan')
                vol_5 = float(volumes.tail(5).mean())
                vol_20 = float(volumes.tail(20).mean())
                volume_ratio = today_vol / prev_5d_vol if prev_5d_vol and prev_5d_vol > 0 else float('nan')
                amount_ratio = float('nan')
                volume_ma5_ma20_ratio = vol_5 / vol_20 if vol_20 and vol_20 > 0 else float('nan')

                # ATR
                atr = _compute_atr(highs, lows, closes, 14)

                # 布林带
                boll_upper, boll_mid, boll_lower = _compute_bollinger(closes, 20)
                if not np.isnan(boll_upper):
                    if current_close >= boll_upper:
                        boll_pos = "上轨上方"
                    elif current_close >= boll_mid:
                        boll_pos = "中轨上方"
                    elif current_close >= boll_lower:
                        boll_pos = "中轨下方"
                    else:
                        boll_pos = "下轨下方"
                else:
                    boll_pos = "N/A"

                line = (
                    f"{name}: 收盘{current_close:.2f}, "
                    f"MA5={ma5:.2f}({ma_status(current_close, ma5)}), "
                    f"MA10={ma10:.2f}({ma_status(current_close, ma10)}), "
                    f"MA20={ma20:.2f}({ma_status(current_close, ma20)}), "
                    f"RSI={rsi:.1f}, "
                    f"MACD={macd_hist:.3f}(DIF={dif:.3f},DEA={dea:.3f}), "
                    f"量比={volume_ratio:.2f}, "
                    f"额比={amount_ratio:.2f}, "
                    f"量趋势={volume_ma5_ma20_ratio:.2f}, "
                    f"ATR={atr:.2f}, "
                    f"布林={boll_pos}"
                )
                lines.append(line)

            except Exception as e:
                logger.error(f"计算{name}技术指标失败: {e}")
                lines.append(f"{name}: 计算失败({str(e)})")

        return "\n".join(lines)

    def _compute_active_stock_indicators(self, trade_date: str, start_date: str, end_date: str) -> str:
        """获取成交额前20活跃个股并计算技术指标"""
        lines = ["### 活跃个股技术面 (成交额前20)"]

        try:
            # 获取当日成交额排名前20的个股
            spot_df = akshare_cached.run(
                func_name="stock_zh_a_spot_em",
                func_kwargs={},
                verbose=False
            )

            if spot_df is None or spot_df.empty:
                lines.append("无法获取个股实时数据")
                return "\n".join(lines)

            # 按成交额降序排列取前20
            if '成交额' in spot_df.columns:
                spot_df = spot_df.copy()
                spot_df['成交额'] = pd.to_numeric(spot_df['成交额'], errors="coerce")
                spot_df = spot_df.dropna(subset=['成交额'])
                spot_df = spot_df.sort_values('成交额', ascending=False).head(20)
            else:
                lines.append("数据缺少成交额字段")
                return "\n".join(lines)

            for _, row in spot_df.iterrows():
                try:
                    code = str(row['代码']).zfill(6)
                    name = row['名称']
                    spot_change_pct = pd.to_numeric(row.get('涨跌幅', float('nan')), errors="coerce")

                    factor = compute_stock_technical_factor(
                        symbol_code=code,
                        symbol_name=name,
                        trade_date=trade_date,
                        start_date=start_date,
                        end_date=end_date,
                        adjust="qfq",
                    )
                    if not factor:
                        lines.append(f"{name}({code}): 历史数据不足")
                        continue

                    if factor.get("change_pct") is None and not pd.isna(spot_change_pct):
                        factor["change_pct"] = float(spot_change_pct)
                        factor["source_line"] = format_stock_technical_factor_line(factor)

                    lines.append(factor["source_line"])

                except Exception as e:
                    logger.warning(f"计算个股{row.get('名称', '?')}技术指标失败: {e}")
                    continue

        except Exception as e:
            logger.error(f"获取活跃个股数据失败: {e}")
            lines.append(f"获取失败: {str(e)}")

        return "\n".join(lines)


if __name__ == "__main__":
    ti = TechnicalIndicatorsAkshare()
    df = asyncio.run(ti.get_data("2026-08-07 09:00:00"))
    if not df.empty:
        print(df.content.values[0])
    else:
        print("No data returned")
