"""短线保守组合 rule for 1-5 日候选筛选.

定义:
  1. RSI 中低位（不高过 max_rsi）
  2. 距 52 周高点仍有缓冲（lt_distance_to_52w_high_pct <= max_dist52_pct，注意是负值）
  3. MA20 / MA50 不过度偏离（% 正负上限）

默认阈值：RSI<=65；距离52周高点<=-8%；MA20偏离<=12%；MA50偏离<=25%。
所有字段必须是 trigger 日已知；T3/T5 仅用于事后评估，不进 rule。
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

DEFAULT_RSI_MAX = 65.0
DEFAULT_DIST52_MAX = -8.0
DEFAULT_MA20_DEV_MAX = 12.0
DEFAULT_MA50_DEV_MAX = 25.0


def eval_conservative_rule(
    row: Dict[str, Any],
    rsi_max: Optional[float] = None,
    dist52_max: Optional[float] = None,
    ma20_dev_max: Optional[float] = None,
    ma50_dev_max: Optional[float] = None,
) -> Dict[str, Any]:
    rsi_max = DEFAULT_RSI_MAX if rsi_max is None else rsi_max
    dist52_max = DEFAULT_DIST52_MAX if dist52_max is None else dist52_max
    ma20_dev_max = DEFAULT_MA20_DEV_MAX if ma20_dev_max is None else ma20_dev_max
    ma50_dev_max = DEFAULT_MA50_DEV_MAX if ma50_dev_max is None else ma50_dev_max

    def num(key: str) -> Optional[float]:
        val = row.get(key)
        try:
            return float(val) if val is not None and val != "" else None
        except (TypeError, ValueError):
            return None

    rsi = num("rsi")
    dist52 = num("lt_distance_to_52w_high_pct")
    ma20 = num("ma20_deviation_pct")
    ma50 = num("lt_ma50_deviation_pct")
    reasons: List[str] = []
    pass_ = True

    if rsi is None:
        pass_, reasons = False, ["rsi_missing"]
    elif rsi > rsi_max:
        pass_ = False
        reasons.append(f"rsi>={rsi:.1f}")

    if dist52 is None:
        pass_ = False
        reasons.append("dist52_missing")
    elif dist52 > dist52_max:
        pass_ = False
        reasons.append(f"dist52>{dist52_max:.1f}")

    if ma20 is None:
        pass_ = False
        reasons.append("ma20_missing")
    elif ma20 > ma20_dev_max:
        pass_ = False
        reasons.append(f"ma20>={ma20:.1f}")

    if ma50 is None:
        pass_ = False
        reasons.append("ma50_missing")
    elif ma50 > ma50_dev_max:
        pass_ = False
        reasons.append(f"ma50>={ma50:.1f}")

    return {
        "pass": pass_,
        "reasons": list(dict.fromkeys(reasons)),
        "rsi": rsi,
        "ma20_deviation_pct": ma20,
        "lt_ma50_deviation_pct": ma50,
        "lt_distance_to_52w_high_pct": dist52,
        "thresholds": {
            "rsi_max": rsi_max,
            "dist52_max": dist52_max,
            "ma20_dev_max": ma20_dev_max,
            "ma50_dev_max": ma50_dev_max,
        },
    }
