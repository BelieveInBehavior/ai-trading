"""
联网搜索市场数据补充 Agent

当 AkShare 结构化数据缺失时，用豆包搜索补充：
- 龙虎榜 / 游资动向
- 涨停封板 / 连板
- 大宗交易
"""

from __future__ import annotations

import asyncio
import traceback

import pandas as pd
from loguru import logger

from data_source.data_source_base import DataSourceBase
from utils.date_utils import get_latest_completed_trading_date
from utils.web_search_supplement import fetch_web_search_context


class WebSearchMarketSupplement(DataSourceBase):
    QUERIES = (
        ("A股龙虎榜", "龙虎榜与游资席位"),
        ("A股涨停", "涨停与连板"),
        ("A股大宗交易", "大宗交易折溢价"),
    )

    def __init__(self):
        super().__init__("web_search_market_supplement")

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        try:
            trade_date = get_latest_completed_trading_date(trigger_time)
            df = self.get_data_cached(trigger_time)
            if df is not None and self.cached_data_has_trade_date(df, trade_date):
                return df

            sections = [f"## {trade_date} 联网搜索市场数据补充\n"]
            for query_suffix, title in self.QUERIES:
                block = await fetch_web_search_context(
                    query=f"{query_suffix}{trade_date}",
                    trigger_time=trigger_time,
                    topk=4,
                    section_title=title,
                )
                if block.strip():
                    sections.append(block)

            if len(sections) <= 1:
                logger.warning("Web search market supplement returned no results")
                return pd.DataFrame()

            content = "".join(sections)
            data = [{
                "title": f"{trade_date}:联网搜索市场数据补充",
                "content": content,
                "pub_time": trigger_time,
                "url": None,
                "market_relevance_score": 6,
                "market_relevance_label": "medium",
                "signal_event_type": "web_search_supplement",
                "signal_direction": "neutral",
                "signal_confidence": 0.55,
            }]
            df = pd.DataFrame(data)
            self.save_data_cached(trigger_time, df)
            return df
        except Exception as exc:
            traceback.print_exc()
            logger.error(f"联网搜索市场数据补充失败: {exc}")
            return pd.DataFrame()


if __name__ == "__main__":
    ds = WebSearchMarketSupplement()
    out = asyncio.run(ds.get_data("2026-08-12 15:54:46"))
    print(out["content"].values[0][:1500] if not out.empty else "empty")
