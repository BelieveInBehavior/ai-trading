"""
Replay calibration for next-day buy decisions.

Workflow:
1) Load decision/trade signal JSON files.
2) Evaluate T+1 realized returns.
3) Fit probability calibration: y = slope * p + intercept.
4) Save updated calibration config and replay report.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

try:
    from tools.news_signal_backtest import (
        AksharePriceProvider,
        CsvPriceProvider,
        BasePriceProvider,
        evaluate_signals,
        load_signals,
    )
except ModuleNotFoundError:
    from news_signal_backtest import (  # type: ignore
        AksharePriceProvider,
        CsvPriceProvider,
        BasePriceProvider,
        evaluate_signals,
        load_signals,
    )


DEFAULT_CALIB_PATH = Path("agents_workspace/models/probability_calibration.json")


def _collect_decision_files(signal_json: Optional[str], signal_dir: Optional[str], latest_n: int) -> List[Path]:
    files: List[Path] = []
    if signal_json:
        p = Path(signal_json)
        if p.exists():
            files.append(p)
    if signal_dir:
        directory = Path(signal_dir)
    else:
        directory = Path("agents_workspace/results/trade_decisions")

    if directory.exists():
        candidates = sorted(directory.glob("*.json"))
        if latest_n > 0:
            candidates = candidates[-latest_n:]
        files.extend(candidates)

    unique = []
    seen = set()
    for f in files:
        key = str(f.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def _filter_evaluation_rows(details_df: pd.DataFrame, buys_only: bool) -> pd.DataFrame:
    if details_df.empty:
        return details_df

    filtered = details_df.copy()

    if buys_only and "action" in filtered.columns:
        action_like = filtered["action"].fillna("").astype(str).str.lower()
        filtered = filtered[action_like.str.contains("buy|加仓|买入|增持|做多")]

    if buys_only and "source_file" in filtered.columns:
        keep_rows = []
        for idx, row in filtered.iterrows():
            source_file = str(row.get("source_file") or "")
            try:
                with open(source_file, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                best_signals = payload.get("best_signals") if isinstance(payload, dict) else None
                if not isinstance(best_signals, list):
                    keep_rows.append(idx)
                    continue

                symbol = str(row.get("symbol_code") or "").split(".")[0].upper()
                matched = next(
                    (
                        item
                        for item in best_signals
                        if isinstance(item, dict)
                        and str(item.get("symbol_code") or "").split(".")[0].upper() == symbol
                    ),
                    None,
                )
                if matched is None:
                    keep_rows.append(idx)
                    continue
                decision = str(matched.get("buy_decision") or "").strip().lower()
                if decision in {"buy", "买入", "加仓", "增持", "做多"}:
                    keep_rows.append(idx)
            except Exception:
                keep_rows.append(idx)

        filtered = filtered.loc[keep_rows]

    if "signal_time" in filtered.columns and "symbol_code" in filtered.columns:
        time_series = pd.to_datetime(filtered["signal_time"], errors="coerce")
        filtered = filtered.assign(signal_date=time_series.dt.date)
        filtered = filtered.sort_values(["symbol_code", "signal_date", "signal_time"]).drop_duplicates(
            subset=["symbol_code", "signal_date"], keep="last"
        )

    return filtered


def _brier_score(pred: Sequence[float], actual: Sequence[int]) -> Optional[float]:
    if not pred or not actual or len(pred) != len(actual):
        return None
    return float(sum((p - y) ** 2 for p, y in zip(pred, actual)) / len(pred))


def _fit_linear_calibration(pred: Sequence[float], actual: Sequence[int]) -> Tuple[float, float]:
    """Least-squares fit for y = slope * p + intercept."""
    if len(pred) < 2:
        return 1.0, 0.0

    x = pd.Series(pred, dtype=float)
    y = pd.Series(actual, dtype=float)

    x_mean = float(x.mean())
    y_mean = float(y.mean())
    denom = float(((x - x_mean) ** 2).sum())
    if denom <= 1e-12:
        return 1.0, 0.0

    slope = float(((x - x_mean) * (y - y_mean)).sum() / denom)
    intercept = float(y_mean - slope * x_mean)

    slope = max(0.0, min(2.0, slope))
    intercept = max(-0.5, min(0.5, intercept))
    return slope, intercept


def _apply_calibration(pred: Sequence[float], slope: float, intercept: float) -> List[float]:
    calibrated = []
    for p in pred:
        v = p * slope + intercept
        calibrated.append(max(0.0, min(1.0, float(v))))
    return calibrated


def _load_existing_calibration(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"slope": 0.92, "intercept": 0.03, "source": "default"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return {"slope": 0.92, "intercept": 0.03, "source": "default"}
        return payload
    except Exception:
        return {"slope": 0.92, "intercept": 0.03, "source": "default"}


def calibrate(
    signal_files: Sequence[Path],
    provider: BasePriceProvider,
    benchmark_symbol: str,
    min_samples: int,
    output_calibration_path: Path,
    report_dir: Path,
    buys_only: bool = True,
) -> Dict[str, Any]:
    signals = load_signals(signal_files)
    details_df, summary = evaluate_signals(
        signals=signals,
        provider=provider,
        benchmark_symbol=benchmark_symbol,
        horizons=[1],
    )

    if details_df.empty or "ret_t1" not in details_df.columns:
        return {
            "status": "no_data",
            "message": "No evaluable T+1 rows found.",
            "summary": summary,
        }

    filtered_df = _filter_evaluation_rows(details_df, buys_only=buys_only)
    valid = filtered_df.dropna(subset=["ret_t1", "probability"]).copy()
    if valid.empty:
        return {
            "status": "no_data",
            "message": "No rows with both probability and T+1 return.",
            "summary": summary,
            "rows_after_filter": int(len(filtered_df)),
        }

    valid["label"] = (valid["ret_t1"] > 0).astype(int)
    pred = [float(x) for x in valid["probability"].tolist()]
    actual = [int(x) for x in valid["label"].tolist()]

    old = _load_existing_calibration(output_calibration_path)
    old_slope = float(old.get("slope", 1.0))
    old_intercept = float(old.get("intercept", 0.0))

    if len(valid) < min_samples:
        return {
            "status": "insufficient_samples",
            "message": f"Only {len(valid)} samples (< {min_samples}), keep existing calibration.",
            "summary": summary,
            "samples": len(valid),
            "rows_after_filter": int(len(filtered_df)),
            "current_calibration": old,
        }

    fit_slope, fit_intercept = _fit_linear_calibration(pred, actual)
    calibrated_pred = _apply_calibration(pred, fit_slope, fit_intercept)

    brier_before = _brier_score(_apply_calibration(pred, old_slope, old_intercept), actual)
    brier_after = _brier_score(calibrated_pred, actual)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_calibration = {
        "slope": round(fit_slope, 6),
        "intercept": round(fit_intercept, 6),
        "updated_at": now,
        "samples": len(valid),
        "brier_before": brier_before,
        "brier_after": brier_after,
        "benchmark_symbol": benchmark_symbol,
        "source": "replay_calibration",
    }

    output_calibration_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_calibration_path, "w", encoding="utf-8") as f:
        json.dump(new_calibration, f, ensure_ascii=False, indent=2)

    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    details_path = report_dir / f"calibration_details_{stamp}.csv"
    valid.to_csv(details_path, index=False)

    summary_payload = {
        "status": "updated",
        "calibration": new_calibration,
        "summary": summary,
        "rows_after_filter": int(len(filtered_df)),
        "signal_files": [str(p) for p in signal_files],
        "details_path": str(details_path),
    }
    summary_path = report_dir / f"calibration_report_{stamp}.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, ensure_ascii=False, indent=2)

    summary_payload["report_path"] = str(summary_path)
    return summary_payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay calibration for next-day buy decisions")
    parser.add_argument("--signal-json", type=str, default="", help="Single decision/signal JSON file")
    parser.add_argument(
        "--signal-dir",
        type=str,
        default="agents_workspace/results/trade_decisions",
        help="Directory with decision JSON files",
    )
    parser.add_argument("--latest-n", type=int, default=20, help="Use latest N decision files from --signal-dir")
    parser.add_argument("--benchmark", type=str, default="sh000300", help="Benchmark symbol")
    parser.add_argument("--price-csv-dir", type=str, default="", help="Offline price CSV directory")
    parser.add_argument("--min-samples", type=int, default=15, help="Minimum sample size to update calibration")
    parser.add_argument(
        "--include-watch",
        action="store_true",
        help="Include watchlist/non-buy decisions (default: buys only)",
    )
    parser.add_argument(
        "--calibration-path",
        type=str,
        default=str(DEFAULT_CALIB_PATH),
        help="Output calibration config path",
    )
    parser.add_argument(
        "--report-dir",
        type=str,
        default="agents_workspace/results/calibration_reports",
        help="Directory for calibration reports",
    )
    args = parser.parse_args()

    signal_files = _collect_decision_files(args.signal_json, args.signal_dir, args.latest_n)
    if not signal_files:
        raise FileNotFoundError("No decision files found for calibration")

    if args.price_csv_dir:
        provider: BasePriceProvider = CsvPriceProvider(Path(args.price_csv_dir))
    else:
        provider = AksharePriceProvider()

    result = calibrate(
        signal_files=signal_files,
        provider=provider,
        benchmark_symbol=args.benchmark,
        min_samples=args.min_samples,
        output_calibration_path=Path(args.calibration_path),
        report_dir=Path(args.report_dir),
        buys_only=not args.include_watch,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
