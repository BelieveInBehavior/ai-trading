"""Trading strategy definitions.

Each strategy tunes:
- screener thresholds (Stage 0 filter)
- ranker gate thresholds (Stage 2+3 buy confirmation)
- research beliefs / behavior (research prompts)
- consensus/gate behavior for the chosen horizon.
"""

from __future__ import annotations

STRATEGY_NAMES = ("swing", "momentum")

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
# 1) 中长线 / 趋势交易（swing）
#    - 偏向趋势确认后回踩买入，避免已经大幅偏离 20 日线的追高
#    - 更看重周线趋势、相对强度、基本面方向、风险报酬率
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
    # screener / ranker gates
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
    # Stage 0 quantitative screener is normally "strong stocks pass"; for Swing we
    # explicitly reject names that are too far above MA20 before Research Agent.
    "quantitative_max_ma20_deviation_pct": 6.0,
    "quantitative_max_prev_day_gain_pct": 5.0,
    "quantitative_ma20_deviation_penalty": 3.0,
    "require_min_buys": 0,
    "max_research_rounds": 10,
    "belief_list": [
        "基于行业景气度、公司基本面和估值位置，寻找处于趋势初/中期的优质成长股。"
        "技术面要求温和放量、靠近20日线回踩企稳，避免只买已经脱离5/10/20日线过多的强弩之末标的。"
        "适合中长线持有，等待趋势延续与业绩兑现。",
        "基于技术面趋势确认、回踩20日线或关键均线企稳、相对强度温和放大，寻找中长线趋势跟随标的。"
        "拒绝追高已经暴涨、远超20日线的股票，优先选择趋势刚确认、风险收益比较优的标的。",
        "基于公司基本面（营收、利润、ROE、现金流、估值）和行业景气位置，寻找基本面向上但股价尚未透支的中期投资机会。"
        "技术面要求上升趋势仍在，但买点尽量靠近支撑/20日线，不追已经过热的强势股。",
        "基于宏观经济、行业景气与政策催化，寻找未来几个季度景气持续向上的方向龙头。"
        "要求估值合理、趋势积极，宁可等待回踩买点也不追高，目标是中长期趋势收益。",
    ],
    "ranker_overrides": {
        "min_risk_reward_score": 58.0,
        "expected_return_floor_pct": 0.4,
        "max_prev_day_gain_pct": 5.0,
        "max_ma20_deviation_pct": 6.0,
        "min_relative_strength_20d_pct": 0.0,
        "min_flow_confirmation_score": 55.0,
        "min_regime_confirmation_score": 52.0,
        "strong_trend_penalty_bias": 0.0,
    },
}

# ---------------------------------------------------------------------------
# 2) 短期收益 / 动量交易（momentum）
#    - 更偏向近期强势、资金主线和日内弹性
#    - 容忍相对较高的 MA20 偏离，只要处在主线且动能强
#    - 更看重量比、资金流入、催化剂、市场风险偏好
# ---------------------------------------------------------------------------
MOMENTUM = {
    "id": "momentum",
    "name": "短期收益 / 动量交易",
    "short_name": "Momentum",
    "description": (
        "目标是短期高弹性。追求市场最强主线、资金共识、突破/强势加速；"
        "允许一定程度追高，核心是跟随资金与情绪并严格控制止损。"
    ),
    "horizon": "短期收益",
    "style": "强势主线 / 资金动量",
    "risk_note": "高波动、高回撤，严格止损",
    "tags": ["高弹性", "强势主线", "资金动量", "短线"],
    # screener/ranker gates
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
    # Stage 0 quantitative: allow fast-moving names, but still keep a sane ceiling.
    "quantitative_max_ma20_deviation_pct": 45.0,
    "quantitative_max_prev_day_gain_pct": 15.0,
    "quantitative_ma20_deviation_penalty": 0.5,
    "require_min_buys": 0,
    "max_research_rounds": 12,
    "belief_list": [
        "关注市场短期最热的主线（如AI算力、半导体、存储、CPO/PCB、MLCC、小金属）中，具有明确催化剂和资金共识的强势标的。"
        "买强势、买放量、买强主线龙头；短线1-3日节奏为主，准备严格止损。",
        "偏好高动量、强量比、资金净流入靠前、处于板块主升阶段的标的。"
        "接受相对高位，寻找更强加速；一旦动能衰退就快速离场。",
        "喜欢事件催化、涨价、订单、超预期公告带来的短线博弈机会；优先资金合力和龙虎榜关注标的。",
        "主线板块中的弹性标的，敢于在资金共识最强时交易，但严格止损，不恋战。",
    ],
    "ranker_overrides": {
        "min_risk_reward_score": 45.0,
        "expected_return_floor_pct": 0.6,
        "max_prev_day_gain_pct": 14.0,
        "max_ma20_deviation_pct": 45.0,
        "min_relative_strength_20d_pct": 0.0,
        "min_flow_confirmation_score": 50.0,
        "min_regime_confirmation_score": 50.0,
        "strong_trend_penalty_bias": 6.0,
    },
}

STRATEGIES = {
    "swing": SWING,
    "momentum": MOMENTUM,
}


def get_strategy(strategy: str):
    """Return the strategy config dict. Defaults to momentum for unknown values."""
    if not strategy:
        return MOMENTUM
    lookup = str(strategy or "").lower()
    if lookup in {"momentum", "short", "短线", "短期", "短期收益", "动量"}:
        return MOMENTUM
    if lookup in {"swing", "trend", "中长线", "趋势"}:
        return SWING
    if lookup in {"default", "legacy"}:
        return SWING
    return MOMENTUM


def get_strategies():
    """Return all strategy configs, ordered for the UI."""
    return [STRATEGIES[name] for name in STRATEGY_NAMES]
