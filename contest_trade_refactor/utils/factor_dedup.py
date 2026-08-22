"""
Layer 3 因子族内去重 / 金融诊断工具。

金融口径（不偷工减料）：
- 家族拆分为 Trend / Breakout / Momentum / Relative Strength / Volume 等因子族。
- 族内使用 Spearman（Rank）相关矩阵、Rank IC 报表（外部回测）、VIF 识别高冗余。
- 不是“简单相加”，也不是直接上 PCA（PCA 只解释方差、不解释未来收益）。

本模块提供：
- factor_to_panel(factors, fields)：抽取横截面数值面板。
- correlation_matrix(factors_or_frame, fields, method)：Spearman/Pearson 相关矩阵。
- vif_table(factors_or_frame)：VIF = 1/(1-R^2)，金融统计口径。
- family_dedup_report：按预定义因子族输出相关对/VIF/代表性因子建议。
- pick_representatives(report, family)：在每个因子族内部去掉高度冗余指标。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

# 每个因子族内的候选指标（足以覆盖“5D Return 与 10D Return 高度相关”这类场景）。
FAMILY_GROUPS: Dict[str, List[str]] = {
    "trend": [
        "ma20_deviation_pct",
        "ma20_slope_pct",
        "ma60_5d_slope_pct",
        "weekly_trend_score",
        "weinstein_stage_score",
    ],
    "breakout": [
        "breakout_20d",
        "breakout_60d",
        "close_vs_20d_high_pct",
        "close_vs_60d_high_pct",
    ],
    "momentum": [
        "ret_1d_pct",
        "ret_3d_pct",
        "ret_5d_pct",
        "ret_10d_pct",
        "ret_20d_pct",
    ],
    "relative_strength": [
        "relative_strength_20d_pct",
        "relative_strength_60d_pct",
        "residual_rs_vs_index_20d",
        "residual_rs_vs_sector_20d",
        "relative_strength_score",
    ],
    "volume": [
        "volume_ratio",
        "amount_ratio",
        "volume_ma5_ma20_ratio",
    ],
    "volatility": [
        "atr_pct",
        "daily_volatility_20d_pct",
    ],
}


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        f = float(value)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _panel_factors(factors: Iterable[Dict[str, Any]], fields: Optional[Iterable[str]] = None) -> pd.DataFrame:
    if isinstance(factors, pd.DataFrame):
        return factors
    field_list = [f for f in (fields or []) if f]
    seen: List[str] = []
    if not field_list:
        for f in factors:
            if not isinstance(f, dict):
                continue
            for key in f.keys():
                if key not in seen:
                    seen.append(key)
        field_list = seen
    rows = []
    for f in factors:
        if not isinstance(f, dict):
            continue
        rows.append({col: _safe_float(f.get(col)) for col in field_list})
    return pd.DataFrame(rows)


def factor_to_panel(
    factors: Iterable[Dict[str, Any]],
    fields: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """抽取一组 factor dict 的数值横截面（字段名 -> 数值）。"""
    return _panel_factors(factors, fields)


def _corr(series_a: pd.Series, series_b: pd.Series, method: str = "spearman") -> Optional[float]:
    df = pd.DataFrame({"a": pd.to_numeric(series_a, errors="coerce"),
                       "b": pd.to_numeric(series_b, errors="coerce")}).dropna()
    if len(df) < 10 or df["a"].nunique() <= 1 or df["b"].nunique() <= 1:
        return None
    try:
        val = df["a"].corr(df["b"], method=method)
        return round(float(val), 6) if val == val else None
    except Exception:
        return None


def correlation_matrix(
    factors: Iterable[Dict[str, Any]],
    fields: Optional[Iterable[str]] = None,
    method: str = "spearman",
) -> pd.DataFrame:
    """字段间相关矩阵（默认 Spearman，金融因子常用秩相关）。"""
    frame = _panel_factors(factors, fields)
    cols = list(frame.columns)
    out = pd.DataFrame(index=cols, columns=cols, dtype=float)
    for a in cols:
        for b in cols:
            if a == b:
                out.loc[a, b] = 1.0
            else:
                out.loc[a, b] = _corr(frame[a], frame[b], method)
    return out


def vif_table(
    factors: Iterable[Dict[str, Any]],
    fields: Optional[Iterable[str]] = None,
) -> Dict[str, Optional[float]]:
    """VIF（方差膨胀因子）表。

    VIF_i = 1 / (1 - R^2_i)，R^2 来自以 i 为因变量、其余因子为自变量的 OLS。
    样本不足 / 无自由度 / R^2 ≈ 1 时返回 None（避免除以 0 或过度膨胀）。
    """
    frame = _panel_factors(factors, fields)
    return _vif_table_from_frame(frame)


def _vif_table_from_frame(frame: pd.DataFrame) -> Dict[str, Optional[float]]:
    cols = list(frame.columns)
    if len(cols) < 2 or len(frame) < 10:
        return {col: None for col in cols}
    out: Dict[str, Optional[float]] = {}
    for col in cols:
        others = [c for c in cols if c != col]
        sub = frame[cols].dropna()
        if len(sub) < 10 or len(sub) <= len(others) + 1:
            out[col] = None
            continue
        try:
            X = sub[others].to_numpy(dtype=float)
            y = sub[col].to_numpy(dtype=float)
            X1 = np.column_stack([np.ones(len(X)), X])
            beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
            resid = y - X1 @ beta
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r2 = 1.0 - np.sum(resid ** 2) / ss_tot if ss_tot > 0 else np.nan
            if not np.isfinite(r2) or r2 >= 1.0 - 1e-9:
                out[col] = None
            else:
                out[col] = round(float(1.0 / (1.0 - r2)), 4)
        except Exception:
            out[col] = None
    return out


def family_dedup_report(
    factors: Iterable[Dict[str, Any]],
    *,
    corr_method: str = "spearman",
    corr_threshold: float = 0.85,
    families: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """Layer 3 宏观诊断：
       - 因子族透视
       - 高相关对
       - VIF 表
       - 每族代表性指标建议

    结果会写入 raw factor 的 `_factor_family_dedup`，便于后续 Quality 只使用代表性因子。
    若样本不足返回 insufficient，不影响既有评分（缺失放行）。
    """
    fam = dict(families or FAMILY_GROUPS)
    frame = _panel_factors(factors)
    if frame.empty or len(frame) < 10:
        return {
            "status": "insufficient",
            "family_count": 0,
            "fields": [],
            "correlation": {"method": corr_method, "matrix": {}, "high_corr_pairs": []},
            "vif": {},
            "representatives": {},
            "note": "样本不足，无法计算可靠相关矩阵/VIF",
        }

    corr = correlation_matrix(frame, method=corr_method)
    vif = _vif_table_from_frame(frame)

    high_corr_pairs = []
    fields = list(frame.columns)
    for a in fields:
        for b in fields:
            if a >= b:
                continue
            val = corr.loc[a, b]
            if val is not None and abs(val) >= corr_threshold:
                high_corr_pairs.append({"field_a": a, "field_b": b, "correlation": round(float(val), 4)})

    representatives: Dict[str, List[str]] = {}
    for family_name, member_fields in fam.items():
        picks: List[str] = []
        for col in member_fields:
            if col not in fields:
                continue
            conflict = any(
                corr.loc[col, p] is not None and abs(corr.loc[col, p]) >= corr_threshold
                for p in picks if corr.loc[col, p] is not None
            )
            if not conflict:
                picks.append(col)
            elif picks:
                # 被代表因子包含时保留低 VIF 项
                if (vif.get(col) or 99.0) < (vif.get(picks[0]) or 99.0):
                    picks[0] = col
        representatives[family_name] = picks

    return {
        "status": "ok",
        "family_count": len(fam),
        "fields": fields,
        "correlation": {
            "method": corr_method,
            "matrix": corr.astype(object).where(corr.notna(), None).to_dict(orient="index"),
            "high_corr_pairs": high_corr_pairs,
        },
        "vif": vif,
        "representatives": representatives,
        "note": "族内高相关/高VIF因子仅在报告层去重；评分族内取代表性因子，不简单叠加同源指标。",
    }


def pick_representatives(report: Dict[str, Any], family: str = "relative_strength") -> List[str]:
    """从 family_dedup_report 的 representatives 中取某个族代表性字段。"""
    reps = (report or {}).get("representatives") or {}
    return list(reps.get(family, []) or [])
