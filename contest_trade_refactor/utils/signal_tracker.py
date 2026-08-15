"""���号跟踪器
记录每个信���的后续表���，用���验���策略有���性和���准概率
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import pandas as pd


class SignalTracker:
    """跟踪信号的实际���现"""

    def __init__(self, workspace_dir: Path = None):
        if workspace_dir is None:
            from config.config import WORKSPACE_ROOT
            workspace_dir = WORKSPACE_ROOT

        self.signals_dir = workspace_dir / "signals_tracking"
        self.signals_dir.mkdir(parents=True, exist_ok=True)

        self.performance_file = self.signals_dir / "signal_performance.jsonl"
        self.summary_file = self.signals_dir / "performance_summary.json"

    def record_signals(
        self,
        signals: List[Dict[str, Any]],
        trigger_time: str,
        metadata: Dict[str, Any] = None
    ) -> None:
        """
        记录新生成的���号

        Args:
            signals: ���入信号���表
            trigger_time: 触发���间
            metadata: 额���元数据（���场环���等）
        """
        if not signals:
            return

        record_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for signal in signals:
            record = {
                "record_time": record_time,
                "trigger_time": trigger_time,
                "symbol_code": signal.get("symbol_code", ""),
                "symbol_name": signal.get("symbol_name", ""),
                "buy_score": signal.get("buy_score", 0),
                "probability_value": signal.get("probability_value", 0.5),
                "signal_tier": signal.get("signal_tier", ""),
                "tier_confidence": signal.get("tier_confidence", 0),
                "expected_return_t1_pct": signal.get("expected_return_t1_pct", 0),
                "entry_price": None,  # 需要后���填充
                "scorecard": signal.get("next_day_factor_scorecard", {}),
                "metadata": metadata or {},
                "performance": {
                    "tracked": False,
                    "t1_return_pct": None,
                    "t3_return_pct": None,
                    "t5_return_pct": None,
                    "max_gain_pct": None,
                    "max_loss_pct": None,
                    "tracking_date": None,
                }
            }

            # 追加到JSONL文件
            with open(self.performance_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def update_performance(
        self,
        symbol_code: str,
        trigger_time: str,
        performance_data: Dict[str, Any]
    ) -> bool:
        """
        更新���号的实���表���数���

        Args:
            symbol_code: 股票代码
            trigger_time: 触发时间
            performance_data: {
                "entry_price": float,
                "t1_return_pct": float,
                "t3_return_pct": float,
                "t5_return_pct": float,
                "max_gain_pct": float,
                "max_loss_pct": float,
            }
        """
        if not self.performance_file.exists():
            return False

        # 读取���有记录
        records = []
        updated = False

        with open(self.performance_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)

                # 匹���记录
                if (
                    record["symbol_code"] == symbol_code
                    and record["trigger_time"] == trigger_time
                ):
                    record["entry_price"] = performance_data.get("entry_price")
                    record["performance"].update({
                        "tracked": True,
                        "t1_return_pct": performance_data.get("t1_return_pct"),
                        "t3_return_pct": performance_data.get("t3_return_pct"),
                        "t5_return_pct": performance_data.get("t5_return_pct"),
                        "max_gain_pct": performance_data.get("max_gain_pct"),
                        "max_loss_pct": performance_data.get("max_loss_pct"),
                        "tracking_date": datetime.now().strftime("%Y-%m-%d"),
                    })
                    updated = True

                records.append(record)

        if updated:
            # 重写文件
            with open(self.performance_file, "w", encoding="utf-8") as f:
                for record in records:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return updated

    def get_performance_summary(
        self,
        min_samples: int = 10,
        days_back: int = 30
    ) -> Dict[str, Any]:
        """
        生成���能摘要���计

        Returns:
            {
                "total_signals": int,
                "tracked_signals": int,
                "by_tier": {
                    "A": {"count": int, "avg_t1_return": float, "win_rate": float, ...},
                    "B": {...},
                    "C": {...}
                },
                "overall": {"avg_t1_return": float, "win_rate": float, ...},
                "probability_calibration": {"slope": float, "intercept": float}
            }
        """
        if not self.performance_file.exists():
            return self._empty_summary()

        # 读取所有已跟踪���记录
        cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        tracked_records = []

        with open(self.performance_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)

                if (
                    record["performance"]["tracked"]
                    and record["trigger_time"] >= cutoff_date
                ):
                    tracked_records.append(record)

        if len(tracked_records) < min_samples:
            return self._empty_summary()

        # 按tier分���统计
        by_tier = {}
        for tier in ["A", "B", "C"]:
            tier_records = [r for r in tracked_records if r.get("signal_tier") == tier]
            by_tier[tier] = self._calculate_tier_stats(tier_records)

        # 整体���计
        overall = self._calculate_tier_stats(tracked_records)

        # ���率校准（简单线性回归）
        calibration = self._calculate_probability_calibration(tracked_records)

        summary = {
            "total_signals": len(tracked_records),
            "tracked_signals": len(tracked_records),
            "days_back": days_back,
            "by_tier": by_tier,
            "overall": overall,
            "probability_calibration": calibration,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        # 保存摘要
        with open(self.summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        return summary

    def _calculate_tier_stats(self, records: List[Dict]) -> Dict[str, Any]:
        """���算某一分层的统计���据"""
        if not records:
            return {
                "count": 0,
                "avg_t1_return": 0.0,
                "avg_t3_return": 0.0,
                "avg_t5_return": 0.0,
                "win_rate_t1": 0.0,
                "win_rate_t5": 0.0,
                "max_gain": 0.0,
                "max_loss": 0.0,
                "sharpe_ratio": 0.0,
            }

        t1_returns = [
            r["performance"]["t1_return_pct"]
            for r in records
            if r["performance"]["t1_return_pct"] is not None
        ]
        t3_returns = [
            r["performance"]["t3_return_pct"]
            for r in records
            if r["performance"]["t3_return_pct"] is not None
        ]
        t5_returns = [
            r["performance"]["t5_return_pct"]
            for r in records
            if r["performance"]["t5_return_pct"] is not None
        ]

        avg_t1 = sum(t1_returns) / len(t1_returns) if t1_returns else 0.0
        avg_t3 = sum(t3_returns) / len(t3_returns) if t3_returns else 0.0
        avg_t5 = sum(t5_returns) / len(t5_returns) if t5_returns else 0.0

        win_rate_t1 = (
            sum(1 for r in t1_returns if r > 0) / len(t1_returns) * 100
            if t1_returns else 0.0
        )
        win_rate_t5 = (
            sum(1 for r in t5_returns if r > 0) / len(t5_returns) * 100
            if t5_returns else 0.0
        )

        # 简单���普比率���假设无风���利率为0）
        if t5_returns and len(t5_returns) > 1:
            std = pd.Series(t5_returns).std()
            sharpe = (avg_t5 / std) if std > 0 else 0.0
        else:
            sharpe = 0.0

        return {
            "count": len(records),
            "avg_t1_return": round(avg_t1, 3),
            "avg_t3_return": round(avg_t3, 3),
            "avg_t5_return": round(avg_t5, 3),
            "win_rate_t1": round(win_rate_t1, 2),
            "win_rate_t5": round(win_rate_t5, 2),
            "max_gain": round(max([r["performance"]["max_gain_pct"] or 0 for r in records]), 3),
            "max_loss": round(min([r["performance"]["max_loss_pct"] or 0 for r in records]), 3),
            "sharpe_ratio": round(sharpe, 3),
        }

    def _calculate_probability_calibration(
        self,
        records: List[Dict]
    ) -> Dict[str, Any]:
        """
        计算概率校准参���

        通过线性回归：actual_win_rate = slope * predicted_prob + intercept
        """
        if len(records) < 20:
            return {"slope": 1.0, "intercept": 0.0, "sample_size": len(records)}

        # 按���测���率分桶
        buckets = [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0]
        bucket_data = []

        for i in range(len(buckets) - 1):
            lower = buckets[i]
            upper = buckets[i + 1]

            bucket_records = [
                r for r in records
                if lower <= r["probability_value"] < upper
                and r["performance"]["t1_return_pct"] is not None
            ]

            if len(bucket_records) < 5:
                continue

            predicted_prob = sum(r["probability_value"] for r in bucket_records) / len(bucket_records)
            actual_wins = sum(1 for r in bucket_records if r["performance"]["t1_return_pct"] > 0)
            actual_rate = actual_wins / len(bucket_records)

            bucket_data.append((predicted_prob, actual_rate))

        if len(bucket_data) < 3:
            return {"slope": 1.0, "intercept": 0.0, "sample_size": len(records)}

        # 简单线���回归
        x_values = [d[0] for d in bucket_data]
        y_values = [d[1] for d in bucket_data]

        n = len(bucket_data)
        x_mean = sum(x_values) / n
        y_mean = sum(y_values) / n

        numerator = sum((x_values[i] - x_mean) * (y_values[i] - y_mean) for i in range(n))
        denominator = sum((x_values[i] - x_mean) ** 2 for i in range(n))

        slope = numerator / denominator if denominator > 0 else 1.0
        intercept = y_mean - slope * x_mean

        return {
            "slope": round(slope, 3),
            "intercept": round(intercept, 3),
            "sample_size": len(records),
            "buckets_used": len(bucket_data),
        }

    def _empty_summary(self) -> Dict[str, Any]:
        """返回空摘���"""
        return {
            "total_signals": 0,
            "tracked_signals": 0,
            "days_back": 0,
            "by_tier": {},
            "overall": {},
            "probability_calibration": {"slope": 1.0, "intercept": 0.0},
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def get_recent_signals(self, days: int = 7) -> List[Dict[str, Any]]:
        """获取最���N天的信号"""
        if not self.performance_file.exists():
            return []

        cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        recent = []

        with open(self.performance_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record["trigger_time"] >= cutoff_date:
                    recent.append(record)

        return recent
