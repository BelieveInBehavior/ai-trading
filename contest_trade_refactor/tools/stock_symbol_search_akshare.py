"""
Stock Symbol Search Tool (AKShare Version)
Search for stock symbols by company names or partial symbols using AKShare data.
"""
import re
import json
import time
import asyncio
import pandas as pd
from typing import List, Dict, Any
from pydantic import BaseModel, Field

from tools.tool_utils import smart_tool
from utils.akshare_utils import akshare_cached

class StockSymbolSearchAkshareInput(BaseModel):
    market: str = Field(description="The target market. Currently supports: CN-Stock")
    queries: List[str] = Field(description="List of search queries: company names or stock symbols (partial match supported)")
    trigger_time: str = Field(description="The trigger time. Format: YYYY-MM-DD HH:MM:SS")
    limit_per_query: int = Field(default=5, description="Maximum number of results per query")
    match_mode: str = Field(default="best", description="Match mode: 'best' (top match), 'all' (all matches), 'exact' (exact only)")

# Module-level cache: never cache empty results, TTL = 4 hours
_stock_basic_cache: Dict[str, Any] = {"data": None, "timestamp": 0}
_CACHE_TTL = 4 * 3600  # 4 hours
_MAX_RETRIES = 3


def get_stock_basic_akshare():
    """Get basic stock information from AKShare with retry.

    Uses a module-level cache with 4-hour TTL and a "never cache empty" policy.
    Retries up to 3 times. If all attempts fail, returns empty DataFrame (error exposed to caller).
    """
    now = time.time()

    # Return cached data if valid
    if (
        _stock_basic_cache["data"] is not None
        and (now - _stock_basic_cache["timestamp"]) < _CACHE_TTL
    ):
        return _stock_basic_cache["data"]

    # ----- Primary source: stock_zh_a_spot_em (rich data, market-hours only) -----
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            df = akshare_cached.run(
                func_name="stock_zh_a_spot_em",
                func_kwargs={},
                verbose=False,
            )
            if df is not None and not df.empty:
                columns_mapping = {
                    '代码': 'ts_code',
                    '名称': 'name',
                    '最新价': 'close',
                    '涨跌幅': 'pct_chg',
                    '总市值': 'total_mv',
                    '流通市值': 'circ_mv',
                }
                existing_mapping = {k: v for k, v in columns_mapping.items() if k in df.columns}
                df = df.rename(columns=existing_mapping)

                if 'ts_code' in df.columns and 'name' in df.columns and len(df) > 0:
                    _stock_basic_cache["data"] = df
                    _stock_basic_cache["timestamp"] = now
                    return df
            break  # Got response but empty, don't retry same source
        except Exception as e:
            print(f"[stock_symbol_search] Primary source attempt {attempt}/{_MAX_RETRIES} failed: {e}")
            if attempt < _MAX_RETRIES:
                time.sleep(2)

    # ----- Fallback source: stock_info_a_code_name (lightweight, works anytime) -----
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            df_fallback = akshare_cached.run(
                func_name="stock_info_a_code_name",
                func_kwargs={},
                verbose=False,
            )
            if df_fallback is not None and not df_fallback.empty:
                fb_mapping = {
                    '代码': 'ts_code',
                    'code': 'ts_code',
                    '名称': 'name',
                }
                existing_fb = {k: v for k, v in fb_mapping.items() if k in df_fallback.columns}
                df_fallback = df_fallback.rename(columns=existing_fb)

                if 'ts_code' in df_fallback.columns and 'name' in df_fallback.columns and len(df_fallback) > 0:
                    print(f"[stock_symbol_search] Using fallback source (stock_info_a_code_name): {len(df_fallback)} stocks")
                    _stock_basic_cache["data"] = df_fallback
                    _stock_basic_cache["timestamp"] = now
                    return df_fallback
            break  # Got response but empty
        except Exception as e:
            print(f"[stock_symbol_search] Fallback source attempt {attempt}/{_MAX_RETRIES} failed: {e}")
            if attempt < _MAX_RETRIES:
                time.sleep(2)

    # ----- All sources failed -----
    print("[stock_symbol_search] ERROR: All data sources failed after retries. Returning empty.")
    return pd.DataFrame()


def calculate_match_score(query: str, ts_code: str, name: str) -> tuple[str, float]:
    """Calculate match score and type"""
    query_lower = query.lower()
    ts_code_lower = ts_code.lower()
    name_lower = name.lower()

    if query == ts_code or query == name:
        return "exact", 1.0
    if query_lower == ts_code_lower or query_lower == name_lower:
        return "exact", 1.0
    if ts_code_lower.startswith(query_lower) or name_lower.startswith(query_lower):
        return "prefix", 0.9
    if query_lower in ts_code_lower or query_lower in name_lower:
        return "contains", 0.8
    if re.search(re.escape(query_lower), ts_code_lower) or re.search(re.escape(query_lower), name_lower):
        return "fuzzy", 0.7

    return "none", 0.0

def search_single_query(symbols_df: pd.DataFrame, query: str, limit: int, match_mode: str, market: str) -> List[Dict[str, Any]]:
    """Search for a single query in the symbols dataframe"""
    results = []

    if symbols_df.empty:
        return results

    for _, row in symbols_df.iterrows():
        ts_code = str(row.get('ts_code', ''))
        name = str(row.get('name', ''))

        if not ts_code or not name:
            continue

        match_type, score = calculate_match_score(query, ts_code, name)

        if match_mode == "exact" and match_type != "exact":
            continue

        if score > 0:
            results.append({
                "ts_code": ts_code,
                "name": name,
                "market": market,
                "match_type": match_type,
                "match_score": score
            })

    results.sort(key=lambda x: (x['match_score'], x['match_type'] == 'exact'), reverse=True)

    if match_mode == "best":
        return results[:1]
    else:
        return results[:limit]

@smart_tool(
    description="Search for stock symbols by company names or partial symbols using AKShare data. Supports Chinese company names and stock codes.",
    args_schema=StockSymbolSearchAkshareInput,
    max_output_len=4000,
    timeout_seconds=60.0
)
async def stock_symbol_search(
    market: str,
    queries: List[str],
    trigger_time: str,
    limit_per_query: int = 5,
    match_mode: str = "best"
) -> Dict[str, Any]:
    """Search for stock symbols using AKShare data."""

    try:
        if market != "CN-Stock":
            return {
                "error": f"Market {market} not supported. Only CN-Stock is currently supported.",
                "results": {},
                "summary": {"total_queries": len(queries), "successful_matches": 0, "failed_matches": len(queries)},
                "failed_queries": [{"query": q, "error": f"Unsupported market: {market}"} for q in queries]
            }

        symbols_df = get_stock_basic_akshare()

        if symbols_df.empty:
            return {
                "error": "All stock data sources failed after retries. Cannot perform search.",
                "results": {},
                "summary": {"total_queries": len(queries), "successful_matches": 0, "failed_matches": len(queries)},
                "failed_queries": [{"query": q, "error": "Data source unavailable"} for q in queries]
            }

        print(f"Loaded {len(symbols_df)} stocks for search")

        results = {}
        failed_queries = []

        for query in queries:
            if not query or not query.strip():
                failed_queries.append({"query": query, "error": "Empty query"})
                continue

            try:
                matches = search_single_query(symbols_df, query.strip(), limit_per_query, match_mode, market)
                if matches:
                    results[query] = matches
                else:
                    failed_queries.append({"query": query, "error": "No matches found"})
            except Exception as e:
                failed_queries.append({"query": query, "error": str(e)})

        summary = {
            "total_queries": len(queries),
            "successful_matches": len(results),
            "failed_matches": len(failed_queries),
            "total_results": sum(len(matches) for matches in results.values())
        }

        return {
            "results": results,
            "summary": summary,
            "failed_queries": failed_queries,
            "market": market,
            "trigger_time": trigger_time
        }

    except Exception as e:
        error_msg = f"Stock symbol search failed: {str(e)}"
        print(error_msg)
        return {
            "error": error_msg,
            "results": {},
            "summary": {"total_queries": len(queries), "successful_matches": 0, "failed_matches": len(queries)},
            "failed_queries": [{"query": q, "error": error_msg} for q in queries]
        }

if __name__ == "__main__":
    async def test():
        result = await stock_symbol_search.ainvoke({
            "market": "CN-Stock",
            "queries": ["茅台", "平安银行", "000001"],
            "trigger_time": "2025-08-21 12:00:00",
            "limit_per_query": 3,
            "match_mode": "best"
        })
        print(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(test())
