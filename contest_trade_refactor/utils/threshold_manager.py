"""
因子阈值配置管理

集中管理所有 alpha 因子数据源中的可调阈值。
支持：
- 从 YAML 文件加载/保存
- API 读写
- 基于回测结果自动校准

配置文件: agents_workspace/factor_thresholds.yaml
"""

import yaml
from pathlib import Path
from typing import Any, Dict
from loguru import logger
from config.config import PROJECT_ROOT


THRESHOLDS_FILE = PROJECT_ROOT / "agents_workspace" / "factor_thresholds.yaml"

# 默认阈值（写死的初始值，会被 YAML 文件覆盖）
DEFAULT_THRESHOLDS = {
    "individual_fund_flow": {
        "absorption_min_net_flow": 5e7,        # 吸筹判定：主力净流入最低值（元）
        "absorption_max_change_pct": 3.0,       # 吸筹判定：涨幅上限（%）
        "absorption_min_change_pct": -2.0,      # 吸筹判定：涨幅下限（%）
        "distribution_max_net_flow": -5e7,      # 出货判定：主力净流出阈值（元）
        "distribution_min_change_pct": -2.0,    # 出货判定：跌幅下限（%）
        "distribution_max_change_pct": 1.0,     # 出货判定：涨幅上限（%）
        "super_large_min_amount": 1e8,          # 超大单最小金额（元）
        "super_large_min_pct": 5.0,             # 超大单最小占比（%）
        "display_top_n": 15,                    # 每类信号展示条数
    },
    "margin_trading": {
        "surge_min_net_buy": 5e7,              # 融资激增：最小净买入（元）
        "short_cover_ratio": 2.0,              # 空头回补：偿还量/卖出量比值
        "short_cover_min_volume": 10000,       # 空头回补：最小偿还量（股）
        "display_top_n": 15,
    },
    "block_trade": {
        "premium_threshold": 0.0,              # 溢价判定线（%）
        "deep_discount_threshold": -5.0,       # 深度折价线（%）
        "large_amount_threshold": 1e8,         # 大额交易阈值（元）
        "concentrated_min_trades": 3,          # 集中买入最小笔数
        "consecutive_min_days": 3,             # 连续交易最小天数
        "display_top_n": 15,
    },
    "sector_fund_flow": {
        "display_top_n": 15,
    },
    "zt_seal_strength": {
        "ultra_strong_threshold": 5.0,         # 封单极强线（封单/流通盘%）
        "strong_min_threshold": 2.0,           # 封单较强下限（%）
        "strong_max_threshold": 5.0,           # 封单较强上限（%）
        "weak_threshold": 1.0,                 # 封单偏弱线（%）
        "first_board_strong_threshold": 3.0,   # 首板强封线（%）
        "display_top_n": 15,
    },
}

# 阈值的元数据（名称、描述、单位、范围）用于前端展示
THRESHOLD_METADATA = {
    "individual_fund_flow": {
        "_label": "个股主力资金流",
        "absorption_min_net_flow": {"label": "吸筹信号 - 最小主力净流入", "unit": "元", "min": 0, "max": 5e8, "step": 1e7},
        "absorption_max_change_pct": {"label": "吸筹信号 - 涨幅上限", "unit": "%", "min": 0, "max": 10, "step": 0.5},
        "absorption_min_change_pct": {"label": "吸筹信号 - 涨幅下限", "unit": "%", "min": -10, "max": 0, "step": 0.5},
        "distribution_max_net_flow": {"label": "出货信号 - 最大净流出", "unit": "元", "min": -5e8, "max": 0, "step": 1e7},
        "distribution_min_change_pct": {"label": "出货信号 - 跌幅下限", "unit": "%", "min": -10, "max": 0, "step": 0.5},
        "distribution_max_change_pct": {"label": "出货信号 - 涨幅上限", "unit": "%", "min": -5, "max": 5, "step": 0.5},
        "super_large_min_amount": {"label": "超大单 - 最小金额", "unit": "元", "min": 0, "max": 1e9, "step": 1e7},
        "super_large_min_pct": {"label": "超大单 - 最小占比", "unit": "%", "min": 0, "max": 20, "step": 1},
        "display_top_n": {"label": "展示条数", "unit": "条", "min": 5, "max": 50, "step": 5},
    },
    "margin_trading": {
        "_label": "融资融券",
        "surge_min_net_buy": {"label": "融资激增 - 最小净买入", "unit": "元", "min": 0, "max": 5e8, "step": 1e7},
        "short_cover_ratio": {"label": "空头回补 - 偿还/卖出比", "unit": "倍", "min": 1, "max": 10, "step": 0.5},
        "short_cover_min_volume": {"label": "空头回补 - 最小偿还量", "unit": "股", "min": 0, "max": 1e6, "step": 5000},
        "display_top_n": {"label": "展示条数", "unit": "条", "min": 5, "max": 50, "step": 5},
    },
    "block_trade": {
        "_label": "大宗交易",
        "premium_threshold": {"label": "溢价判定线", "unit": "%", "min": -5, "max": 5, "step": 0.5},
        "deep_discount_threshold": {"label": "深度折价线", "unit": "%", "min": -20, "max": 0, "step": 1},
        "large_amount_threshold": {"label": "大额交易阈值", "unit": "元", "min": 0, "max": 1e9, "step": 1e7},
        "concentrated_min_trades": {"label": "集中买入 - 最小笔数", "unit": "笔", "min": 2, "max": 10, "step": 1},
        "consecutive_min_days": {"label": "连续交易 - 最小天数", "unit": "天", "min": 2, "max": 10, "step": 1},
        "display_top_n": {"label": "展示条数", "unit": "条", "min": 5, "max": 50, "step": 5},
    },
    "sector_fund_flow": {
        "_label": "板块资金流向",
        "display_top_n": {"label": "展示条数", "unit": "条", "min": 5, "max": 50, "step": 5},
    },
    "zt_seal_strength": {
        "_label": "涨停封单强度",
        "ultra_strong_threshold": {"label": "封单极强线", "unit": "%", "min": 2, "max": 15, "step": 0.5},
        "strong_min_threshold": {"label": "封单较强下限", "unit": "%", "min": 0.5, "max": 5, "step": 0.5},
        "strong_max_threshold": {"label": "封单较强上限", "unit": "%", "min": 3, "max": 15, "step": 0.5},
        "weak_threshold": {"label": "封单偏弱线", "unit": "%", "min": 0.1, "max": 3, "step": 0.1},
        "first_board_strong_threshold": {"label": "首板强封线", "unit": "%", "min": 1, "max": 10, "step": 0.5},
        "display_top_n": {"label": "展示条数", "unit": "条", "min": 5, "max": 50, "step": 5},
    },
}


class ThresholdManager:
    """阈值管理器"""

    def __init__(self):
        self._thresholds: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self):
        """从文件加载阈值，不存在则用默认值"""
        if THRESHOLDS_FILE.exists():
            try:
                with open(THRESHOLDS_FILE, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f) or {}
                # 合并默认值（确保新增的阈值有默认值）
                self._thresholds = {}
                for factor, defaults in DEFAULT_THRESHOLDS.items():
                    self._thresholds[factor] = {**defaults, **(loaded.get(factor) or {})}
                logger.info(f"阈值已从 {THRESHOLDS_FILE} 加载")
            except Exception as e:
                logger.error(f"加载阈值文件失败: {e}")
                self._thresholds = {k: dict(v) for k, v in DEFAULT_THRESHOLDS.items()}
        else:
            self._thresholds = {k: dict(v) for k, v in DEFAULT_THRESHOLDS.items()}
            self.save()

    def save(self):
        """保存阈值到文件"""
        THRESHOLDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(THRESHOLDS_FILE, "w", encoding="utf-8") as f:
            yaml.dump(self._thresholds, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"阈值已保存到 {THRESHOLDS_FILE}")

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """获取所有阈值"""
        return self._thresholds

    def get(self, factor_name: str) -> Dict[str, Any]:
        """获取某个因子的阈值"""
        return self._thresholds.get(factor_name, {})

    def get_value(self, factor_name: str, key: str, default: Any = None) -> Any:
        """获取单个阈值值"""
        return self._thresholds.get(factor_name, {}).get(key, default)

    def update(self, factor_name: str, updates: Dict[str, Any]):
        """更新某个因子的阈值"""
        if factor_name not in self._thresholds:
            self._thresholds[factor_name] = {}
        self._thresholds[factor_name].update(updates)
        self.save()

    def reset(self, factor_name: str = ""):
        """重置阈值到默认值"""
        if factor_name:
            if factor_name in DEFAULT_THRESHOLDS:
                self._thresholds[factor_name] = dict(DEFAULT_THRESHOLDS[factor_name])
        else:
            self._thresholds = {k: dict(v) for k, v in DEFAULT_THRESHOLDS.items()}
        self.save()

    def auto_calibrate(self, factor_name: str, backtest_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        基于回测结果自动校准阈值。

        策略：
        - 如果 IC > 0.05 且因子有效，保持当前阈值
        - 如果 IC < 0.03，因子无效，放宽阈值（降低筛选门槛获取更多样本）
        - 如果分组收益不单调，缩紧阈值（提高筛选精度）
        """
        validation = backtest_result.get("walk_forward") or backtest_result.get("out_of_sample")
        if not isinstance(validation, dict) or validation.get("status") != "ok":
            return {
                "status": "blocked_no_out_of_sample",
                "changes": {},
                "reason": "阈值校准必须先通过滚动样本外验证",
            }
        if int(validation.get("test_samples", 0) or 0) < 30:
            return {
                "status": "insufficient_out_of_sample",
                "changes": {},
                "samples": int(validation.get("test_samples", 0) or 0),
            }

        changes = {}
        ic_values = backtest_result.get("ic_values", {})
        horizons = backtest_result.get("horizons", {})
        validation_horizons = validation.get("horizons", {})

        # 取 T+1 的 IC 作为主要参考
        ic_t1 = validation.get("ic_values", {}).get("t1", ic_values.get("t1"))
        t1_stats = validation_horizons.get("t1", horizons.get("t1", {}))
        hit_rate = t1_stats.get("hit_rate")

        if ic_t1 is None or hit_rate is None:
            return {"status": "insufficient_data", "changes": {}}

        current = self._thresholds.get(factor_name, {})

        if factor_name == "individual_fund_flow":
            if ic_t1 > 0.05 and hit_rate > 0.52:
                # 因子有效，可以适当缩紧阈值提高精度
                changes["absorption_min_net_flow"] = current.get("absorption_min_net_flow", 5e7) * 1.2
            elif ic_t1 < 0.03:
                # 因子弱/无效，放宽阈值获取更多样本
                changes["absorption_min_net_flow"] = current.get("absorption_min_net_flow", 5e7) * 0.7
                changes["absorption_max_change_pct"] = min(5.0, current.get("absorption_max_change_pct", 3.0) + 1.0)

        elif factor_name == "margin_trading":
            if ic_t1 > 0.05 and hit_rate > 0.52:
                changes["surge_min_net_buy"] = current.get("surge_min_net_buy", 5e7) * 1.2
            elif ic_t1 < 0.03:
                changes["surge_min_net_buy"] = current.get("surge_min_net_buy", 5e7) * 0.7

        elif factor_name == "zt_seal_strength":
            if ic_t1 > 0.05 and hit_rate > 0.55:
                # 封单强度因子有效，提高极强线
                changes["ultra_strong_threshold"] = current.get("ultra_strong_threshold", 5.0) + 0.5
            elif ic_t1 < 0.03:
                # 放宽
                changes["ultra_strong_threshold"] = max(2.0, current.get("ultra_strong_threshold", 5.0) - 1.0)

        elif factor_name == "block_trade":
            if ic_t1 > 0.05:
                changes["deep_discount_threshold"] = current.get("deep_discount_threshold", -5.0) - 1.0
            elif ic_t1 < 0.03:
                changes["deep_discount_threshold"] = min(-2.0, current.get("deep_discount_threshold", -5.0) + 1.5)

        if changes:
            self.update(factor_name, changes)

        return {
            "status": "calibrated" if changes else "no_change",
            "ic_t1": ic_t1,
            "hit_rate": hit_rate,
            "changes": changes,
        }


# 全局实例
THRESHOLD_MANAGER = ThresholdManager()
