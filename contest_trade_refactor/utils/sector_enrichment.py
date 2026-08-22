"""T+3~T+5 板块强度富化。

把板块快照与个股行业/概念映射，转成 quantitative screener / ranker 可读的字段：
    sector_1d_return, sector_3d_return, sector_rank, stock_vs_sector_strength

数据源可插拔：
- 优先从 utils.sector_flow_provider 拉行业/概念板块当日行情；
- 行业映射优先读取本地 cache/market_manager/industry_map.json；
- 如果缺映射或快照，返回空 dict，不影响既有评分。
"""
from __future__ import annotations

import glob
import hashlib
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


def _lookback_return_from_daily(
    daily: pd.DataFrame,
    trade_date: str,
    lookback: int,
) -> Optional[float]:
    """从板块日线 pct_chg 序列计算 N 日累计涨跌幅（金融口径：复合收益，百分数）。

    daily 需包含 date 与 pct_chg 列；pct_chg 为百分数。
    只用 <= trade_date 的已完成交易数据，避免未来函数。
    """
    if daily is None or daily.empty or not {"date", "pct_chg"}.issubset(daily.columns):
        return None
    try:
        dd = daily[daily["date"] <= pd.to_datetime(str(trade_date).replace("-", ""), format="%Y%m%d")]
    except Exception:
        return None
    dd = dd[["date", "pct_chg"]].copy()
    dd["pct_chg"] = pd.to_numeric(dd["pct_chg"], errors="coerce")
    dd = dd.dropna(subset=["pct_chg"]).sort_values("date").tail(lookback)
    if len(dd) < max(2, lookback):
        return None
    prod = 1.0
    for chg in dd["pct_chg"].tolist():
        prod *= (1.0 + float(chg) / 100.0)
    return round((prod - 1.0) * 100.0, 6)


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
        # 板块 N 日收益：优先复合日线，其次使用快照已有字段，避免仅 1d 导致 stock_vs 缺失。
        sector_3d = None
        if "板块3日涨跌幅" in row:
            sector_3d = round(float(row["板块3日涨跌幅"]), 3)
        if sector_3d is None and daily is not None and not daily.empty:
            sector_3d = _lookback_return_from_daily(daily, trade_date, 3)
        sector_5d = None
        if daily is not None and not daily.empty:
            sector_5d = _lookback_return_from_daily(daily, trade_date, 5)
        sector_10d = None
        if daily is not None and not daily.empty:
            sector_10d = _lookback_return_from_daily(daily, trade_date, 10)
        # stock_vs_sector_strength 由调用方填：stock_ret - sector_return，这里先给 s1 占位，避免 None
        sector_map[ts_code.upper()] = {
            "sector_1d_return": round(s1, 3),
            "sector_3d_return": sector_3d,
            "sector_5d_return": sector_5d,
            "sector_10d_return": sector_10d,
            "sector_rank": rank,
            "stock_vs_sector_strength": None,
            "sector_daily_returns": sector_daily_returns,
            "上涨家数": _float_or_none(row.get("上涨家数")) if "上涨家数" in row.index else None,
            "下跌家数": _float_or_none(row.get("下跌家数")) if "下跌家数" in row.index else None,
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

    # 计算 个股/板块 超额强度（原快照里 stock_vs_sector_strength 只是 None 占位）。
    stock_vs_sector_factor(factor)
    # Layer 4：金融口径 Ex-Self（板块剔除本股）
    enrich_factor_with_ex_self(factor, sector_snapshot)
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
    # pct_chg 是“百分数”（如 -0.5 表示 -0.50%），做金融回归前先转成小数。
    # 否则 residual = y - (alpha+beta*x) 的残差会被放大 100 倍，alpha/beta 口径也会错。
    x = m["pct_chg_sector"].to_numpy(dtype=float) / 100.0
    y = m["pct_chg_stock"].to_numpy(dtype=float) / 100.0
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
        "alpha": round(float(alpha) * 100.0, 6) if np.isfinite(alpha) else None,
        "beta": round(float(beta), 6) if np.isfinite(beta) else None,
        "residual": round(float(resid[-1]) * 100.0, 4) if np.isfinite(resid[-1]) else None,
        "r2": round(float(r2), 6) if np.isfinite(r2) else None,
        "n": int(len(m)),
    }


def _board_cons_cache_fd(industry_name: str, fallback_kwargs: Optional[dict] = None) -> list:
    """读取已有本地股票板块成分缓存（akshare stock_board_industry_cons_em）。

    与 akshare_cached 相同的 hash 规则：md5(str(func_kwargs).encode()).
    返回缓存 DataFrame 列表；不存在或读取失败返回空列表。
    """
    frames: list = []
    if not industry_name:
        return frames
    kwargs = dict(fallback_kwargs or {})
    kwargs["symbol"] = industry_name
    h = hashlib.md5(str(kwargs).encode()).hexdigest()
    dirp = Path(__file__).parent / "akshare_cache" / "stock_board_industry_cons_em"
    hits = sorted(glob.glob(str(dirp / f"{h}*.pkl"))) if dirp else []
    for f in hits[:5]:
        try:
            df = pd.read_pickle(f)
            if df is not None and not df.empty:
                frames.append(df)
        except Exception:
            continue
    return frames


def _float_or_none(value) -> Optional[float]:
    try:
        f = float(value)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def compute_ex_self_sector_metrics(
    sector_snapshot: Dict[str, Dict[str, float]],
    stock_code: str,
    industry_name: str,
    stock_daily_returns: Optional[list] = None,
    trade_date: Optional[str] = None,
) -> Dict[str, Optional[float]]:
    """金融口径的板块 Ex-Self 指标。

    彻底剔除“个股推高板块”的污染：
      - sector_return_ex_self_1d: 板块1D - 个股1D（近似剔除本股对板块贡献）
      - sector_return_ex_self_5d: 板块5D - 个股5D（板块日线可用时用复合收益）
      - sector_breadth_ex_self: (板块内上涨家数-本股是否上涨) / (板块总家数-1)
      - sector_ex_self_status: ok / approximate / missing
    """
    out: Dict[str, Optional[float]] = {
        "sector_return_ex_self_1d": None,
        "sector_return_ex_self_5d": None,
        "sector_breadth_ex_self": None,
        "sector_breadth_total": None,
        "sector_ex_self_status": "missing",
    }
    code = str(stock_code or "").strip().upper()
    if not code or not industry_name:
        return out
    info = sector_snapshot.get(code) or sector_snapshot.get(code.split(".")[0])
    if info is None:
        info = sector_snapshot.get(str(industry_name).strip().upper())
    if info is None:
        return out

    sector_1d = _float_or_none(info.get("sector_1d_return"))
    stock_1d = None
    if stock_daily_returns and isinstance(stock_daily_returns, list) and stock_daily_returns:
        stock_1d = _float_or_none(stock_daily_returns[-1].get("pct_chg") if isinstance(stock_daily_returns[-1], dict) else None)
    if sector_1d is not None and stock_1d is not None:
        out["sector_return_ex_self_1d"] = round(sector_1d - stock_1d, 3)
        out["sector_ex_self_status"] = "ok_1d"

    # 5D ex-self: 板块复合收益 - 个股 5D（个股 5D 从 stock_daily_returns 复利，或调用方在 factor.ret_5d_pct 传入）
    sector_5d = _float_or_none(info.get("sector_5d_return"))
    stock_5d = None
    if stock_daily_returns and isinstance(stock_daily_returns, list):
        pct_seq = []
        for item in stock_daily_returns:
            try:
                chg = float(item.get("pct_chg")) if isinstance(item, dict) else float(item)
            except Exception:
                continue
            if chg == chg:
                pct_seq.append(chg)
        recent = pct_seq[-5:]
        if len(recent) >= 5:
            prod = 1.0
            for chg in recent:
                prod *= (1.0 + chg / 100.0)
            stock_5d = (prod - 1.0) * 100.0
    if sector_5d is not None and stock_5d is not None:
        out["sector_return_ex_self_5d"] = round(sector_5d - stock_5d, 3)
        out["sector_ex_self_status"] = out.get("sector_ex_self_status") or "ok_5d"

    # Breadth Ex-Self
    up_count = _float_or_none(info.get("上涨家数"))
    down_count = _float_or_none(info.get("下跌家数"))
    board_count = None
    if up_count is not None and down_count is not None:
        up_count = int(up_count); down_count = int(down_count)
        board_count = up_count + down_count
    else:
        frames = _board_cons_cache_fd(industry_name)
        if frames:
            last = frames[-1]
            code_col = next((c for c in ("代码", "股票代码", "ts_code") if c in last.columns), None)
            if code_col is not None:
                up = 0
                for _, row in last.iterrows():
                    chg = _float_or_none(row.get("涨跌幅"))
                    if chg is not None and chg > 0:
                        up += 1
                board_count = len(last)
                up_count = up
    if board_count and board_count > 1:
        stock_up = 0
        if stock_daily_returns and isinstance(stock_daily_returns, list) and stock_daily_returns:
            try:
                stock_up = 1 if _float_or_none(stock_daily_returns[-1].get("pct_chg")) or 0 > 0 else 0
            except Exception:
                stock_up = 0
        up_ex = int(up_count or 0) - stock_up
        if up_ex < 0:
            up_ex = 0
        out["sector_breadth_ex_self"] = round(up_ex / (board_count - 1), 4)
        out["sector_breadth_total"] = round((up_count or 0) / board_count, 4)
        out["sector_ex_self_status"] = out.get("sector_ex_self_status") or "ok_breadth"
    return out


def enrich_factor_with_ex_self(factor: dict, sector_snapshot: Dict[str, Dict[str, float]]) -> dict:
    """在 factor 上补 Ex-Self 板块强度，并把旧近似字段留在原地（避免破坏既有调用）。"""
    if not factor:
        return factor
    code = str(factor.get("symbol_code") or "").strip().upper()
    industry = str(factor.get("industry_name") or factor.get("sector_name") or "").strip()
    metrics = compute_ex_self_sector_metrics(
        sector_snapshot,
        code,
        industry,
        stock_daily_returns=factor.get("stock_daily_returns"),
        trade_date=factor.get("report_date"),
    )
    only_not_none = {k: v for k, v in metrics.items() if v is not None}
    if only_not_none:
        factor.update(only_not_none)
    return factor


def stock_vs_sector_factor(factor: dict) -> dict:
    """在已富化板块的 factor 上补算 stock_vs_sector_strength 系列字段。

    板块快照的 stock_vs_sector_strength 字段是 None 占位，因为构建快照时拿不到个股收益。
    个股的 ret_{lookback}d_pct / change_pct 和板块的 sector_{lookback}d_return 都在 factor 上可用时，
    这里直接相减得到“超额/跑赢板块”的强度。
    若 sector_{n}d_return 缺失但 sector_daily_returns 存在，先由日线复合收益补齐，避免 stock_vs 常为 None。
    """
    if not factor:
        return factor
    sector_daily = factor.get("sector_daily_returns")
    for lookback in (1, 3, 5, 10):
        sector_col = f"sector_{lookback}d_return"
        if factor.get(sector_col) is None and isinstance(sector_daily, list) and sector_daily:
            cum = _cum_return_from_sector_daily(sector_daily, lookback)
            if cum is not None:
                factor[sector_col] = round(cum, 3)
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

    # 默认 stock_vs_sector_strength 用 5 日版本，和原语义一致；缺失时依次退到 3d / 1d。
    for lookback in (5, 3, 10, 1):
        key = f"stock_vs_sector_{lookback}d"
        if factor.get(key) is not None:
            factor["stock_vs_sector_strength"] = factor[key]
            break
    return factor


def _cum_return_from_sector_daily(sector_daily: list, lookback: int) -> Optional[float]:
    """按 sector_daily_returns 最近 N 日 pct_chg 复合累计收益（百分数）。"""
    if not sector_daily or lookback <= 0:
        return None
    rows = []
    for item in sector_daily:
        try:
            chg = float(item.get("pct_chg"))
        except (TypeError, ValueError, AttributeError):
            continue
        if chg == chg:
            rows.append(chg)
    recent = rows[-lookback:]
    if len(recent) < max(2, lookback):
        return None
    prod = 1.0
    for chg in recent:
        prod *= (1.0 + chg / 100.0)
    return round((prod - 1.0) * 100.0, 6)


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
    enrich_factor_with_ex_self(factor, snapshot_by_industry)
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
