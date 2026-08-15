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
from config.config import WORKSPACE_ROOT
from utils.cn_price_provider import get_stock_zh_a_hist
from utils.date_utils import get_previous_trading_date

def _normalize_compact_date(dt) -> str:
    return dt.strftime("%Y%m%d")


class PerformanceTracker:
    """Tracks and evaluates the historical performance of trading signals."""

    def __init__(self):
        self.workspace_dir = WORKSPACE_ROOT / "performance"
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

        Returns the number of signals recorded so callers can use it for downstream
        tracking (including non-buy watchlist signals if desired).
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
                    "probability_value": signal.get("probability_value", None),
                    "buy_score": signal.get("buy_score", 0),
                    "expected_return_t1_pct": signal.get("expected_return_t1_pct", 0),
                    "gate_report": signal.get("next_day_gate_report") or {},
                    "agent_name": signal.get("agent_name", ""),
                    "scorecard": signal.get("next_day_factor_scorecard") or {},
                    "metadata": {
                        "strategy": signal.get("strategy"),
                        "market_trend": signal.get("market_trend"),
                        "risk_sentiment": signal.get("risk_sentiment"),
                        "source": "performance_tracker",
                    },
                }
                self.pending_signals.append(record)

            self._save_json(self.pending_file, self.pending_signals)
            skipped = len(best_signals) - len(tradable_signals)
            logger.info(
                f"Recorded {len(tradable_signals)} buy signals for trigger_time={trigger_time}; "
                f"skipped {skipped} watchlist candidates"
            )
            return len(tradable_signals)
        except Exception as e:
            logger.error(f"Error recording signals: {e}")
            return 0

    async def evaluate_pending(self):
        """
        Evaluate pending signals that are at least 1 trading day old.

        For each eligible signal:
        - Fetch future prices from trigger trade-date onwards.
        - Determine the actual next trading day (entry) open and day N close/returns.
        - Store t1/t3/t5/max_gain/max_loss categories (entry basis: next-day open).
        - Move from pending to history when the requested horizon is fully observable.
        """
        from utils.market_manager import GLOBAL_MARKET_MANAGER

        market_name = "CN-Stock"
        now = datetime.now()
        trade_dates = GLOBAL_MARKET_MANAGER.get_trade_date(market_name=market_name, verbose=False)
        trade_dates = [str(td).replace("-", "").replace("/", "") for td in trade_dates]
        trade_date_set = set(trade_dates)

        def _next_trading_dates(trigger_compact: str, count: int) -> List[str]:
            out = []
            for td in trade_dates:
                if td > trigger_compact:
                    out.append(td)
                    if len(out) >= count:
                        break
            return out

        still_pending = []
        for signal in self.pending_signals:
            try:
                trigger_time = signal.get("trigger_time")
                if not trigger_time:
                    continue
                trigger_dt = datetime.strptime(trigger_time, "%Y-%m-%d %H:%M:%S")
                trigger_compact = _normalize_compact_date(trigger_dt)
                # If trigger day isn't in trade calendar, evaluate from the next trading day.
                if trade_dates and trigger_compact not in trade_date_set:
                    upcoming = _next_trading_dates(trigger_compact, 1)
                    if not upcoming:
                        still_pending.append(signal)
                        continue
                    trigger_compact = upcoming[0]

                nxt = _next_trading_dates(trigger_compact, 6)
                if len(nxt) < 6:
                    # Not enough history yet; keep pending.
                    still_pending.append(signal)
                    continue

                entry_date = nxt[0]
                horizon_dates = nxt[:5]  # T1..T5 close dates
                ak_symbol = str(signal["symbol_code"]).split(".")[0]

                start_compact = trigger_compact
                end_compact = horizon_dates[-1]

                df = get_stock_zh_a_hist(
                    symbol=ak_symbol,
                    start_date=start_compact,
                    end_date=end_compact,
                    adjust="qfq",
                    verbose=False,
                )
                if df is None or len(df) < 2:
                    still_pending.append(signal)
                    continue

                df["日期"] = pd.to_datetime(df["日期"], errors="coerce").dt.strftime("%Y%m%d")
                df = df.drop_duplicates("日期", keep="last").sort_values("日期").reset_index(drop=True)
                row_map = {str(r["日期"]): r for _, r in df.iterrows()}

                # Entry = next-day open. If missing, keep pending.
                if entry_date not in row_map:
                    still_pending.append(signal)
                    continue
                entry_open = float(row_map[entry_date]["开盘"])

                def _close(d: str):
                    r = row_map.get(d)
                    if r is None:
                        return None
                    return float(r["收盘"])

                closes = {d: _close(d) for d in horizon_dates}
                if not all(closes.values()):
                    still_pending.append(signal)
                    continue

                t1_close = closes[horizon_dates[0]]
                t3_close = closes[horizon_dates[2]]
                t5_close = closes[horizon_dates[4]]

                high_col = "最高" if "最高" in df.columns else None
                low_col = "最低" if "最低" in df.columns else None
                max_high = entry_open
                min_low = entry_open
                for hd in horizon_dates:
                    r = row_map.get(hd)
                    if r is None:
                        continue
                    if high_col:
                        try:
                            max_high = max(max_high, float(r[high_col]))
                        except Exception:
                            pass
                    if low_col:
                        try:
                            min_low = min(min_low, float(r[low_col]))
                        except Exception:
                            pass

                def pct(a: float, b: float) -> float:
                    return (b - a) / a * 100.0 if a else 0.0

                t1_return = pct(entry_open, t1_close)
                t3_return = pct(entry_open, t3_close)
                t5_return = pct(entry_open, t5_close)
                max_gain = pct(entry_open, max_high)
                max_loss = pct(entry_open, min_low)

                action = str(signal.get("action", "buy")).lower()
                hit = t1_return > 0 if action == "buy" else t1_return < 0

                history_record = {
                    "trigger_time": trigger_time,
                    "trigger_date": trigger_compact,
                    "entry_date": entry_date,
                    "symbol_code": signal["symbol_code"],
                    "symbol_name": signal.get("symbol_name", ""),
                    "action": action,
                    "buy_decision": signal.get("buy_decision", ""),
                    "probability": signal.get("probability", 0),
                    "agent_name": signal.get("agent_name", ""),
                    "buy_score": signal.get("buy_score", 0),
                    "expected_return_t1_pct": signal.get("expected_return_t1_pct", 0),
                    "gate_report": signal.get("gate_report") or {},
                    "scorecard": signal.get("scorecard") or {},
                    "entry_price": round(entry_open, 3),
                    "t1_close": round(t1_close, 3),
                    "t3_close": round(t3_close, 3),
                    "t5_close": round(t5_close, 3),
                    "t1_return_pct": round(t1_return, 3),
                    "t3_return_pct": round(t3_return, 3),
                    "t5_return_pct": round(t5_return, 3),
                    "max_gain_pct": round(max_gain, 3),
                    "max_loss_pct": round(max_loss, 3),
                    "actual_return_pct": round(t1_return, 4),
                    "hit": hit,
                    "evaluated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                }

                self.performance_history.append(history_record)
                logger.info(
                    f"Evaluated {signal['symbol_code']} entry={entry_date} "
                    f"t1={t1_return:.2f}% t3={t3_return:.2f}% t5={t5_return:.2f}% hit={hit}"
                )

            except Exception as e:
                logger.warning(
                    f"Failed to evaluate signal {signal.get('symbol_code', '?')}: {e}"
                )
                still_pending.append(signal)

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
