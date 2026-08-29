#!/usr/bin/env python3
"""Parameter research layer for main_trend 1~5 day short-sprint swing rules.

This script intentionally does **not** modify the production main_trend state
machine.  It extracts the core research questions into a compact parameter
matrix:

  - SMA vs EMA
  - fast/mid/long moving-average trend skeleton
  - optional MACD entry confirmation
  - fast-MA break partial reduce
  - mid-MA hard exit
  - ATR trailing exit
  - max holding days
  - max distance from fast MA at entry

It tries to import vectorbt for future compatibility, but the current project
does not require vectorbt.  When vectorbt is unavailable, the script uses a
strict pandas event simulator with T-day signal -> T+1 open entry -> next-day
open exit after close-based exit signals.

Examples:
  .venv/bin/python scripts/main_trend_vectorbt_research.py \\
      --start 20260601 --end 20260818 \\
      --symbols 600988,601899,600547 \\
      --output-dir agents_workspace_main_trend_research

  .venv/bin/python scripts/main_trend_vectorbt_research.py \\
      --start 20260601 --end 20260818 \\
      --from-tday agents_workspace_main_trend/20260824/tday_pool.json

  .venv/bin/python scripts/main_trend_vectorbt_research.py \\
      --start 20260601 --end 20260818 \\
      --from-event-dir agents_workspace_main_trend_event
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def _vectorbt_available() -> bool:
    try:
        import vectorbt  # noqa: F401

        return True
    except Exception:
        return False


def _compact_date(value: Any) -> str:
    return str(value or "").strip().replace("-", "").replace("/", "")


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if out == out else default
    except (TypeError, ValueError):
        return default


def _parse_csv_values(text: str, cast):
    return [cast(x.strip()) for x in str(text or "").split(",") if x.strip()]


def moving_average(series: pd.Series, size: int, mode: str) -> pd.Series:
    mode = str(mode or "ema").lower()
    if mode == "ema":
        return series.ewm(span=size, adjust=False, min_periods=size).mean()
    return series.rolling(size).mean()


def macd_hist(close: pd.Series) -> pd.Series:
    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False, min_periods=9).mean()
    return 2.0 * (dif - dea)


def atr_pct(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    high = frame["high"]
    low = frame["low"]
    close = frame["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    return atr / close * 100.0


def normalize_price_frame(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close"])
    mapping = {
        "日期": "date",
        "date": "date",
        "开盘": "open",
        "open": "open",
        "最高": "high",
        "high": "high",
        "最低": "low",
        "low": "low",
        "收盘": "close",
        "close": "close",
    }
    frame = raw.rename(columns={k: v for k, v in mapping.items() if k in raw.columns}).copy()
    keep = [c for c in ["date", "open", "high", "low", "close"] if c in frame.columns]
    frame = frame[keep]
    for col in ["open", "high", "low", "close"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y%m%d")
    frame = frame.dropna(subset=["date", "open", "high", "low", "close"])
    return frame.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


@dataclass(frozen=True)
class ResearchParams:
    ma_mode: str
    fast_ma: int
    mid_ma: int
    long_ma: int
    use_macd: bool
    use_fast_ma_reduce: bool
    use_mid_ma_exit: bool
    use_atr_trailing: bool
    atr_mult: float
    max_holding_days: int
    max_fast_ma_deviation_pct: float

    @property
    def key(self) -> str:
        macd = "macd" if self.use_macd else "nomacd"
        fast = "fastreduce" if self.use_fast_ma_reduce else "nofastreduce"
        mid = "midexit" if self.use_mid_ma_exit else "nomidexit"
        atr = f"atr{self.atr_mult:g}" if self.use_atr_trailing else "noatr"
        return (
            f"{self.ma_mode}_f{self.fast_ma}_m{self.mid_ma}_l{self.long_ma}_"
            f"{macd}_{fast}_{mid}_{atr}_h{self.max_holding_days}_dev{self.max_fast_ma_deviation_pct:g}"
        )


def build_param_grid(args: argparse.Namespace) -> list[ResearchParams]:
    modes = _parse_csv_values(args.ma_modes, str)
    fasts = _parse_csv_values(args.fast_mas, int)
    mids = _parse_csv_values(args.mid_mas, int)
    longs = _parse_csv_values(args.long_mas, int)
    atr_mults = _parse_csv_values(args.atr_mults, float)
    max_days = _parse_csv_values(args.max_holding_days, int)
    max_devs = _parse_csv_values(args.max_fast_ma_deviation_pcts, float)
    macd_opts = [False, True] if args.test_macd else [False]
    fast_reduce_opts = [False, True] if args.test_fast_ma_reduce else [True]
    mid_exit_opts = [False, True] if args.test_mid_ma_exit else [True]
    atr_opts = [False, True] if args.test_atr_trailing else [True]

    out: list[ResearchParams] = []
    for combo in itertools.product(
        modes,
        fasts,
        mids,
        longs,
        macd_opts,
        fast_reduce_opts,
        mid_exit_opts,
        atr_opts,
        atr_mults,
        max_days,
        max_devs,
    ):
        p = ResearchParams(*combo)
        if p.fast_ma >= p.mid_ma or p.mid_ma >= p.long_ma:
            continue
        if not p.use_atr_trailing and p.atr_mult != atr_mults[0]:
            continue
        out.append(p)
    return out


def enrich_indicators(frame: pd.DataFrame, p: ResearchParams) -> pd.DataFrame:
    out = frame.copy()
    close = out["close"]
    out["ma_fast"] = moving_average(close, p.fast_ma, p.ma_mode)
    out["ma_mid"] = moving_average(close, p.mid_ma, p.ma_mode)
    out["ma_long"] = moving_average(close, p.long_ma, p.ma_mode)
    out["ma_fast_slope_3d_pct"] = (out["ma_fast"] / out["ma_fast"].shift(3) - 1.0) * 100.0
    out["fast_dev_pct"] = (close / out["ma_fast"] - 1.0) * 100.0
    out["close_vs_20d_high_pct"] = (close / close.rolling(20, min_periods=20).max() - 1.0) * 100.0
    out["macd_hist"] = macd_hist(close)
    out["macd_hist_delta"] = out["macd_hist"].diff()
    out["atr_pct"] = atr_pct(out)
    return out


def entry_signal(row: Any, p: ResearchParams) -> bool:
    values = [row.get("close"), row.get("ma_fast"), row.get("ma_mid"), row.get("ma_long")]
    if any(pd.isna(v) for v in values):
        return False
    trend_ok = bool(row["close"] > row["ma_fast"] > row["ma_mid"] > row["ma_long"])
    slope_ok = bool(row.get("ma_fast_slope_3d_pct", 0) > 0)
    breakout_ok = bool(row.get("close_vs_20d_high_pct", -999) >= -0.5)
    dev_ok = bool(row.get("fast_dev_pct", 999) <= p.max_fast_ma_deviation_pct)
    macd_ok = True
    if p.use_macd:
        macd_ok = bool(row.get("macd_hist", -1) > 0)
    return bool(trend_ok and slope_ok and breakout_ok and dev_ok and macd_ok)


def simulate_symbol(
    symbol: str,
    name: str,
    price_frame: pd.DataFrame,
    p: ResearchParams,
    start: str,
    end: str,
) -> list[dict[str, Any]]:
    frame = enrich_indicators(price_frame, p)
    rows = frame.to_dict("records")
    trades: list[dict[str, Any]] = []
    i = 0
    while i < len(rows) - 1:
        row = rows[i]
        date = str(row["date"])
        if date < start or date > end or not entry_signal(row, p):
            i += 1
            continue

        entry_idx = i + 1
        entry = rows[entry_idx]
        entry_price = _num(entry.get("open"))
        if entry_price is None or entry_price <= 0:
            i += 1
            continue

        remaining = 1.0
        realized_return = 0.0
        highest_close = float(entry.get("close") or entry_price)
        partial_reduced = False
        exit_idx = entry_idx
        exit_reason = "max_holding_days"
        hold_days = 0

        for j in range(entry_idx, min(len(rows) - 1, entry_idx + p.max_holding_days)):
            cur = rows[j]
            hold_days = j - entry_idx + 1
            close = _num(cur.get("close"))
            if close is not None:
                highest_close = max(highest_close, close)

            exit_today = False
            if p.use_fast_ma_reduce and not partial_reduced and close is not None:
                ma_fast = _num(cur.get("ma_fast"))
                ma_mid = _num(cur.get("ma_mid"))
                if ma_fast is not None and ma_mid is not None and close < ma_fast and close >= ma_mid:
                    next_open = _num(rows[j + 1].get("open"))
                    if next_open is not None and next_open > 0:
                        realized_return += 0.5 * (next_open / entry_price - 1.0)
                        remaining -= 0.5
                        partial_reduced = True

            if p.use_mid_ma_exit and close is not None:
                ma_mid = _num(cur.get("ma_mid"))
                if ma_mid is not None and close < ma_mid:
                    exit_today = True
                    exit_reason = "mid_ma_exit"

            if not exit_today and p.use_atr_trailing and close is not None:
                ap = _num(cur.get("atr_pct"))
                if ap is not None and ap > 0:
                    trail = highest_close * (1.0 - p.atr_mult * ap / 100.0)
                    if close < trail:
                        exit_today = True
                        exit_reason = "atr_trailing"

            if not exit_today and p.use_macd:
                mh = _num(cur.get("macd_hist"))
                md = _num(cur.get("macd_hist_delta"))
                if mh is not None and md is not None and mh < 0 and md < 0:
                    exit_today = True
                    exit_reason = "macd_decay"

            if exit_today:
                exit_idx = j + 1
                break
            exit_idx = j + 1

        exit_row = rows[min(exit_idx, len(rows) - 1)]
        exit_price = _num(exit_row.get("open")) or _num(exit_row.get("close"))
        if exit_price is None or exit_price <= 0:
            i = max(i + 1, exit_idx)
            continue

        realized_return += remaining * (exit_price / entry_price - 1.0)
        trades.append(
            {
                "param_key": p.key,
                "symbol_code": symbol,
                "symbol_name": name,
                "signal_date": date,
                "entry_date": str(entry.get("date")),
                "entry_price": round(entry_price, 4),
                "exit_date": str(exit_row.get("date")),
                "exit_price": round(exit_price, 4),
                "exit_reason": exit_reason,
                "holding_days": hold_days,
                "partial_reduced": partial_reduced,
                "return_pct": round(realized_return * 100.0, 4),
            }
        )
        i = max(i + 1, exit_idx)
    return trades


def simulate_symbol_events(
    symbol: str,
    name: str,
    price_frame: pd.DataFrame,
    signal_dates: list[str],
    p: ResearchParams,
    start: str,
    end: str,
) -> list[dict[str, Any]]:
    """Simulate only on supplied real T-day candidate dates.

    The event date list comes from existing main_trend daily candidate files.
    For each candidate date, this function still applies the current parameter
    rule as a research filter, then enters at T+1 open and exits at the next
    open after a close-based exit signal.
    """
    frame = enrich_indicators(price_frame, p)
    rows = frame.to_dict("records")
    idx_by_date = {str(r["date"]): i for i, r in enumerate(rows)}
    trades: list[dict[str, Any]] = []
    next_available_idx = 0
    for signal_date in sorted({_compact_date(d) for d in signal_dates if start <= _compact_date(d) <= end}):
        i = idx_by_date.get(signal_date)
        if i is None or i < next_available_idx or i >= len(rows) - 1:
            continue
        row = rows[i]
        if not entry_signal(row, p):
            continue

        entry_idx = i + 1
        entry = rows[entry_idx]
        entry_price = _num(entry.get("open"))
        if entry_price is None or entry_price <= 0:
            continue

        remaining = 1.0
        realized_return = 0.0
        highest_close = float(entry.get("close") or entry_price)
        partial_reduced = False
        exit_idx = entry_idx
        exit_reason = "max_holding_days"
        hold_days = 0

        for j in range(entry_idx, min(len(rows) - 1, entry_idx + p.max_holding_days)):
            cur = rows[j]
            hold_days = j - entry_idx + 1
            close = _num(cur.get("close"))
            if close is not None:
                highest_close = max(highest_close, close)

            exit_today = False
            if p.use_fast_ma_reduce and not partial_reduced and close is not None:
                ma_fast = _num(cur.get("ma_fast"))
                ma_mid = _num(cur.get("ma_mid"))
                if ma_fast is not None and ma_mid is not None and close < ma_fast and close >= ma_mid:
                    next_open = _num(rows[j + 1].get("open"))
                    if next_open is not None and next_open > 0:
                        realized_return += 0.5 * (next_open / entry_price - 1.0)
                        remaining -= 0.5
                        partial_reduced = True

            if p.use_mid_ma_exit and close is not None:
                ma_mid = _num(cur.get("ma_mid"))
                if ma_mid is not None and close < ma_mid:
                    exit_today = True
                    exit_reason = "mid_ma_exit"

            if not exit_today and p.use_atr_trailing and close is not None:
                ap = _num(cur.get("atr_pct"))
                if ap is not None and ap > 0:
                    trail = highest_close * (1.0 - p.atr_mult * ap / 100.0)
                    if close < trail:
                        exit_today = True
                        exit_reason = "atr_trailing"

            if not exit_today and p.use_macd:
                mh = _num(cur.get("macd_hist"))
                md = _num(cur.get("macd_hist_delta"))
                if mh is not None and md is not None and mh < 0 and md < 0:
                    exit_today = True
                    exit_reason = "macd_decay"

            if exit_today:
                exit_idx = j + 1
                break
            exit_idx = j + 1

        exit_row = rows[min(exit_idx, len(rows) - 1)]
        exit_price = _num(exit_row.get("open")) or _num(exit_row.get("close"))
        if exit_price is None or exit_price <= 0:
            continue
        realized_return += remaining * (exit_price / entry_price - 1.0)
        trades.append(
            {
                "param_key": p.key,
                "symbol_code": symbol,
                "symbol_name": name,
                "signal_date": signal_date,
                "entry_date": str(entry.get("date")),
                "entry_price": round(entry_price, 4),
                "exit_date": str(exit_row.get("date")),
                "exit_price": round(exit_price, 4),
                "exit_reason": exit_reason,
                "holding_days": hold_days,
                "partial_reduced": partial_reduced,
                "return_pct": round(realized_return * 100.0, 4),
            }
        )
        next_available_idx = max(next_available_idx, exit_idx)
    return trades


def summarize_trades(trades: list[dict[str, Any]], p: ResearchParams, engine_name: str) -> dict[str, Any]:
    returns = np.array([float(t["return_pct"]) / 100.0 for t in trades], dtype=float)
    row: dict[str, Any] = asdict(p)
    row["param_key"] = p.key
    row["engine"] = engine_name
    row["trade_count"] = int(len(returns))
    if len(returns) == 0:
        row.update(
            {
                "total_return_pct": 0.0,
                "avg_trade_return_pct": None,
                "median_trade_return_pct": None,
                "win_rate_pct": None,
                "profit_factor": None,
                "max_drawdown_pct": None,
                "sharpe_like": None,
            }
        )
        return row
    equity = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(equity)
    drawdown = equity / peak - 1.0
    gross_profit = returns[returns > 0].sum()
    gross_loss = abs(returns[returns < 0].sum())
    std = returns.std(ddof=1) if len(returns) > 1 else 0.0
    row.update(
        {
            "total_return_pct": round((equity[-1] - 1.0) * 100.0, 4),
            "avg_trade_return_pct": round(float(returns.mean() * 100.0), 4),
            "median_trade_return_pct": round(float(np.median(returns) * 100.0), 4),
            "win_rate_pct": round(float((returns > 0).mean() * 100.0), 2),
            "profit_factor": round(float(gross_profit / gross_loss), 4) if gross_loss > 0 else None,
            "max_drawdown_pct": round(float(drawdown.min() * 100.0), 4),
            "sharpe_like": round(float(returns.mean() / std * math.sqrt(252 / max(1, p.max_holding_days))), 4) if std > 0 else None,
        }
    )
    return row


def load_symbols(args: argparse.Namespace) -> list[tuple[str, str]]:
    symbols: list[tuple[str, str]] = []
    if args.symbols:
        for code in _parse_csv_values(args.symbols, str):
            digits = "".join(ch for ch in code if ch.isdigit())[-6:].zfill(6)
            symbols.append((digits, digits))
    if args.from_tday:
        payload = json.loads(Path(args.from_tday).read_text(encoding="utf-8"))
        rows = payload.get("pool") if isinstance(payload, dict) else payload
        for row in rows or []:
            code = str(row.get("symbol_code") or row.get("code") or "")
            digits = "".join(ch for ch in code if ch.isdigit())[-6:].zfill(6)
            if digits:
                symbols.append((digits, str(row.get("symbol_name") or row.get("name") or digits)))
    if args.from_event_dir:
        events = load_candidate_events(Path(args.from_event_dir), _compact_date(args.start), _compact_date(args.end or args.start))
        for code, items in events.items():
            name = next((str(x.get("symbol_name") or x.get("name") or code) for x in items if x), code)
            symbols.append((code, name))
    # stable de-dup
    out = []
    seen = set()
    for code, name in symbols:
        if code and code not in seen:
            seen.add(code)
            out.append((code, name))
    return out


def load_candidate_events(event_dir: Path, start: str, end: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(event_dir.glob("*/candidates.json")):
        signal_date = _compact_date(path.parent.name)
        if signal_date < start or signal_date > end:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = payload.get("candidates") if isinstance(payload, dict) else payload
        for row in rows or []:
            code = str(row.get("symbol_code") or row.get("code") or "")
            digits = "".join(ch for ch in code if ch.isdigit())[-6:].zfill(6)
            if not digits:
                continue
            item = dict(row)
            item["signal_date"] = signal_date
            item["symbol_code"] = digits
            item["symbol_name"] = str(row.get("symbol_name") or row.get("name") or digits)
            out.setdefault(digits, []).append(item)
    return out


def fetch_price_data(symbols: Iterable[tuple[str, str]], start: str, end: str, warmup: int) -> dict[str, pd.DataFrame]:
    from utils.cn_price_provider import get_stock_zh_a_hist
    from utils.date_utils import get_trading_date_range

    warmup_start, _ = get_trading_date_range(end_date=start, count=max(warmup, 260), include_end=True)
    data = {}
    for code, _name in symbols:
        raw = get_stock_zh_a_hist(code, warmup_start, end, adjust="qfq", verbose=False)
        frame = normalize_price_frame(raw)
        if not frame.empty:
            data[code] = frame
    return data


def run_research(args: argparse.Namespace) -> dict[str, Any]:
    start = _compact_date(args.start)
    end = _compact_date(args.end or args.start)
    symbols = load_symbols(args)
    if not symbols:
        raise SystemExit("No symbols supplied. Use --symbols or --from-tday.")
    params = build_param_grid(args)
    if not params:
        raise SystemExit("Parameter grid is empty.")

    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    price_data = fetch_price_data(symbols, start, end, warmup=max(max(p.long_ma for p in params) + 80, 260))
    engine_name = "vectorbt_available_pandas_event" if _vectorbt_available() else "pandas_event"
    candidate_events = (
        load_candidate_events(Path(args.from_event_dir), start, end)
        if args.from_event_dir
        else {}
    )

    all_summary: list[dict[str, Any]] = []
    all_trades: list[dict[str, Any]] = []
    for idx, p in enumerate(params, 1):
        trades: list[dict[str, Any]] = []
        for code, name in symbols:
            frame = price_data.get(code)
            if frame is None or frame.empty:
                continue
            if candidate_events:
                signal_dates = [str(x.get("signal_date")) for x in candidate_events.get(code, [])]
                trades.extend(simulate_symbol_events(code, name, frame, signal_dates, p, start, end))
            else:
                trades.extend(simulate_symbol(code, name, frame, p, start, end))
        all_summary.append(summarize_trades(trades, p, engine_name))
        if args.save_trades:
            all_trades.extend(trades)
        if args.progress and (idx == 1 or idx % 25 == 0 or idx == len(params)):
            print(f"[research] {idx}/{len(params)} params done; last_trades={len(trades)}")

    summary_df = pd.DataFrame(all_summary).sort_values(
        ["avg_trade_return_pct", "profit_factor", "trade_count"],
        ascending=[False, False, False],
        na_position="last",
    )
    matrix_path = out_dir / "vectorbt_param_matrix.csv"
    summary_df.to_csv(matrix_path, index=False)

    trades_path = None
    if args.save_trades:
        trades_path = out_dir / "vectorbt_trades.csv"
        pd.DataFrame(all_trades).to_csv(trades_path, index=False)

    meta = {
        "start": start,
        "end": end,
        "symbols": [{"symbol_code": c, "symbol_name": n} for c, n in symbols],
        "event_days": len({x.get("signal_date") for items in candidate_events.values() for x in items}) if candidate_events else None,
        "event_count": sum(len(items) for items in candidate_events.values()) if candidate_events else None,
        "param_count": len(params),
        "engine": engine_name,
        "vectorbt_installed": _vectorbt_available(),
        "matrix_path": str(matrix_path),
        "trades_path": str(trades_path) if trades_path else None,
        "top": summary_df.head(10).to_dict("records"),
    }
    meta_path = out_dir / "vectorbt_research_summary.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="Research signal start date, e.g. 20260601")
    parser.add_argument("--end", default="", help="Research signal end date; defaults to --start")
    parser.add_argument("--symbols", default="", help="Comma-separated stock codes, e.g. 600988,601899")
    parser.add_argument("--from-tday", default="", help="Read symbols from a main_trend tday_pool.json")
    parser.add_argument("--from-event-dir", default="", help="Read daily real candidate events from <date>/candidates.json files")
    parser.add_argument("--output-dir", default="agents_workspace_main_trend_research")
    parser.add_argument("--ma-modes", default="ema,sma")
    parser.add_argument("--fast-mas", default="5,8,10")
    parser.add_argument("--mid-mas", default="20")
    parser.add_argument("--long-mas", default="60")
    parser.add_argument("--atr-mults", default="1.5,2.0,2.5")
    parser.add_argument("--max-holding-days", default="3,5,10")
    parser.add_argument("--max-fast-ma-deviation-pcts", default="8,10,12")
    parser.add_argument("--test-macd", action="store_true", help="Run MACD on/off variants")
    parser.add_argument("--test-fast-ma-reduce", action="store_true", help="Run fast-MA reduce on/off variants")
    parser.add_argument("--test-mid-ma-exit", action="store_true", help="Run mid-MA exit on/off variants")
    parser.add_argument("--test-atr-trailing", action="store_true", help="Run ATR trailing on/off variants")
    parser.add_argument("--save-trades", action="store_true")
    parser.add_argument("--progress", action="store_true")
    return parser


def main() -> None:
    meta = run_research(build_parser().parse_args())
    print(json.dumps({"matrix_path": meta["matrix_path"], "top": meta["top"][:3]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
