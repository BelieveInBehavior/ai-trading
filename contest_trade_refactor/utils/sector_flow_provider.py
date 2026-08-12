"""
Unified sector/concept fund-flow fallbacks.

The downstream agents expect a Chinese field set regardless of provider:
板块名称, 涨跌幅, 主力净流入, 上涨家数, 下跌家数, 数据源.
"""
from __future__ import annotations

from typing import Callable, Optional

import akshare as ak
import pandas as pd
from loguru import logger

from utils.akshare_utils import akshare_cached


TUSHARE_MONEYFLOW_FIELDS = (
    "trade_date,ts_code,name,pct_change,close,net_amount,net_amount_rate,rank,"
    "buy_elg_amount,buy_lg_amount,buy_md_amount,buy_sm_amount,buy_sm_amount_stock"
)


def _parse_amount(value) -> float:
    if pd.isna(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).replace(",", "").strip()
    if not text or text == "--":
        return 0.0

    sign = -1 if text.startswith("-") else 1
    text = text.lstrip("+-")

    multiplier = 1.0
    if text.endswith("亿"):
        multiplier = 1e8
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 1e4
        text = text[:-1]

    number = pd.to_numeric(text, errors="coerce")
    if pd.isna(number):
        return 0.0
    return sign * float(number) * multiplier


def _money_series_to_yuan(series: pd.Series, source_unit: str) -> pd.Series:
    values = series.apply(_parse_amount)
    if source_unit == "yi":
        return values * 1e8
    return values


def _normalize_sector_frame(
    df: pd.DataFrame,
    *,
    source_name: str,
    board_type: str,
    money_unit: str = "yuan",
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    result = df.copy()
    rename_map = {
        "行业": "板块名称",
        "name": "板块名称",
        "行业-涨跌幅": "涨跌幅",
        "pct_change": "涨跌幅",
        "net_amount": "主力净流入",
        "净额": "主力净流入",
        "流入资金": "资金流入",
        "流出资金": "资金流出",
        "公司家数": "成分股数量",
        "领涨股": "领涨股票",
        "领涨股-涨跌幅": "领涨股票-涨跌幅",
        "rank": "排名",
        "ts_code": "板块代码",
        "buy_sm_amount_stock": "代表股票",
    }
    result = result.rename(columns={k: v for k, v in rename_map.items() if k in result.columns})

    if "板块名称" not in result.columns and "名称" in result.columns:
        result["板块名称"] = result["名称"]

    if "板块名称" not in result.columns:
        return pd.DataFrame()

    result["板块名称"] = result["板块名称"].fillna("").astype(str)
    result = result[result["板块名称"].str.strip() != ""].copy()
    if result.empty:
        return result

    if "涨跌幅" in result.columns:
        result["涨跌幅"] = pd.to_numeric(result["涨跌幅"], errors="coerce").fillna(0.0)
    else:
        result["涨跌幅"] = 0.0

    for col in ["主力净流入", "资金流入", "资金流出"]:
        if col in result.columns:
            result[col] = _money_series_to_yuan(result[col], source_unit=money_unit)

    for col in ["上涨家数", "下跌家数", "成分股数量"]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce").fillna(0).astype(int)

    result["数据源"] = source_name
    result["板块类型"] = board_type
    return result.reset_index(drop=True)


def _has_flow(df: pd.DataFrame) -> bool:
    return any(col in df.columns for col in ["主力净流入", "今日主力净流入", "主力净流入-净额", "净流入"])


def _fetch_akshare_board_name(func_name: str, board_type: str) -> pd.DataFrame:
    df = akshare_cached.run(func_name=func_name, func_kwargs={}, verbose=False)
    return _normalize_sector_frame(
        df,
        source_name=f"akshare:{func_name}",
        board_type=board_type,
        money_unit="yuan",
    )


def _fetch_tushare_moneyflow(trade_date: str, board_type: str) -> pd.DataFrame:
    from utils.tushare_utils import tushare_cached

    df = tushare_cached.run(
        "moneyflow_ind_dc",
        func_kwargs={
            "trade_date": trade_date,
            "fields": TUSHARE_MONEYFLOW_FIELDS,
        },
        verbose=False,
    )
    return _normalize_sector_frame(
        df,
        source_name="tushare:moneyflow_ind_dc",
        board_type=board_type,
        money_unit="yuan",
    )


def _fetch_akshare_fund_flow(func_name: str, board_type: str) -> pd.DataFrame:
    func = getattr(ak, func_name)
    df = func(symbol="即时")
    return _normalize_sector_frame(
        df,
        source_name=f"akshare:{func_name}",
        board_type=board_type,
        money_unit="yi",
    )


def _first_available(
    candidates: list[tuple[str, Callable[[], pd.DataFrame]]],
    *,
    require_flow: bool,
) -> pd.DataFrame:
    last_errors = []
    for label, fetcher in candidates:
        try:
            df = fetcher()
            if df is None or df.empty:
                logger.warning(f"{label} 返回空数据")
                continue
            if require_flow and not _has_flow(df):
                logger.warning(f"{label} 缺少资金流字段，继续尝试备用源")
                continue
            logger.info(f"{label} 获取成功，{len(df)} 条")
            return df
        except Exception as e:
            last_errors.append(f"{label}: {e}")
            logger.warning(f"{label} 获取失败: {e}")

    if last_errors:
        logger.error("板块资金多源获取失败: " + " | ".join(last_errors))
    return pd.DataFrame()


def get_concept_board_data(
    trade_date: Optional[str] = None,
    *,
    require_flow: bool = False,
    allow_industry_fallback: bool = True,
) -> pd.DataFrame:
    candidates: list[tuple[str, Callable[[], pd.DataFrame]]] = [
        (
            "akshare:stock_board_concept_name_em",
            lambda: _fetch_akshare_board_name("stock_board_concept_name_em", "概念"),
        ),
    ]

    if trade_date:
        candidates.append(
            (
                "tushare:moneyflow_ind_dc",
                lambda: _fetch_tushare_moneyflow(trade_date, "概念/行业"),
            )
        )

    candidates.append(
        (
            "akshare:stock_fund_flow_concept",
            lambda: _fetch_akshare_fund_flow("stock_fund_flow_concept", "概念"),
        )
    )

    if allow_industry_fallback:
        candidates.append(
            (
                "akshare:stock_fund_flow_industry",
                lambda: _fetch_akshare_fund_flow("stock_fund_flow_industry", "行业替代"),
            )
        )

    return _first_available(candidates, require_flow=require_flow)


def get_industry_board_data(
    trade_date: Optional[str] = None,
    *,
    require_flow: bool = False,
) -> pd.DataFrame:
    candidates: list[tuple[str, Callable[[], pd.DataFrame]]] = [
        (
            "akshare:stock_board_industry_name_em",
            lambda: _fetch_akshare_board_name("stock_board_industry_name_em", "行业"),
        ),
    ]

    if trade_date:
        candidates.append(
            (
                "tushare:moneyflow_ind_dc",
                lambda: _fetch_tushare_moneyflow(trade_date, "概念/行业"),
            )
        )

    candidates.append(
        (
            "akshare:stock_fund_flow_industry",
            lambda: _fetch_akshare_fund_flow("stock_fund_flow_industry", "行业"),
        )
    )

    return _first_available(candidates, require_flow=require_flow)
