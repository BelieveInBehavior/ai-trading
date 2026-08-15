"""
akshare 的工具函数

"""
import inspect
import json
import hashlib
import pickle
import random
import time
from pathlib import Path
from datetime import datetime, timedelta
from config.config import cfg

import akshare as ak
import pandas as pd
import requests

DEFAULT_AKSHARE_CACHE_DIR = Path(__file__).parent / "akshare_cache"

# 历史 K 线按参数稳定缓存；实时类接口仍按小时失效
STABLE_CACHE_FUNCS = frozenset(
    {
        "stock_zh_a_hist",
        "stock_zh_index_daily",
        "stock_info_a_code_name",
    }
)

class CachedAksharePro:
    def __init__(self, cache_dir=None, max_retries: int = 10, timeout: float = 20.0):
        if not cache_dir:
            self.cache_dir = DEFAULT_AKSHARE_CACHE_DIR
        else:
            self.cache_dir = Path(cache_dir)
        if not self.cache_dir.exists():
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self.timeout = timeout

    def run(self, func_name: str, func_kwargs: dict, verbose: bool = False):
        func_kwargs_str = json.dumps(func_kwargs)
        return self.run_with_cache(func_name, func_kwargs_str, verbose)

    def _stock_zh_a_hist_tx_fallback(self, func_kwargs: dict, verbose: bool = False):
        raw_symbol = str(func_kwargs.get("symbol") or "")
        digits = "".join(ch for ch in raw_symbol if ch.isdigit())
        if len(digits) < 6:
            digits = digits.zfill(6)
        else:
            digits = digits[-6:]
        if digits.startswith(("60", "68", "90", "92")):
            tx_symbol = f"sh{digits}"
        else:
            tx_symbol = f"sz{digits}"
        tx_kwargs = {
            "symbol": tx_symbol,
            "start_date": func_kwargs.get("start_date", "19700101"),
            "end_date": func_kwargs.get("end_date", "20500101"),
            "adjust": func_kwargs.get("adjust", "") or "qfq",
            "timeout": min(float(self.timeout), 8.0),
        }
        if verbose:
            print(f"akshare stock_zh_a_hist fallback to stock_zh_a_hist_tx with args: {tx_kwargs}")
        df = ak.stock_zh_a_hist_tx(**tx_kwargs)
        if df is None or df.empty:
            return df
        df = df.rename(columns={
            "date": "日期",
            "open": "开盘",
            "close": "收盘",
            "high": "最高",
            "low": "最低",
            "volume": "成交量",
            "amount": "成交额",
            "turnover": "换手率",
        })
        df["股票代码"] = func_kwargs["symbol"]
        df["振幅"] = ((df["最高"] - df["最低"]) / df["收盘"].shift(1) * 100).round(2)
        df["涨跌额"] = (df["收盘"] - df["收盘"].shift(1)).round(2)
        df["涨跌幅"] = (df["涨跌额"] / df["收盘"].shift(1) * 100).round(2)
        return df[["日期", "股票代码", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]]

    def _stock_zh_a_spot_tx_fallback(self, verbose: bool = False):
        if verbose:
            print("akshare stock_zh_a_spot_em fallback to stock_zh_a_spot_tx")
        df = ak.stock_zh_a_spot_tx()
        if df is None or df.empty:
            return df
        rename_map = {
            "code": "代码",
            "name": "名称",
            "zxj": "最新价",
            "zdf": "涨跌幅",
            "zd": "涨跌额",
            "volume": "成交量",
            "turnover": "成交额",
            "zf": "振幅",
            "hsl": "换手率",
            "lb": "量比",
            "ltsz": "流通市值",
            "zsz": "总市值",
        }
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        if "代码" in df.columns:
            df["代码"] = df["代码"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(df["代码"].astype(str))
        return df

    def _stock_individual_fund_flow_rank_fallback(self, func_kwargs: dict, verbose: bool = False):
        indicator = func_kwargs.get("indicator", "今日")
        symbol_map = {"今日": "即时", "3日": "3日排行", "5日": "5日排行", "10日": "10日排行"}
        symbol = symbol_map.get(indicator, "即时")
        if verbose:
            print(f"akshare stock_individual_fund_flow_rank fallback to stock_fund_flow_individual({symbol})")
        df = ak.stock_fund_flow_individual(symbol=symbol)
        if df is None or df.empty:
            return df
        if indicator == "今日":
            df = df.rename(columns={
                "股票代码": "代码",
                "股票简称": "名称",
                "净额": "主力净流入-净额",
            })
            if "主力净流入-净额" in df.columns:
                df["主力净流入-净额"] = df["主力净流入-净额"].apply(self._parse_cn_amount)
            for pct_col in ["涨跌幅", "换手率"]:
                if pct_col in df.columns:
                    df[pct_col] = df[pct_col].apply(self._parse_percent)
        else:
            df = df.rename(columns={
                "股票代码": "代码",
                "股票简称": "名称",
                "资金流入净额": "主力净流入-净额",
                "阶段涨跌幅": "涨跌幅",
            })
            if "主力净流入-净额" in df.columns:
                df["主力净流入-净额"] = df["主力净流入-净额"].apply(self._parse_cn_amount)
            if "涨跌幅" in df.columns:
                df["涨跌幅"] = df["涨跌幅"].apply(self._parse_percent)
        if "代码" in df.columns:
            df["代码"] = df["代码"].astype(str).str.zfill(6)
        return df

    @staticmethod
    def _parse_percent(value):
        if pd.isna(value):
            return 0.0
        if isinstance(value, str):
            value = value.replace("%", "").strip()
        return pd.to_numeric(value, errors="coerce")

    @staticmethod
    def _parse_cn_amount(value):
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
        return 0.0 if pd.isna(number) else sign * float(number) * multiplier

    def _call_akshare(self, func_name: str, func_kwargs: dict, verbose: bool = False):
        func = getattr(ak, func_name)
        call_kwargs = dict(func_kwargs)
        signature = inspect.signature(func)
        if "timeout" in signature.parameters and "timeout" not in call_kwargs:
            call_kwargs["timeout"] = self.timeout

        last_error = None
        fallback_retry_limits = {
            "stock_zh_a_hist": 1,
            "stock_zh_a_spot_em": 2,
            "stock_individual_fund_flow_rank": 2,
        }
        retry_limit = fallback_retry_limits.get(func_name, self.max_retries)
        if func_name == "stock_zh_a_hist":
            # Tencent is dramatically faster in this environment; try it first.
            try:
                tx_df = self._stock_zh_a_hist_tx_fallback(func_kwargs, verbose=verbose)
                if tx_df is not None and not tx_df.empty:
                    return tx_df
            except Exception as e:
                if verbose:
                    print(f"akshare stock_zh_a_hist_tx fast path failed: {e}")
        for attempt in range(1, retry_limit + 1):
            try:
                return func(**call_kwargs)
            except Exception as e:
                fallback_funcs = {
                    "stock_zh_a_hist",
                    "stock_zh_a_spot_em",
                    "stock_individual_fund_flow_rank",
                    "stock_margin_detail_sse",
                    "stock_margin_detail_szse",
                    "stock_dzjy_mrtj",
                    "stock_dzjy_mrmx",
                }
                if func_name not in fallback_funcs:
                    raise
                last_error = e
                retryable = isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))
                if not retryable or attempt == retry_limit:
                    break
                delay = min(8.0, 0.5 * (2 ** (attempt - 1))) + random.uniform(0, 0.5)
                if verbose:
                    print(f"akshare {func_name} attempt {attempt}/{retry_limit} failed: {e}; retry in {delay:.2f}s")
                time.sleep(delay)
        if func_name == "stock_zh_a_hist":
            try:
                tx_df = self._stock_zh_a_hist_tx_fallback(func_kwargs, verbose=verbose)
                if tx_df is not None and not tx_df.empty:
                    return tx_df
            except Exception as fallback_error:
                if verbose:
                    print(f"akshare stock_zh_a_hist_tx fallback failed: {fallback_error}")
            if verbose:
                print(
                    "akshare stock_zh_a_hist failed; skip Yahoo, "
                    "return empty (use Agent-level web search for narrative data)"
                )
            return pd.DataFrame()
        if func_name == "stock_zh_a_spot_em":
            try:
                return self._stock_zh_a_spot_tx_fallback(verbose=verbose)
            except Exception as fallback_error:
                if verbose:
                    print(f"akshare stock_zh_a_spot_tx fallback failed: {fallback_error}")
        if func_name == "stock_individual_fund_flow_rank":
            try:
                return self._stock_individual_fund_flow_rank_fallback(func_kwargs, verbose=verbose)
            except Exception as fallback_error:
                if verbose:
                    print(f"akshare stock_fund_flow_individual fallback failed: {fallback_error}")
        if func_name in {"stock_margin_detail_sse", "stock_margin_detail_szse", "stock_dzjy_mrtj", "stock_dzjy_mrmx"}:
            if verbose:
                print(f"akshare {func_name} returned malformed empty response; use empty DataFrame")
            return pd.DataFrame()
        raise last_error

    def run_with_cache(self, func_name: str, func_kwargs: str, verbose: bool = False):
        func_kwargs = json.loads(func_kwargs)
        args_hash = hashlib.md5(str(func_kwargs).encode()).hexdigest()
        if func_name not in STABLE_CACHE_FUNCS:
            trigger_time = datetime.now().strftime("%Y%m%d%H")
            args_hash = f"{args_hash}_{trigger_time}"
        func_cache_dir = self.cache_dir / func_name
        if not func_cache_dir.exists():
            func_cache_dir.mkdir(parents=True, exist_ok=True)
        func_cache_file = func_cache_dir / f"{args_hash}.pkl"
        if func_cache_file.exists():
            if verbose:
                print(f"load result from {func_cache_file}")
            with open(func_cache_file, "rb") as f:
                return pickle.load(f)
        else:
            if verbose:
                print(f"cache miss for {func_name} with args: {func_kwargs}")
            result = self._call_akshare(func_name, func_kwargs, verbose=verbose)
            if verbose:
                print(f"save result to {func_cache_file}")
            with open(func_cache_file, "wb") as f:
                pickle.dump(result, f)
            return result

akshare_cached = CachedAksharePro()

if __name__ == "__main__":
    stock_sse_summary_df = akshare_cached.run(
        func_name="stock_sse_summary", 
        func_kwargs={},
        verbose=True
    )
    print(stock_sse_summary_df)
