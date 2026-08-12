"""
Performance Tracker: Track historical performance of trading signals.

Evaluates past predictions against actual market returns to measure
signal quality over time.
"""
import json
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict

from loguru import logger
from config.config import PROJECT_ROOT
from utils.akshare_utils import akshare_cached
from utils.date_utils import get_previous_trading_date


class PerformanceTracker:
    """Tracks and evaluates the historical performance of trading signals."""

    def __init__(self):
        self.workspace_dir = PROJECT_ROOT / "agents_workspace" / "performance"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        self.pending_file = self.workspace_dir / "pending_signals.json"
        self.history_file = self.workspace_dir / "performance_history.json"

        self.pending_signals: List[Dict] = self._load_json(self.pending_file, default=[])
        self.performance_history: List[Dict] = self._load_json(self.history_file, default=[])

    def _load_json(self, path: Path, default=None):
        """Load JSON file safely, returning default on any failure."""
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load {path}: {e}")
        return default if default is not None else []

    def _save_json(self, path: Path, data):
        """Save data to JSON file safely."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save {path}: {e}")

    async def record_signals(self, trigger_time: str, best_signals: List[Dict]):
        """
        Store signals with their predictions for later evaluation.

        Args:
            trigger_time: The time the signal was triggered (format: "YYYY-MM-DD HH:MM:SS")
            best_signals: List of signal dicts from the trading decision system.
                Only passed-gate buy decisions are persisted.
        """
        try:
            def is_tradable_buy(signal: Dict) -> bool:
                decision = str(signal.get("buy_decision") or "").lower()
                if decision:
                    return decision == "buy"
                gate = signal.get("next_day_gate_report") or {}
                return bool(gate.get("passed", False))

            tradable_signals = [
                signal for signal in best_signals
                if is_tradable_buy(signal)
            ]
            for signal in tradable_signals:
                record = {
                    "trigger_time": trigger_time,
                    "symbol_code": signal.get("symbol_code", ""),
                    "symbol_name": signal.get("symbol_name", ""),
                    "action": signal.get("action", "buy"),
                    "buy_decision": signal.get("buy_decision", ""),
                    "probability": signal.get("probability_value", signal.get("probability", 0)),
                    "agent_name": signal.get("agent_name", ""),
                }
                self.pending_signals.append(record)

            self._save_json(self.pending_file, self.pending_signals)
            skipped = len(best_signals) - len(tradable_signals)
            logger.info(
                f"Recorded {len(tradable_signals)} buy signals for trigger_time={trigger_time}; "
                f"skipped {skipped} watchlist candidates"
            )
        except Exception as e:
            logger.error(f"Error recording signals: {e}")

    async def evaluate_pending(self):
        """
        Evaluate pending signals that are at least 1 trading day old.

        For each eligible signal:
        - Fetch actual price on trigger day (open) and next day (close) via akshare
        - Calculate actual return
        - Classify as hit or miss
        - Move from pending to history
        """
        still_pending = []
        now = datetime.now()

        for signal in self.pending_signals:
            try:
                trigger_time = signal["trigger_time"]
                trigger_dt = datetime.strptime(trigger_time, "%Y-%m-%d %H:%M:%S")

                # Must be at least 2 calendar days old to ensure next trading day data is available
                if (now - trigger_dt) < timedelta(days=2):
                    still_pending.append(signal)
                    continue

                symbol_code = signal["symbol_code"]
                action = signal.get("action", "buy")

                # Determine date range for akshare query
                trigger_date = trigger_dt.strftime("%Y%m%d")

                # Convert symbol code from tushare format (600519.SH) to akshare format (600519)
                ak_symbol = symbol_code.split(".")[0] if "." in symbol_code else symbol_code

                # Fetch historical data covering trigger day and next day
                # Use a window to ensure we capture at least 2 trading days
                start_date = trigger_dt.strftime("%Y%m%d")
                end_date = (trigger_dt + timedelta(days=10)).strftime("%Y%m%d")

                df = akshare_cached.run(
                    func_name="stock_zh_a_hist",
                    func_kwargs={
                        "symbol": ak_symbol,
                        "period": "daily",
                        "start_date": start_date,
                        "end_date": end_date,
                        "adjust": "qfq",
                    },
                    verbose=False,
                )

                if df is None or len(df) < 2:
                    # Not enough data yet, keep pending
                    still_pending.append(signal)
                    continue

                # Sort by date ascending
                df = df.sort_values(by="日期", ascending=True).reset_index(drop=True)

                # Get open price on trigger day and close on next trading day
                open_price = float(df.iloc[0]["开盘"])
                next_close = float(df.iloc[1]["收盘"])

                # Calculate actual return percentage
                actual_return = (next_close - open_price) / open_price * 100

                # Determine hit/miss
                if action.lower() == "buy":
                    hit = actual_return > 0
                else:  # sell
                    hit = actual_return < 0

                # Build history record
                history_record = {
                    "trigger_time": trigger_time,
                    "symbol_code": symbol_code,
                    "symbol_name": signal.get("symbol_name", ""),
                    "action": action,
                    "probability": signal.get("probability", 0),
                    "agent_name": signal.get("agent_name", ""),
                    "open_price": open_price,
                    "next_close": next_close,
                    "actual_return_pct": round(actual_return, 4),
                    "hit": hit,
                    "evaluated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                }

                self.performance_history.append(history_record)
                logger.info(
                    f"Evaluated {symbol_code}: return={actual_return:.2f}%, hit={hit}"
                )

            except Exception as e:
                # If evaluation fails (e.g., akshare fetch error), keep signal pending
                logger.warning(
                    f"Failed to evaluate signal {signal.get('symbol_code', '?')}: {e}"
                )
                still_pending.append(signal)

        # Update files
        self.pending_signals = still_pending
        self._save_json(self.pending_file, self.pending_signals)
        self._save_json(self.history_file, self.performance_history)
        logger.info(
            f"Evaluation complete. Pending: {len(still_pending)}, "
            f"Total history: {len(self.performance_history)}"
        )

    def get_summary_stats(self) -> Dict:
        """
        Return aggregate performance statistics.

        Returns:
            Dict with overall stats, per-agent stats, per-probability-bucket stats,
            and recent signal results.
        """
        history = self.performance_history

        if not history:
            return {
                "total_signals": 0,
                "hit_count": 0,
                "miss_count": 0,
                "win_rate": 0.0,
                "avg_return": 0.0,
                "avg_return_hits": 0.0,
                "avg_return_misses": 0.0,
                "by_agent": {},
                "by_probability_bucket": {},
                "recent_10": [],
            }

        total = len(history)
        hits = [r for r in history if r.get("hit")]
        misses = [r for r in history if not r.get("hit")]
        hit_count = len(hits)
        miss_count = len(misses)

        all_returns = [r.get("actual_return_pct", 0) for r in history]
        hit_returns = [r.get("actual_return_pct", 0) for r in hits]
        miss_returns = [r.get("actual_return_pct", 0) for r in misses]

        avg_return = sum(all_returns) / total if total > 0 else 0.0
        avg_return_hits = sum(hit_returns) / hit_count if hit_count > 0 else 0.0
        avg_return_misses = sum(miss_returns) / miss_count if miss_count > 0 else 0.0
        win_rate = (hit_count / total * 100) if total > 0 else 0.0

        # By agent
        by_agent = {}
        for record in history:
            agent = record.get("agent_name", "unknown")
            if agent not in by_agent:
                by_agent[agent] = {"total": 0, "wins": 0}
            by_agent[agent]["total"] += 1
            if record.get("hit"):
                by_agent[agent]["wins"] += 1
        for agent, stats in by_agent.items():
            stats["win_rate"] = round(
                stats["wins"] / stats["total"] * 100, 1
            ) if stats["total"] > 0 else 0.0

        # By probability bucket
        by_probability_bucket = {}
        for record in history:
            prob = record.get("probability", 0)
            if prob < 50:
                bucket = "0-50"
            elif prob < 60:
                bucket = "50-60"
            elif prob < 70:
                bucket = "60-70"
            elif prob < 80:
                bucket = "70-80"
            elif prob < 90:
                bucket = "80-90"
            else:
                bucket = "90-100"

            if bucket not in by_probability_bucket:
                by_probability_bucket[bucket] = {"total": 0, "wins": 0}
            by_probability_bucket[bucket]["total"] += 1
            if record.get("hit"):
                by_probability_bucket[bucket]["wins"] += 1

        # Recent 10
        sorted_history = sorted(history, key=lambda x: x.get("trigger_time", ""), reverse=True)
        recent_10 = [
            {
                "date": r.get("trigger_time", ""),
                "symbol": r.get("symbol_code", ""),
                "return": r.get("actual_return_pct", 0),
                "hit": r.get("hit", False),
            }
            for r in sorted_history[:10]
        ]

        return {
            "total_signals": total,
            "hit_count": hit_count,
            "miss_count": miss_count,
            "win_rate": round(win_rate, 1),
            "avg_return": round(avg_return, 2),
            "avg_return_hits": round(avg_return_hits, 2),
            "avg_return_misses": round(avg_return_misses, 2),
            "by_agent": by_agent,
            "by_probability_bucket": by_probability_bucket,
            "recent_10": recent_10,
        }

    def generate_report(self) -> str:
        """
        Generate a markdown report string with performance summary.

        Returns:
            Markdown-formatted string summarizing signal performance.
        """
        stats = self.get_summary_stats()

        lines = [
            "# Trading Signal Performance Report",
            "",
            f"**Report Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "---",
            "",
            "## Overall Statistics",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Signals | {stats['total_signals']} |",
            f"| Hits | {stats['hit_count']} |",
            f"| Misses | {stats['miss_count']} |",
            f"| Win Rate | {stats['win_rate']}% |",
            f"| Avg Return | {stats['avg_return']}% |",
            f"| Avg Return (Hits) | {stats['avg_return_hits']}% |",
            f"| Avg Return (Misses) | {stats['avg_return_misses']}% |",
            "",
        ]

        # By agent section
        if stats["by_agent"]:
            lines.extend([
                "## Performance by Agent",
                "",
                "| Agent | Total | Wins | Win Rate |",
                "|-------|-------|------|----------|",
            ])
            for agent, agent_stats in stats["by_agent"].items():
                lines.append(
                    f"| {agent} | {agent_stats['total']} | "
                    f"{agent_stats['wins']} | {agent_stats['win_rate']}% |"
                )
            lines.append("")

        # By probability bucket section
        if stats["by_probability_bucket"]:
            lines.extend([
                "## Performance by Probability Bucket",
                "",
                "| Bucket | Total | Wins |",
                "|--------|-------|------|",
            ])
            for bucket in sorted(stats["by_probability_bucket"].keys()):
                bucket_stats = stats["by_probability_bucket"][bucket]
                lines.append(
                    f"| {bucket} | {bucket_stats['total']} | {bucket_stats['wins']} |"
                )
            lines.append("")

        # Recent signals section
        if stats["recent_10"]:
            lines.extend([
                "## Recent 10 Signals",
                "",
                "| Date | Symbol | Return | Hit |",
                "|------|--------|--------|-----|",
            ])
            for r in stats["recent_10"]:
                hit_str = "Yes" if r["hit"] else "No"
                lines.append(
                    f"| {r['date']} | {r['symbol']} | {r['return']}% | {hit_str} |"
                )
            lines.append("")

        # Pending signals info
        lines.extend([
            "---",
            "",
            f"**Pending Signals (awaiting evaluation)**: {len(self.pending_signals)}",
        ])

        return "\n".join(lines)
