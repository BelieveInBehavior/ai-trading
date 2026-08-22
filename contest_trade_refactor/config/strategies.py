"""Trading strategy definitions.

策略现在是“策略包”形式：每个策略放在 strategies/<name>/ 目录下，
包含 strategy.yaml（参数）、beliefs.yaml（研究信念）、tools.yaml（研究工具）、
以及可选的 backtest.yaml / SKILL.md。

本模块保持 get_strategy / get_strategies 兼容入口：
- 优先从 strategies/<name>/ 读取；
- 缺失时回退到历史内置字典 SWING / MOMENTUM（保持 CLI / Web 不破坏）。
"""

from __future__ import annotations

import json
import copy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRATEGIES_DIR = PROJECT_ROOT / "strategies"


STRATEGY_NAMES = ("swing", "momentum", "strong_diverge", "first_board_continue", "main_trend", "quant_research")

DEFAULTS = {
    "quantitative_screen_top_k": 80,
    "quantitative_screen_history_days": 260,
    "min_weekly_trend_score": 55.0,
    "min_relative_strength_score": 45.0,
    "min_relative_strength_20d_pct": 0.0,
    "min_daily_entry_score": 50.0,
    "min_flow_confirmation_score": 50.0,
    "min_regime_confirmation_score": 50.0,
    "max_prev_day_gain_pct": 5.0,
    "max_ma20_deviation_pct": 8.0,
    "require_min_buys": 0,
    "max_research_rounds": 10,
}


# ---------------------------------------------------------------------------
# 旧字典（fallback / compatibility）
# ---------------------------------------------------------------------------
SWING = {
    "id": "swing",
    "name": "中长线 / 趋势交易",
    "short_name": "Swing·趋势",
    "horizon": "中长线（趋势）",
    "style": "趋势确认 + 回踩 20 日线",
    "risk_note": "宁可错过也不追高，适合持有数周至数月",
    "description": (
        "基本面定方向，技术面定买卖点。"
        "筛选趋势初期/回踩确认的机会，宁可错过也不追已经大幅偏离 20 日线的标的。"
    ),
    "tags": ["不追高", "趋势确认", "回踩低吸", "中长线"],
    "quantitative_screen_top_k": 80,
    "quantitative_screen_history_days": 260,
    "min_weekly_trend_score": 62.0,
    "min_relative_strength_score": 52.0,
    "min_relative_strength_20d_pct": 0.0,
    "min_daily_entry_score": 55.0,
    "min_flow_confirmation_score": 55.0,
    "min_regime_confirmation_score": 52.0,
    "max_prev_day_gain_pct": 5.0,
    "max_ma20_deviation_pct": 6.0,
    "quantitative_max_ma20_deviation_pct": 6.0,
    "quantitative_max_prev_day_gain_pct": 5.0,
    "quantitative_ma20_deviation_penalty": 3.0,
    "require_min_buys": 0,
    "max_research_rounds": 10,
    "belief_list": [
        "基于行业景气度、公司基本面和估值位置，寻找处于趋势初/中期的优质成长股。"
        "技术面要求温和放量、靠近20日线回踩企稳，避免只买已经脱离5/10/20日线过多的强弩之末标的。",
        "基于技术面趋势确认、回踩20日线或关键均线企稳、相对强度温和放大，寻找中长线趋势跟随标的。"
        "拒绝追高已经暴涨、远超20日线的股票，优先选择趋势刚确认、风险收益比较优的标的。",
        "基于公司基本面（营收、利润、ROE、现金流、估值）和行业景气位置，寻找基本面向上但股价尚未透支的中期机会。"
        "技术面要求上升趋势仍在，买点尽量靠近支撑/20日线，不追已经过热的强势股。",
        "基于宏观经济、行业景气与政策催化，寻找未来几个季度景气持续向上的方向龙头。"
        "要求估值合理、趋势积极，耐心等待回踩买点。",
    ],
    "ranker_overrides": {
        "min_risk_reward_score": 58.0,
        "expected_return_floor_pct": 0.4,
        "max_prev_day_gain_pct": 5.0,
        "max_ma20_deviation_pct": 6.0,
        "min_relative_strength_20d_pct": 0.0,
        "min_flow_confirmation_score": 55.0,
        "min_regime_confirmation_score": 52.0,
        "strong_trend_penalty_bias": -3.0,
    },
}

MOMENTUM = {
    "id": "momentum",
    "name": "短期收益 / 动量交易",
    "short_name": "Momentum",
    "description": (
        "目标是短期高弹性。追求市场最强主线、资金共识、突破/强势加速；"
        "允许一定程度追高，核心是跟随资金与情绪并严格控制止损。"
    ),
    "horizon": "短线 1~3 交易日",
    "style": "强势主线 / 资金动量",
    "risk_note": "高波动、高回撤，严格止损",
    "tags": ["高弹性", "强势主线", "资金动量", "短线"],
    "quantitative_screen_top_k": 120,
    "quantitative_screen_history_days": 260,
    "min_weekly_trend_score": 56.0,
    "min_relative_strength_score": 52.0,
    "min_relative_strength_20d_pct": 0.0,
    "min_daily_entry_score": 55.0,
    "min_flow_confirmation_score": 52.0,
    "min_regime_confirmation_score": 50.0,
    "max_prev_day_gain_pct": 14.0,
    "max_ma20_deviation_pct": 45.0,
    "quantitative_max_ma20_deviation_pct": 45.0,
    "quantitative_max_prev_day_gain_pct": 15.0,
    "quantitative_ma20_deviation_penalty": 0.5,
    "quantitative_hard_min_weekly_score": 0.0,
    "quantitative_hard_min_relative_score": 0.0,
    "quantitative_hard_min_relative_20d_pct": -100.0,
    "require_min_buys": 0,
    "max_research_rounds": 12,
    "belief_list": [
        "关注资金共识最强、量比(今日量/前5日均量)和额比(今日额/前5日均额)明确、催化剂明确的短线主线。"
        "买强势、买放量、买强主线龙头；短线1-3日节奏为主，准备严格止损。",
        "偏好高动量、量比>=1.2、额比>=1.2、资金净流入靠前、处于板块主升阶段的标的。"
        "接受相对高位，寻找更强加速；一旦动能衰退就快速离场。",
        "喜欢事件催化、涨价、订单、超预期公告带来的短线博弈机会；优先资金合力与龙虎榜关注标的。",
        "主线板块中的弹性标的，敢于在资金共识最强时交易，但严格止损，不恋战。",
    ],
    "ranker_overrides": {
        "min_buy_score": 55.0,
        "min_probability": 0.45,
        "min_technical_score": 0.0,
        "min_tradeability_score": 50.0,
        "min_data_quality_score": 40.0,
        "min_risk_reward_score": 50.0,
        "reject_below_rr_without_company_catalyst": True,
        "min_rr_without_company_catalyst": 1.0,
        "expected_return_floor_pct": -999.0,
        "max_prev_day_gain_pct": 14.0,
        "max_ma20_deviation_pct": 45.0,
        "min_relative_strength_20d_pct": 0.0,
        "min_flow_confirmation_score": 50.0,
        "min_regime_confirmation_score": 50.0,
        "enforce_multi_timeframe": False,
        "enforce_flow_confirmation_if_available": False,
        "strong_trend_penalty_bias": -3.0,
    },
}


def _deepcopy_strategy(d: dict) -> dict:
    return copy.deepcopy(d)


def _load_strategy_dir(name: str) -> dict | None:
    """Load strategies/<name>/strategy.yaml if present."""
    import yaml
    path = STRATEGIES_DIR / name / "strategy.yaml"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data["id"] = str(data.get("id") or name)
    # 兼容：beliefs / backtest / tools 如果散在 strategy.yaml 也作为顶层键保留
    beliefs_path = STRATEGIES_DIR / name / "beliefs.yaml"
    if isinstance(data.get("belief_list"), list) and data["belief_list"] and Path(beliefs_path).exists():
        # strategy.yaml 中的 belief_list 优先，但允许 beliefs.yaml 兜底
        pass
    if not isinstance(data.get("belief_list"), list):
        try:
            with open(beliefs_path, "r", encoding="utf-8") as f:
                bdata = yaml.safe_load(f) or {}
            data["belief_list"] = bdata.get("belief_list") or bdata.get("beliefs") or []
        except Exception:
            data["belief_list"] = []

    tools_path = STRATEGIES_DIR / name / "tools.yaml"
    data["tool_list"] = None
    if tools_path.exists():
        try:
            with open(tools_path, "r", encoding="utf-8") as f:
                tdata = yaml.safe_load(f) or {}
            tools = tdata.get("tools") or tdata.get("tool_list") or []
            if isinstance(tools, list):
                data["tool_list"] = tools
        except Exception:
            data["tool_list"] = None

    return data


_STRATEGY_CACHE: dict[str, dict] = {}


def get_strategy(strategy: str):
    """Return the strategy config dict. Defaults to momentum for unknown values."""
    if not strategy:
        return _load_or_default("momentum")
    lookup = str(strategy or "").lower()
    if lookup in {"momentum", "short", "短线", "短期", "短期收益", "动量"}:
        return _load_or_default("momentum")
    if lookup in {"swing", "trend", "中长线", "趋势"}:
        return _load_or_default("swing")
    if lookup in {"default", "legacy"}:
        return _load_or_default("swing")
    return _load_or_default(lookup)


def _load_or_default(name: str) -> dict:
    if name in _STRATEGY_CACHE:
        return _STRATEGY_CACHE[name]
    loaded = _load_strategy_dir(name)
    legacy = _legacy_for(name)
    cfg = _deep_merge_strategy(legacy, loaded)
    _STRATEGY_CACHE[name] = cfg
    return cfg


def _legacy_for(name: str) -> dict:
    if name == "swing":
        return _deep_merge_strategy({}, SWING)
    if name == "momentum":
        return _deep_merge_strategy({}, MOMENTUM)
    return _deep_merge_strategy({}, MOMENTUM)


def _deep_merge_strategy(base: dict, override: dict | None) -> dict:
    result = _deep_merge(base)
    if not override:
        return result
    merged = _deep_merge(result)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = _recursive_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def _recursive_merge(a: dict, b: dict) -> dict:
    out = _deep_merge(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _recursive_merge(out[k], v)
        else:
            out[k] = v
    return out


def _deep_merge(d: dict) -> dict:
    return copy.deepcopy(d)


def get_strategies():
    """Return all strategy configs, ordered for the UI + any packages on disk."""
    # 优先读目录里存在的策略
    out = []
    seen = set()
    if STRATEGIES_DIR.exists():
        for p in sorted(STRATEGIES_DIR.iterdir()):
            if p.is_dir() and (p / "strategy.yaml").exists():
                name = p.name
                if name in seen:
                    continue
                seen.add(name)
                out.append(_load_or_default(name))
    for name in STRATEGY_NAMES:
        if name not in seen:
            seen.add(name)
            out.append(_load_or_default(name))
    return out
