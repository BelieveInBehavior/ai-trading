"""T+3~T+5 板块强度富化。

把板块快照与个股行业/概念映射，转成 quantitative screener / ranker 可读的字段：
    sector_1d_return, sector_3d_return, sector_rank, stock_vs_sector_strength

数据源可插拔：
- 优先从 utils.sector_flow_provider 拉行业/概念板块当日行情；
- 行业映射优先读取本地 cache/market_manager/industry_map.json；
- 如果缺映射或快照，返回空 dict，不影响既有评分。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
from loguru import logger

CACHE_DIR = Path(__file__).parent / "cache" / "market_manager"
INDUSTRY_MAP_CACHE = CACHE_DIR / "industry_map.json"


def load_industry_map(verbose: bool = False) -> Dict[str, str]:
    """ts_code -> industry name. 优先本地缓存，其次尝试 stock_basic_cache 里的 industry 列。"""
    if INDUSTRY_MAP_CACHE.exists():
        try:
            data = json.loads(INDUSTRY_MAP_CACHE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return data
        except Exception as exc:
            logger.warning("读取 industry_map 失败: {}", exc)

    basic = CACHE_DIR / "stock_basic_cache.json"
    if basic.exists():
        try:
            rows = json.loads(basic.read_text(encoding="utf-8"))
            mapping = {}
            for row in rows:
                code = str(row.get("ts_code") or "").strip().upper()
                industry = str(row.get("industry") or "").strip()
                if code and industry:
                    mapping[code] = industry
            if mapping:
                return mapping
        except Exception:
            pass

    return {}


def save_industry_map(mapping: Dict[str, str]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    INDUSTRY_MAP_CACHE.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_sector_snapshot(
    trade_date: Optional[str] = None,
    *,
    require_flow: bool = False,
    industry_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, float]]:
    """返回 {ts_code: {'sector_1d_return','sector_3d_return','sector_rank', ...}}.

    依赖 utils.sector_flow_provider.get_industry_board_data 提供的"行业"板块数据。
    若拉取失败或没有 industry_map，返回空 dict，由上层保持中性分。
    """
    sector_map: Dict[str, Dict[str, float]] = {}

    try:
        from utils.sector_flow_provider import get_industry_board_data
    except Exception as exc:
        logger.warning("sector_flow_provider import failed: {}", exc)
        return sector_map

    try:
        board_df = get_industry_board_data(trade_date=trade_date, require_flow=require_flow)
    except Exception as exc:
        logger.warning("获取行业板块快照失败: {}", exc)
        return sector_map

    if board_df is None or board_df.empty:
        return sector_map

    industry_map = industry_map if industry_map is not None else _load_industry_map()
    board_df = board_df.copy()

    name_col = "板块名称" if "板块名称" in board_df.columns else "名称"
    if name_col not in board_df.columns:
        logger.warning("行业板块数据缺少板块名称列: {}", list(board_df.columns))
        return sector_map

    # rank by 涨跌幅, 1=最强
    if "涨跌幅" in board_df.columns:
        board_df["涨跌幅"] = pd.to_numeric(board_df["涨跌幅"], errors="coerce").fillna(0.0)
        board_df["sector_rank"] = board_df["涨跌幅"].rank(ascending=False, method="min").astype(int)
    else:
        board_df["sector_rank"] = board_df.index + 1

    rank_max = max(1, int(board_df["sector_rank"].max())) if "sector_rank" in board_df.columns else 1
    industry_by_name = {str(k).strip(): v for k, v in industry_map.items()}  # ts_code -> industry
    code_to_industry = industry_map

    # 尝试拉板块日线（失败降级，不影响既有快照）
    board_names = sorted({str(v).strip() for v in industry_map.values() if v and str(v).strip()})
    daily_by_board = {}
    if board_names and trade_date:
        try:
            start, end = _default_history_range(trade_date)
            from utils.sector_flow_provider import get_industry_daily_history_map
            daily_by_board = get_industry_daily_history_map(board_names, start, end)
        except Exception as exc:
            logger.warning("板块日线拉取失败，退化到区间收益: {}", exc)

    for ts_code, industry in code_to_industry.items():
        if not industry:
            continue
        row = board_df[board_df[name_col].astype(str).str.strip() == str(industry).strip()]
        if row.empty:
            # 概念/板块名称可能有 alias，不强制
            continue
        row = row.iloc[0]
        s1 = float(row.get("涨跌幅", 0.0))
        rank = int(row.get("sector_rank", rank_max))
        daily = daily_by_board.get(str(industry).strip().upper())
        sector_daily_returns = []
        if daily is not None and not daily.empty and {"date", "pct_chg"}.issubset(daily.columns):
            dd = daily[daily["date"] <= pd.to_datetime(str(trade_date).replace("-", ""), format="%Y%m%d")]
            sector_daily_returns = [
                {"date": str(r.date.date()), "pct_chg": round(float(r.pct_chg), 4)}
                for r in dd.tail(30).itertuples(index=False)
                if pd.notna(r.pct_chg)
            ]
        # stock_vs_sector_strength 由调用方填：stock_ret_3d - sector_3d，这里先给 s1 占位，避免 None
        sector_map[ts_code.upper()] = {
            "sector_1d_return": round(s1, 3),
            "sector_3d_return": None if "板块3日涨跌幅" not in row else round(float(row["板块3日涨跌幅"]), 3),
            "sector_rank": rank,
            "stock_vs_sector_strength": None,
            "sector_daily_returns": sector_daily_returns,
        }
    if sector_map:
        logger.info("板块富化完成，映射 {} 只股票: {}", len(sector_map), list(sector_map.keys())[:5])
    return sector_map


def enrich_factor_with_sector(factor: dict, sector_snapshot: Dict[str, Dict[str, float]]) -> dict:
    if not factor:
        return factor
    code = str(factor.get("symbol_code") or "").strip().upper()
    if not code or not sector_snapshot:
        return factor
    info = sector_snapshot.get(code)
    if not info and "." in code:
        info = sector_snapshot.get(code.split(".")[0])
    if not info:
        raw_code = code.split(".")[0]
        for key in list(sector_snapshot.keys()):
            if str(key).split(".")[0].upper() == raw_code:
                info = sector_snapshot[key]
                break
    if not info:
        return factor
    factor = dict(factor)
    for k, v in info.items():
        if v is not None:
            factor[k] = v

    # 板块 OLS 残差（金融口径）：股票日收益 vs 板块日收益
    stock_daily = factor.get("stock_daily_returns")
    sector_daily = factor.get("sector_daily_returns")
    if isinstance(stock_daily, list) and isinstance(sector_daily, list):
        ols20 = _compute_sector_residual(stock_daily, sector_daily, 20)
        if ols20.get("residual") is not None:
            factor["residual_rs_vs_sector_20d"] = ols20["residual"]
            factor["beta_20d_vs_sector"] = ols20["beta"]
            factor["alpha_20d_vs_sector"] = ols20["alpha"]
            factor["r2_20d_vs_sector"] = ols20["r2"]
        ols60 = _compute_sector_residual(stock_daily, sector_daily, 60)
        if ols60.get("residual") is not None:
            factor["residual_rs_vs_sector_60d"] = ols60["residual"]
            factor["beta_60d_vs_sector"] = ols60["beta"]
            factor["alpha_60d_vs_sector"] = ols60["alpha"]
            factor["r2_60d_vs_sector"] = ols60["r2"]

    # 计算 个股 vs 板块 超额强度（原快照里 stock_vs_sector_strength 只是 None 占位）。
    stock_vs_sector_factor(factor)
    return factor


def _compute_sector_residual(
    stock_daily: list,
    sector_daily: list,
    window: int = 20,
) -> dict:
    """对个股日收益 / 板块日收益做金融 OLS 残差。

    输入都是 [{"date": "YYYY-MM-DD", "pct_chg": float}, ...]。
    返回 {alpha, beta, residual, r2, n}。
    """
    if not stock_daily or not sector_daily:
        return {"alpha": None, "beta": None, "residual": None, "r2": None, "n": 0}

    def _to_df(items):
        df = pd.DataFrame(items)
        if df.empty or not {"date", "pct_chg"} <= set(df.columns):
            return pd.DataFrame()
        df["date"] = pd.to_datetime(df["date"])
        df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
        return df.dropna(subset=["date", "pct_chg"])

    sdf = _to_df(stock_daily)
    bdf = _to_df(sector_daily)
    if sdf.empty or bdf.empty:
        return {"alpha": None, "beta": None, "residual": None, "r2": None, "n": 0}
    m = sdf.merge(bdf, on="date", suffixes=("_stock", "_sector"))
    m = m.tail(window)
    if len(m) < max(10, int(window * 0.5)):
        return {"alpha": None, "beta": None, "residual": None, "r2": None, "n": len(m)}
    x = m["pct_chg_sector"].to_numpy(dtype=float)
    y = m["pct_chg_stock"].to_numpy(dtype=float)
    import numpy as np
    if np.std(x) == 0 or np.std(y) == 0:
        return {"alpha": None, "beta": None, "residual": None, "r2": None, "n": len(m)}
    x_mean = np.mean(x); y_mean = np.mean(y)
    var_x = np.sum((x - x_mean) ** 2) / (len(x) - 1)
    cov = np.sum((x - x_mean) * (y - y_mean)) / (len(x) - 1)
    beta = cov / var_x
    alpha = y_mean - beta * x_mean
    pred = alpha + beta * x
    resid = y - pred
    ss_tot = np.sum((y - y_mean) ** 2)
    ss_res = np.sum(resid ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot != 0 else np.nan
    return {
        "alpha": round(float(alpha), 6) if np.isfinite(alpha) else None,
        "beta": round(float(beta), 6) if np.isfinite(beta) else None,
        "residual": round(float(resid[-1] * 100.0), 4) if np.isfinite(resid[-1]) else None,
        "r2": round(float(r2), 6) if np.isfinite(r2) else None,
        "n": int(len(m)),
    }


def stock_vs_sector_factor(factor: dict) -> dict:
    """在已富化板块的 factor 上补算 stock_vs_sector_strength 系列字段。

    板块快照的 stock_vs_sector_strength 字段是 None 占位，因为构建快照时拿不到个股收益。
    个股的 ret_{lookback}d_pct / change_pct 和板块的 sector_{lookback}d_return 都在 factor 上可用时，
    这里直接相减得到“超额/跑赢板块”的强度。
    """
    if not factor:
        return factor
    for lookback in (1, 3, 5, 10):
        stock_col = "change_pct" if lookback == 1 else f"ret_{lookback}d_pct"
        sector_col = f"sector_{lookback}d_return"
        stock_val = factor.get(stock_col)
        sector_val = factor.get(sector_col)
        if stock_val is None or sector_val is None:
            continue
        try:
            stock_val = float(stock_val)
            sector_val = float(sector_val)
        except (TypeError, ValueError):
            continue
        factor[f"stock_vs_sector_{lookback}d"] = round(stock_val - sector_val, 3)

    # 默认 stock_vs_sector_strength 用 5 日版本，和原语义一致。
    f5 = factor.get("stock_vs_sector_5d")
    if f5 is not None:
        factor["stock_vs_sector_strength"] = f5
    elif factor.get("stock_vs_sector_1d") is not None:
        factor["stock_vs_sector_strength"] = factor["stock_vs_sector_1d"]
    return factor



def build_sector_snapshot_from_factor_store(
    factor_dir: str = "agents_workspace/factor_store/sector_fund_flow",
    trade_date: str | None = None,
) -> Dict[str, Dict[str, float]]:
    """从 agents_workspace/factor_store/sector_fund_flow/<date>.csv 构建行业板块快照。

    返回 {industry_name.upper(): {sector_1d_return, sector_3d_return, sector_5d_return,
          sector_10d_return, sector_rank, sector_lookback_days, source_trade_date, ...}}
    数据来自结构化板块资金流文件，metadata_json.change_pct 即板块当日涨跌幅。
    若指定 trade_date，只使用 <= trade_date 的历史文件，避免未来数据。
    """
    import glob as _glob
    import json as _json

    snapshot: Dict[str, Dict[str, float]] = {}
    # name -> [(date_compact, chg), ...] for available dates <= trade_date
    history: Dict[str, list] = {}

    if trade_date:
        files = sorted(_glob.glob(str(Path(factor_dir) / "*.csv")))
        files = [f for f in files if _date_compact(f) <= str(trade_date).replace("-", "")]
        # keep latest up to 20 files to limit memory/time
        files = files[-20:]
    else:
        files = sorted(_glob.glob(str(Path(factor_dir) / "*.csv")))

    for file in files:
        try:
            df = pd.read_csv(file)
        except Exception as exc:
            logger.warning("读取板块资金流 csv 失败 {}: {}", file, exc)
            continue
        if df.empty or "metadata_json" not in df.columns:
            continue
        file_date = str(Path(file).stem).strip()
        for _, row in df.iterrows():
            name = str(row.get("symbol_code") or row.get("symbol_name") or "").strip()
            if not name:
                continue
            try:
                meta = _json.loads(row.get("metadata_json") or "{}")
            except Exception:
                meta = {}
            try:
                chg = float(meta.get("change_pct") or 0.0)
            except (TypeError, ValueError):
                chg = 0.0
            key = name.strip().upper()
            if not key:
                continue
            history.setdefault(key, []).append((file_date, chg))
        if trade_date and not history:
            continue

    if not history:
        logger.warning("板块资金流快照为空: {}", files)
        return snapshot

    def _cum(rows, n):
        """cumulative pct over at most last n available daily change_pct rows."""
        recent = rows[-n:]
        prod = 1.0
        for _d, chg in recent:
            prod *= (1.0 + chg / 100.0)
        return (prod - 1.0) * 100.0

    # rank by 当日涨幅，1=最强
    unique_1d: Dict[str, float] = {}
    for key, rows in history.items():
        unique_1d[key] = rows[-1][1] if rows else 0.0
    ranked = sorted(unique_1d.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    rank_map = {k: i + 1 for i, (k, _) in enumerate(ranked)}
    for key, rows in history.items():
        rows_sorted = sorted(rows, key=lambda x: x[0])
        last_date = rows_sorted[-1][0]
        snapshot[key] = {
            "sector_1d_return": round(rows_sorted[-1][1], 3),
            "sector_3d_return": round(_cum(rows_sorted, 3), 3),
            "sector_5d_return": round(_cum(rows_sorted, 5), 3),
            "sector_10d_return": round(_cum(rows_sorted, 10), 3),
            "sector_rank": rank_map[key],
            "stock_vs_sector_strength": None,
            "sector_lookback_days": len(rows_sorted),
            "source_trade_date": last_date,
        }
    logger.info("从 factor_store 构建板块快照: {} 个行业, trade_date={}", len(snapshot), trade_date)
    return snapshot


def _default_history_range(trade_date: str) -> tuple[str, str]:
    """默认拉取板块日线区间：最近 ~160 个自然日（更宽松，实际数据按交易日截断）。"""
    end = str(trade_date).replace("-", "")
    try:
        from datetime import datetime, timedelta
        dt = datetime.strptime(end, "%Y%m%d")
    except Exception:
        return "20250101", end
    start = (dt - timedelta(days=240)).strftime("%Y%m%d")
    return start, end


def _date_compact(path) -> str:
    import re as _re
    m = _re.findall(r"(20\d{6})", str(path))
    if m:
        return m[-1]
    return str(Path(path).stem).strip()


def save_sector_snapshot(snapshot: Dict[str, Dict[str, float]], path: str | None = None) -> Path:
    if path is None:
        path = CACHE_DIR / "sector_board_snapshot.json"
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def enrich_factor_with_sector_by_name(
    factor: dict,
    snapshot_by_industry: Dict[str, Dict[str, float]],
    stock_industry: str | None,
) -> dict:
    if not factor or not snapshot_by_industry or not stock_industry:
        return factor
    info = snapshot_by_industry.get(stock_industry.strip().upper())
    if not info:
        return factor
    factor = dict(factor)
    for k, v in info.items():
        if v is not None:
            factor[k] = v

    # 计算 个股 vs 板块 超额强度（原快照里 stock_vs_sector_strength 只是 None 占位）。
    # 板块快照只有板块数据，个股收益在 factor 里，所以在这里补算。
    stock_vs_sector_factor(factor)
    return factor



def build_code_sector_snapshot(
    industry_map: dict,
    snapshot_by_industry: dict | None = None,
    *,
    factor_dir: str = "agents_workspace/factor_store/sector_fund_flow",
    trade_date: str | None = None,
) -> dict:
    """将 industry_map + 行业板块快照转成 ts_code → sector 字段。"""
    if snapshot_by_industry is None:
        snapshot_by_industry = build_sector_snapshot_from_factor_store(
            factor_dir=factor_dir, trade_date=trade_date,
        )
    code_snap = {}
    for ts_code, industry in industry_map.items():
        info = snapshot_by_industry.get(str(industry).strip().upper())
        if not info:
            continue
        normalized = str(ts_code).strip().upper()
        code_snap[normalized] = info
        # Also index by the bare 6-digit code so technical factors with
        # symbol_code="603259" can still resolve to "603259.SH".
        if "." in normalized:
            code_snap[normalized.split(".")[0]] = info
    return code_snap


if __name__ == "__main__":
    mapping = load_industry_map()
    print("industry_map size:", len(mapping), "examples:", list(mapping.items())[:3])
