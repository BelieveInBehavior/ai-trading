"""
News-signal offline validator.

Purpose:
- Evaluate whether ranked stock signals produce forward returns and excess returns.
- Support both real-time AKShare fetch and offline CSV mode.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd


def normalize_symbol_code(symbol_code: str) -> str:
    text = (symbol_code or "").strip().upper()
    if not text:
        return ""
    if "." in text:
        text = text.split(".")[0]
    return text


def parse_datetime_any(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    for fmt in [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
    ]:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


@dataclass
class SignalRecord:
    symbol_code: str
    signal_time: datetime
    buy_score: float
    probability: float
    action: str
    source_file: str


class BasePriceProvider:
    def get_price_frame(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise NotImplementedError


class AksharePriceProvider(BasePriceProvider):
    def get_price_frame(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        import akshare as ak

        frame = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
        if frame is None or frame.empty:
            return pd.DataFrame(columns=["date", "close"])
        mapped = frame.rename(columns={"日期": "date", "收盘": "close"})
        mapped["date"] = pd.to_datetime(mapped["date"], errors="coerce")
        mapped["close"] = pd.to_numeric(mapped["close"], errors="coerce")
        return mapped[["date", "close"]].dropna().sort_values("date").reset_index(drop=True)

    def get_index_frame(self, index_symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        import akshare as ak

        frame = ak.stock_zh_index_daily_em(symbol=index_symbol)
        if frame is None or frame.empty:
            return pd.DataFrame(columns=["date", "close"])

        mapped = frame.rename(columns={"date": "date", "close": "close"})
        mapped["date"] = pd.to_datetime(mapped["date"], errors="coerce")
        mapped["close"] = pd.to_numeric(mapped["close"], errors="coerce")

        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        mapped = mapped[(mapped["date"] >= start_dt) & (mapped["date"] <= end_dt)]
        return mapped[["date", "close"]].dropna().sort_values("date").reset_index(drop=True)


class CsvPriceProvider(BasePriceProvider):
    """Load symbol CSV from a directory: `<symbol>.csv` with columns `date`, `close`."""

    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir)

    def get_price_frame(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        file_path = self.root_dir / f"{symbol}.csv"
        if not file_path.exists():
            return pd.DataFrame(columns=["date", "close"])

        frame = pd.read_csv(file_path)
        if "date" not in frame.columns or "close" not in frame.columns:
            return pd.DataFrame(columns=["date", "close"])

        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        frame = frame[(frame["date"] >= start_dt) & (frame["date"] <= end_dt)]
        return frame[["date", "close"]].dropna().sort_values("date").reset_index(drop=True)

    def get_index_frame(self, index_symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self.get_price_frame(index_symbol, start_date, end_date)


def _extract_signal_time(signal: Dict[str, Any], default_time: Optional[datetime]) -> Optional[datetime]:
    candidates = [
        signal.get("signal_time"),
        signal.get("trigger_time"),
        signal.get("pub_time"),
    ]
    evidence_list = signal.get("evidence_list") or []
    for ev in evidence_list:
        candidates.append(ev.get("time"))

    for candidate in candidates:
        dt = parse_datetime_any(candidate)
        if dt:
            return dt

    return default_time


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        text = str(value).strip()
        if not text:
            return default
        if text.endswith("%"):
            return float(text[:-1]) / 100.0
        num = float(text)
        if num > 1.0:
            num = num / 100.0
        return num
    except Exception:
        return default


def load_signals_from_json(path: Path) -> List[SignalRecord]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    base_trigger_time = parse_datetime_any(payload.get("trigger_time")) if isinstance(payload, dict) else None
    signals = []

    if isinstance(payload, list):
        signal_list = payload
    elif isinstance(payload, dict):
        signal_list = payload.get("best_signals") or payload.get("research_signals") or []
    else:
        signal_list = []

    for item in signal_list:
        if not isinstance(item, dict):
            continue
        symbol = normalize_symbol_code(item.get("symbol_code") or "")
        if not symbol:
            continue

        signal_time = _extract_signal_time(item, base_trigger_time)
        if not signal_time:
            continue

        record = SignalRecord(
            symbol_code=symbol,
            signal_time=signal_time,
            buy_score=float(item.get("buy_score") or 0.0),
            probability=_safe_float(item.get("probability_value") or item.get("probability"), 0.5),
            action=str(item.get("action") or ""),
            source_file=str(path),
        )
        signals.append(record)

    return signals


def load_signals(signal_paths: Sequence[Path]) -> List[SignalRecord]:
    all_signals: List[SignalRecord] = []
    for path in signal_paths:
        all_signals.extend(load_signals_from_json(path))
    return all_signals


def _pick_entry_index(price_df: pd.DataFrame, signal_time: datetime) -> Optional[int]:
    if price_df.empty:
        return None
    signal_date = signal_time.date()
    candidates = price_df.index[price_df["date"].dt.date > signal_date].tolist()
    return candidates[0] if candidates else None


def _compute_forward_return(price_df: pd.DataFrame, entry_idx: int, horizon: int) -> Optional[float]:
    exit_idx = entry_idx + horizon
    if exit_idx >= len(price_df):
        return None
    entry_close = float(price_df.iloc[entry_idx]["close"])
    exit_close = float(price_df.iloc[exit_idx]["close"])
    if entry_close <= 0:
        return None
    return (exit_close / entry_close) - 1.0


def evaluate_signals(
    signals: Sequence[SignalRecord],
    provider: BasePriceProvider,
    benchmark_symbol: Optional[str],
    horizons: Sequence[int],
    lookahead_padding_days: int = 14,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    if not signals:
        return pd.DataFrame(), {"total_signals": 0, "evaluated_signals": 0}

    min_time = min(s.signal_time for s in signals)
    max_time = max(s.signal_time for s in signals)
    start_date = (min_time - timedelta(days=5)).strftime("%Y%m%d")
    end_date = (max_time + timedelta(days=lookahead_padding_days)).strftime("%Y%m%d")

    benchmark_df = None
    if benchmark_symbol and hasattr(provider, "get_index_frame"):
        try:
            benchmark_df = provider.get_index_frame(benchmark_symbol, start_date, end_date)
        except Exception:
            benchmark_df = None

    rows = []
    by_symbol_cache: Dict[str, pd.DataFrame] = {}

    for signal in signals:
        symbol = signal.symbol_code
        if symbol not in by_symbol_cache:
            try:
                by_symbol_cache[symbol] = provider.get_price_frame(symbol, start_date, end_date)
            except Exception:
                by_symbol_cache[symbol] = pd.DataFrame(columns=["date", "close"])
        price_df = by_symbol_cache[symbol]

        entry_idx = _pick_entry_index(price_df, signal.signal_time)
        if entry_idx is None:
            continue

        entry_date = price_df.iloc[entry_idx]["date"]
        row: Dict[str, Any] = {
            "symbol_code": symbol,
            "signal_time": signal.signal_time.strftime("%Y-%m-%d %H:%M:%S"),
            "entry_date": entry_date.strftime("%Y-%m-%d"),
            "buy_score": signal.buy_score,
            "probability": signal.probability,
            "action": signal.action,
            "source_file": signal.source_file,
        }

        for horizon in horizons:
            ret = _compute_forward_return(price_df, entry_idx, horizon)
            row[f"ret_t{horizon}"] = ret

            if benchmark_df is not None and ret is not None:
                bench_entry_idx = _pick_entry_index(benchmark_df, signal.signal_time)
                if bench_entry_idx is not None:
                    bench_ret = _compute_forward_return(benchmark_df, bench_entry_idx, horizon)
                    row[f"bench_ret_t{horizon}"] = bench_ret
                    row[f"alpha_t{horizon}"] = (ret - bench_ret) if bench_ret is not None else None
                else:
                    row[f"bench_ret_t{horizon}"] = None
                    row[f"alpha_t{horizon}"] = None

        rows.append(row)

    details = pd.DataFrame(rows)
    summary = _summarize_metrics(details, horizons)
    summary["total_signals"] = len(signals)
    summary["evaluated_signals"] = len(details)
    return details, summary


def _summarize_metrics(details: pd.DataFrame, horizons: Sequence[int]) -> Dict[str, Any]:
    if details.empty:
        return {"hit_rate": {}, "avg_return": {}, "avg_alpha": {}}

    result: Dict[str, Any] = {
        "hit_rate": {},
        "avg_return": {},
        "avg_alpha": {},
        "score_bucket": {},
    }

    for horizon in horizons:
        ret_col = f"ret_t{horizon}"
        alpha_col = f"alpha_t{horizon}"
        if ret_col in details:
            valid_ret = details[ret_col].dropna()
            if not valid_ret.empty:
                result["hit_rate"][f"t{horizon}"] = float((valid_ret > 0).mean())
                result["avg_return"][f"t{horizon}"] = float(valid_ret.mean())
            else:
                result["hit_rate"][f"t{horizon}"] = None
                result["avg_return"][f"t{horizon}"] = None

        if alpha_col in details:
            valid_alpha = details[alpha_col].dropna()
            result["avg_alpha"][f"t{horizon}"] = float(valid_alpha.mean()) if not valid_alpha.empty else None

    # Stratify by buy-score bucket
    score_bins = [0, 50, 60, 70, 80, 100]
    details = details.copy()
    details["score_bucket"] = pd.cut(details["buy_score"], bins=score_bins, include_lowest=True)
    if "ret_t1" in details.columns:
        bucket_df = (
            details.groupby("score_bucket", observed=False)["ret_t1"]
            .agg(["count", "mean"])
            .reset_index()
        )
        bucket_df["score_bucket"] = bucket_df["score_bucket"].astype(str)
        bucket_df["mean"] = bucket_df["mean"].astype(object)
        bucket_df["mean"] = bucket_df["mean"].apply(lambda x: None if pd.isna(x) else float(x))
        bucket_stats = bucket_df.to_dict(orient="records")
        for row in bucket_stats:
            if pd.isna(row.get("mean")):
                row["mean"] = None
        result["score_bucket"] = bucket_stats

    return result


def _collect_signal_files(signal_json: Optional[str], signal_dir: Optional[str]) -> List[Path]:
    files: List[Path] = []
    if signal_json:
        files.append(Path(signal_json))
    if signal_dir:
        files.extend(sorted(Path(signal_dir).glob("*.json")))
    return [f for f in files if f.exists()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest ranked news signals")
    parser.add_argument("--signal-json", type=str, default="", help="Single signal JSON file")
    parser.add_argument("--signal-dir", type=str, default="", help="Directory of signal JSON files")
    parser.add_argument("--horizons", type=str, default="1,3,5", help="Comma-separated horizons")
    parser.add_argument("--benchmark", type=str, default="sh000300", help="Benchmark index symbol")
    parser.add_argument("--price-csv-dir", type=str, default="", help="Offline CSV price directory")
    parser.add_argument("--output", type=str, default="", help="Optional output summary JSON path")
    parser.add_argument("--details-output", type=str, default="", help="Optional output details CSV path")
    args = parser.parse_args()

    horizons = [int(x.strip()) for x in args.horizons.split(",") if x.strip().isdigit()]
    if not horizons:
        raise ValueError("No valid horizons provided")

    signal_files = _collect_signal_files(args.signal_json, args.signal_dir)
    if not signal_files:
        raise FileNotFoundError("No signal files found. Provide --signal-json or --signal-dir")

    signals = load_signals(signal_files)
    if not signals:
        raise ValueError("No valid signals parsed from input files")

    if args.price_csv_dir:
        provider: BasePriceProvider = CsvPriceProvider(Path(args.price_csv_dir))
    else:
        provider = AksharePriceProvider()

    details_df, summary = evaluate_signals(
        signals=signals,
        provider=provider,
        benchmark_symbol=args.benchmark,
        horizons=horizons,
    )

    print("=== News Signal Backtest Summary ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"Saved summary to {output_path}")

    if args.details_output:
        details_path = Path(args.details_output)
        details_path.parent.mkdir(parents=True, exist_ok=True)
        details_df.to_csv(details_path, index=False)
        print(f"Saved details to {details_path}")


if __name__ == "__main__":
    main()
