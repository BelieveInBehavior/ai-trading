"""
个股资金流数据源（主力/散户分离）

Alpha 逻辑：
- 主力净流入但股价未涨 = 吸筹阶段，次日大概率拉升
- 主力持续流出但股价不跌 = 护盘出货，次日大概率下跌
- 连续3天主力净流入 + 今日缩量 = 洗盘结束信号

数据来源：akshare stock_individual_fund_flow_rank（东方财富个股资金流排名）
"""
import pandas as pd
import numpy as np
import asyncio
import traceback
from datetime import datetime
from data_source.data_source_base import DataSourceBase
from utils.akshare_utils import akshare_cached
from loguru import logger
from utils.date_utils import get_latest_completed_trading_date
from utils.factor_store import FUND_FLOW_STORE
from utils.threshold_manager import THRESHOLD_MANAGER


class IndividualFundFlowAkshare(DataSourceBase):
    def __init__(self):
        super().__init__("individual_fund_flow_akshare")

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        try:
            trade_date = get_latest_completed_trading_date(trigger_time)
            df = self.get_data_cached(trigger_time)
            if df is not None and self.cached_data_has_trade_date(df, trade_date):
                return df

            logger.info(f"获取 {trade_date} 的个股资金流数据")

            report = await self._build_fund_flow_report(trade_date)

            data = [{
                "title": f"{trade_date}:个股主力资金流分析",
                "content": report,
                "pub_time": trigger_time,
                "url": None,
                "market_relevance_score": 8,
                "market_relevance_label": "high",
                "signal_event_type": "capital_flow",
                "signal_direction": "neutral",
                "signal_confidence": 0.7,
            }]
            df = pd.DataFrame(data)
            self.save_data_cached(trigger_time, df)
            return df

        except Exception as e:
            traceback.print_exc()
            logger.error(f"获取个股资金流数据失败: {e}")
            return pd.DataFrame()

    async def _build_fund_flow_report(self, trade_date: str) -> str:
        """构建个股资金流分析报告（纯数据，不使用 LLM）"""
        sections = [f"## {trade_date} 个股主力资金流分析\n"]

        # 获取当日资金流排名（按主力净流入排序）
        flow_df = self._get_fund_flow_rank("今日")
        if flow_df.empty:
            return "当日个股资金流数据获取失败"

        # 获取 3 日资金流（用于识别连续流入/流出模式）
        flow_3d_df = self._get_fund_flow_rank("3日")

        # 获取 5 日资金流
        flow_5d_df = self._get_fund_flow_rank("5日")

        # 保存结构化因子数据
        self._save_structured_factors(flow_df, flow_3d_df, flow_5d_df, trade_date)

        # ===== 1. 主力大幅净流入但涨幅较小（吸筹信号）=====
        absorption = self._find_absorption_signals(flow_df)
        if not absorption.empty:
            sections.append("### 一、主力吸筹信号（主力大幅净流入 + 涨幅偏低）")
            sections.append("逻辑：主力资金大量流入但股价未明显上涨，可能在吸筹阶段\n")
            for _, row in absorption.head(15).iterrows():
                sections.append(
                    f"- {row['名称']}({row['代码']}): "
                    f"涨跌幅{row['涨跌幅']:+.2f}%, "
                    f"主力净流入{row['主力净流入-净额']/1e8:.2f}亿, "
                    f"主力净占比{row.get('主力净流入-净占比', 0):.1f}%, "
                    f"收盘价{row.get('最新价', 'N/A')}"
                )

        # ===== 2. 主力大幅净流出但跌幅较小（护盘出货信号）=====
        distribution = self._find_distribution_signals(flow_df)
        if not distribution.empty:
            sections.append("\n### 二、主力出货信号（主力大幅净流出 + 跌幅偏小）")
            sections.append("逻辑：主力资金大量流出但股价未明显下跌，可能在护盘出货\n")
            for _, row in distribution.head(10).iterrows():
                sections.append(
                    f"- {row['名称']}({row['代码']}): "
                    f"涨跌幅{row['涨跌幅']:+.2f}%, "
                    f"主力净流出{abs(row['主力净流入-净额'])/1e8:.2f}亿, "
                    f"收盘价{row.get('最新价', 'N/A')}"
                )

        # ===== 3. 连续多日主力净流入（趋势确认）=====
        if not flow_3d_df.empty and not flow_5d_df.empty:
            trend = self._find_trend_confirmation(flow_df, flow_3d_df, flow_5d_df)
            if not trend.empty:
                sections.append("\n### 三、连续主力资金流入确认")
                sections.append("逻辑：今日+3日+5日主力均为净流入，资金持续进场\n")
                for _, row in trend.head(15).iterrows():
                    sections.append(
                        f"- {row['名称']}({row['代码']}): "
                        f"今日涨跌幅{row['涨跌幅']:+.2f}%, "
                        f"今日主力净流入{row['主力净流入-净额']/1e8:.2f}亿, "
                        f"3日主力净流入{row['主力净流入_3d']/1e8:.2f}亿, "
                        f"5日主力净流入{row['主力净流入_5d']/1e8:.2f}亿"
                    )

        # ===== 4. 超大单异动（机构行为）=====
        super_large = self._find_super_large_order_signals(flow_df)
        if not super_large.empty:
            sections.append("\n### 四、超大单异动（机构行为）")
            sections.append("逻辑：超大单净流入占比极高，表明机构级别资金介入\n")
            for _, row in super_large.head(10).iterrows():
                sections.append(
                    f"- {row['名称']}({row['代码']}): "
                    f"涨跌幅{row['涨跌幅']:+.2f}%, "
                    f"超大单净流入{row.get('超大单净流入-净额', 0)/1e8:.2f}亿, "
                    f"超大单净占比{row.get('超大单净流入-净占比', 0):.1f}%"
                )

        # ===== 5. 统计摘要 =====
        sections.append(f"\n### 五、市场资金流统计摘要")
        total_stocks = len(flow_df)
        net_inflow_count = len(flow_df[flow_df['主力净流入-净额'] > 0])
        net_outflow_count = total_stocks - net_inflow_count
        total_net = flow_df['主力净流入-净额'].sum()
        sections.append(f"- 全市场股票数: {total_stocks}")
        sections.append(f"- 主力净流入股票数: {net_inflow_count} ({net_inflow_count/total_stocks*100:.1f}%)")
        sections.append(f"- 主力净流出股票数: {net_outflow_count} ({net_outflow_count/total_stocks*100:.1f}%)")
        sections.append(f"- 全市场主力净流入合计: {total_net/1e8:.2f}亿")

        return "\n".join(sections)

    def _get_fund_flow_rank(self, indicator: str) -> pd.DataFrame:
        """获取个股资金流排名"""
        try:
            df = akshare_cached.run(
                func_name="stock_individual_fund_flow_rank",
                func_kwargs={"indicator": indicator},
                verbose=False
            )
            if df is None or df.empty:
                logger.warning(f"个股资金流排名({indicator})数据为空")
                return pd.DataFrame()
            logger.info(f"获取个股资金流排名({indicator})成功，{len(df)}条")
            return df
        except Exception as e:
            logger.error(f"获取个股资金流排名({indicator})失败: {e}")
            return pd.DataFrame()

    def _find_absorption_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        找到主力吸筹信号：主力大幅净流入 + 涨幅偏低
        """
        if df.empty or '主力净流入-净额' not in df.columns:
            return pd.DataFrame()

        t = THRESHOLD_MANAGER.get("individual_fund_flow")
        working = df.copy()
        mask = (
            (working['主力净流入-净额'] > t.get("absorption_min_net_flow", 5e7))
            & (working['涨跌幅'] < t.get("absorption_max_change_pct", 3.0))
            & (working['涨跌幅'] > t.get("absorption_min_change_pct", -2.0))
        )
        result = working[mask].sort_values('主力净流入-净额', ascending=False)
        return result

    def _find_distribution_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        找到主力出货信号：主力大幅净流出 + 跌幅偏小
        """
        if df.empty or '主力净流入-净额' not in df.columns:
            return pd.DataFrame()

        t = THRESHOLD_MANAGER.get("individual_fund_flow")
        working = df.copy()
        mask = (
            (working['主力净流入-净额'] < t.get("distribution_max_net_flow", -5e7))
            & (working['涨跌幅'] > t.get("distribution_min_change_pct", -2.0))
            & (working['涨跌幅'] < t.get("distribution_max_change_pct", 1.0))
        )
        result = working[mask].sort_values('主力净流入-净额', ascending=True)
        return result

    def _find_trend_confirmation(
        self, df_1d: pd.DataFrame, df_3d: pd.DataFrame, df_5d: pd.DataFrame
    ) -> pd.DataFrame:
        """找到连续资金流入确认的股票"""
        if df_1d.empty or df_3d.empty or df_5d.empty:
            return pd.DataFrame()

        try:
            # 合并三个时间维度
            merged = df_1d[['代码', '名称', '涨跌幅', '最新价', '主力净流入-净额']].copy()
            df_3d_slim = df_3d[['代码', '主力净流入-净额']].rename(
                columns={'主力净流入-净额': '主力净流入_3d'}
            )
            df_5d_slim = df_5d[['代码', '主力净流入-净额']].rename(
                columns={'主力净流入-净额': '主力净流入_5d'}
            )

            merged = merged.merge(df_3d_slim, on='代码', how='inner')
            merged = merged.merge(df_5d_slim, on='代码', how='inner')

            # 三个维度都是净流入
            mask = (
                (merged['主力净流入-净额'] > 0)
                & (merged['主力净流入_3d'] > 0)
                & (merged['主力净流入_5d'] > 0)
            )
            result = merged[mask].sort_values('主力净流入_5d', ascending=False)
            return result
        except Exception as e:
            logger.error(f"计算连续资金流入确认失败: {e}")
            return pd.DataFrame()

    def _find_super_large_order_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """找到超大单异动信号"""
        col = '超大单净流入-净额'
        pct_col = '超大单净流入-净占比'
        if df.empty or col not in df.columns:
            return pd.DataFrame()

        working = df.copy()
        t = THRESHOLD_MANAGER.get("individual_fund_flow")
        mask = (working[col] > t.get("super_large_min_amount", 1e8))
        if pct_col in working.columns:
            mask = mask & (working[pct_col] > t.get("super_large_min_pct", 5.0))
        result = working[mask].sort_values(col, ascending=False)
        return result

    def _save_structured_factors(
        self, flow_df: pd.DataFrame, flow_3d_df: pd.DataFrame, flow_5d_df: pd.DataFrame, trade_date: str
    ):
        """保存结构化因子到 FactorStore"""
        if flow_df.empty or '主力净流入-净额' not in flow_df.columns:
            return

        records = []
        for _, row in flow_df.iterrows():
            code = str(row.get('代码', '')).zfill(6)
            name = str(row.get('名称', ''))
            net_flow = float(row.get('主力净流入-净额', 0))
            change_pct = float(row.get('涨跌幅', 0))
            price = float(row.get('最新价', 0))

            records.append({
                "symbol_code": code,
                "symbol_name": name,
                "factor_value": net_flow,
                "change_pct": change_pct,
                "price": price,
                "super_large_net": float(row.get('超大单净流入-净额', 0)),
                "main_pct": float(row.get('主力净流入-净占比', 0)),
            })

        FUND_FLOW_STORE.save(records, trade_date)


if __name__ == "__main__":
    ds = IndividualFundFlowAkshare()
    df = asyncio.run(ds.get_data("2026-08-09 09:00:00"))
    if not df.empty:
        print(df.content.values[0])
    else:
        print("No data returned")
