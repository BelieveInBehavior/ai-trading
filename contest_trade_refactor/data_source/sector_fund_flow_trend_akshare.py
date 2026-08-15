"""
板块资金流向趋势数据源

Alpha 逻辑：
- 连续3天板块净流入 + 板块内个股滞涨 = 补涨机会
- 板块资金流入加速（今日 > 昨日 > 前日）= 趋势增强
- 板块资金由流出转流入（拐点）= 反转信号
- 概念板块和行业板块交叉验证 = 高置信度

数据来源：akshare stock_board_industry_cons_em / stock_sector_fund_flow_rank
"""
import pandas as pd
import numpy as np
import asyncio
import traceback
from datetime import datetime
from data_source.data_source_base import DataSourceBase
from utils.sector_flow_provider import get_concept_board_data, get_industry_board_data
from loguru import logger
from utils.date_utils import get_latest_completed_trading_date
from utils.factor_store import SECTOR_FLOW_STORE


class SectorFundFlowTrendAkshare(DataSourceBase):
    def __init__(self):
        super().__init__("sector_fund_flow_trend_akshare")

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        try:
            trade_date = get_latest_completed_trading_date(trigger_time)
            df = self.get_data_cached(trigger_time)
            if df is not None and self.cached_data_has_trade_date(df, trade_date):
                return df

            logger.info(f"获取 {trade_date} 的板块资金流向趋势数据")

            report = self._build_sector_flow_report(trade_date)
            report = await self.maybe_web_search_supplement(
                report,
                query=f"A股板块资金流向{trade_date}",
                trigger_time=trigger_time,
                section_title="板块资金流联网补充",
            )

            data = [{
                "title": f"{trade_date}:板块资金流向趋势分析",
                "content": report,
                "pub_time": trigger_time,
                "url": None,
                "market_relevance_score": 8,
                "market_relevance_label": "high",
                "signal_event_type": "sector_flow",
                "signal_direction": "neutral",
                "signal_confidence": 0.7,
            }]
            df = pd.DataFrame(data)
            self.save_data_cached(trigger_time, df)
            return df

        except Exception as e:
            traceback.print_exc()
            logger.error(f"获取板块资金流向数据失败: {e}")
            trade_date = get_latest_completed_trading_date(trigger_time)
            return await self.akshare_web_search_fallback(
                title=f"{trade_date}:板块资金流向趋势分析",
                query=f"A股板块资金流向{trade_date}",
                trigger_time=trigger_time,
                section_title="板块资金流联网补充",
                market_relevance_score=8,
                market_relevance_label="high",
                signal_event_type="sector_flow",
                signal_direction="neutral",
                signal_confidence=0.7,
            )

    def _build_sector_flow_report(self, trade_date: str) -> str:
        """构建板块资金流向趋势报告"""
        sections = [f"## {trade_date} 板块资金流向趋势分析\n"]

        # 获取行业板块实时资金流
        industry_df = self._get_industry_fund_flow(trade_date)

        # 获取概念板块实时资金流
        concept_df = self._get_concept_fund_flow(trade_date)

        if industry_df.empty and concept_df.empty:
            return "板块资金流向数据获取失败"

        # ===== 1. 行业板块资金净流入 TOP =====
        if not industry_df.empty:
            industry_inflow = self._find_top_inflow_sectors(industry_df, "行业")
            if not industry_inflow.empty:
                sections.append("### 一、行业板块资金净流入 TOP15")
                sections.append("逻辑：行业板块整体资金持续流入，板块内标的有轮动补涨机会\n")
                for _, row in industry_inflow.head(15).iterrows():
                    sections.append(self._format_sector_row(row))

            # 行业板块资金净流出 TOP
            industry_outflow = self._find_top_outflow_sectors(industry_df, "行业")
            if not industry_outflow.empty:
                sections.append("\n### 二、行业板块资金净流出 TOP10（回避）")
                for _, row in industry_outflow.head(10).iterrows():
                    sections.append(self._format_sector_row(row))

        # ===== 2. 概念板块资金净流入 TOP =====
        if not concept_df.empty:
            concept_inflow = self._find_top_inflow_sectors(concept_df, "概念")
            if not concept_inflow.empty:
                sections.append("\n### 三、概念板块资金净流入 TOP15")
                for _, row in concept_inflow.head(15).iterrows():
                    sections.append(self._format_sector_row(row))

            concept_outflow = self._find_top_outflow_sectors(concept_df, "概念")
            if not concept_outflow.empty:
                sections.append("\n### 四、概念板块资金净流出 TOP10（回避）")
                for _, row in concept_outflow.head(10).iterrows():
                    sections.append(self._format_sector_row(row))

        # ===== 3. 多时间维度趋势确认 =====
        if not industry_df.empty:
            trend_confirmed = self._find_trend_confirmed_sectors(industry_df)
            if not trend_confirmed.empty:
                sections.append("\n### 五、行业板块多时间维度资金流入趋势确认")
                sections.append("逻辑：今日+3日+5日资金均为净流入，趋势持续性强\n")
                for _, row in trend_confirmed.head(10).iterrows():
                    name = row.get('板块名称', row.get('名称', ''))
                    flow_today = row.get('今日主力净流入', 0)
                    flow_3d = row.get('3日主力净流入', 0)
                    flow_5d = row.get('5日主力净流入', 0)
                    sections.append(
                        f"- {name}: "
                        f"今日净流入{flow_today/1e8:.2f}亿, "
                        f"3日净流入{flow_3d/1e8:.2f}亿, "
                        f"5日净流入{flow_5d/1e8:.2f}亿"
                    )

        # ===== 4. 行业+概念板块交叉验证 =====
        if not industry_df.empty and not concept_df.empty:
            cross_validated = self._cross_validate_sectors(industry_df, concept_df)
            if cross_validated:
                sections.append("\n### 六、行业×概念交叉验证（高置信度方向）")
                sections.append("逻辑：行业板块和概念板块同时大幅净流入的主题方向\n")
                for item in cross_validated[:10]:
                    sections.append(
                        f"- 行业[{item['industry']}] ↔ 概念[{item['concept']}]: "
                        f"行业净流入{item['industry_flow']/1e8:.2f}亿, "
                        f"概念净流入{item['concept_flow']/1e8:.2f}亿"
                    )

        # ===== 5. 统计摘要 =====
        sections.append(f"\n### 七、板块资金统计摘要")
        if not industry_df.empty:
            flow_col = self._find_flow_col(industry_df)
            if flow_col:
                industry_df[flow_col] = pd.to_numeric(industry_df[flow_col], errors='coerce')
                inflow_count = len(industry_df[industry_df[flow_col] > 0])
                outflow_count = len(industry_df[industry_df[flow_col] <= 0])
                total_flow = industry_df[flow_col].sum()
                sections.append(f"- 行业板块净流入数: {inflow_count}, 净流出数: {outflow_count}")
                sections.append(f"- 行业板块合计净流入: {total_flow/1e8:.2f}亿")

        # 保存结构化因子数据
        self._save_structured_factors(industry_df, trade_date)

        return "\n".join(sections)

    def _save_structured_factors(self, industry_df: pd.DataFrame, trade_date: str):
        """保存结构化因子到 FactorStore（板块级别）"""
        if industry_df.empty:
            return

        flow_col = self._find_flow_col(industry_df)
        if not flow_col:
            return

        name_col = '板块名称' if '板块名称' in industry_df.columns else '名称'
        records = []
        for _, row in industry_df.iterrows():
            name = str(row.get(name_col, ''))
            flow = float(pd.to_numeric(row.get(flow_col, 0), errors='coerce'))
            change = float(pd.to_numeric(row.get('涨跌幅', 0), errors='coerce'))

            records.append({
                "symbol_code": name,  # 板块用名称作为标识
                "symbol_name": name,
                "factor_value": flow,
                "change_pct": change,
            })

        SECTOR_FLOW_STORE.save(records, trade_date)

    def _get_industry_fund_flow(self, trade_date: str = None) -> pd.DataFrame:
        """获取行业板块资金流"""
        try:
            df = get_industry_board_data(trade_date=trade_date, require_flow=True)
            if df is None or df.empty:
                logger.warning("行业板块数据为空")
                return pd.DataFrame()
            source = df["数据源"].iloc[0] if "数据源" in df.columns else "unknown"
            logger.info(f"获取行业板块数据成功，{len(df)}条，来源: {source}")
            return df
        except Exception as e:
            logger.error(f"获取行业板块数据失败: {e}")
            return pd.DataFrame()

    def _get_concept_fund_flow(self, trade_date: str = None) -> pd.DataFrame:
        """获取概念板块资金流"""
        try:
            df = get_concept_board_data(
                trade_date=trade_date,
                require_flow=True,
                allow_industry_fallback=False,
            )
            if df is None or df.empty:
                logger.warning("概念板块数据为空")
                return pd.DataFrame()
            source = df["数据源"].iloc[0] if "数据源" in df.columns else "unknown"
            logger.info(f"获取概念板块数据成功，{len(df)}条，来源: {source}")
            return df
        except Exception as e:
            logger.error(f"获取概念板块数据失败: {e}")
            return pd.DataFrame()

    def _find_flow_col(self, df: pd.DataFrame) -> str:
        for col in ['主力净流入', '今日主力净流入', '主力净流入-净额', '净流入']:
            if col in df.columns:
                return col
        return ""

    def _find_top_inflow_sectors(self, df: pd.DataFrame, label: str) -> pd.DataFrame:
        """找到资金净流入 TOP 的板块"""
        flow_col = self._find_flow_col(df)
        if not flow_col:
            return pd.DataFrame()
        working = df.copy()
        working[flow_col] = pd.to_numeric(working[flow_col], errors='coerce')
        mask = working[flow_col] > 0
        return working[mask].sort_values(flow_col, ascending=False)

    def _find_top_outflow_sectors(self, df: pd.DataFrame, label: str) -> pd.DataFrame:
        """找到资金净流出 TOP 的板块"""
        flow_col = self._find_flow_col(df)
        if not flow_col:
            return pd.DataFrame()
        working = df.copy()
        working[flow_col] = pd.to_numeric(working[flow_col], errors='coerce')
        mask = working[flow_col] < 0
        return working[mask].sort_values(flow_col, ascending=True)

    def _find_trend_confirmed_sectors(self, df: pd.DataFrame) -> pd.DataFrame:
        """找到多时间维度资金流入趋势确认的板块"""
        cols_needed = ['今日主力净流入', '3日主力净流入', '5日主力净流入']
        # 检查列是否存在（东方财富 API 可能返回这些列）
        available = [c for c in cols_needed if c in df.columns]
        if len(available) < 2:
            # 尝试其他列名
            alt_cols = {
                '主力净流入': '今日主力净流入',
                '3日涨跌幅': None,  # skip
                '5日涨跌幅': None,
            }
            return pd.DataFrame()

        working = df.copy()
        for col in available:
            working[col] = pd.to_numeric(working[col], errors='coerce')

        mask = pd.Series(True, index=working.index)
        for col in available:
            mask = mask & (working[col] > 0)

        result = working[mask].copy()
        if not result.empty and '今日主力净流入' in result.columns:
            result = result.sort_values('今日主力净流入', ascending=False)
        return result

    def _cross_validate_sectors(self, industry_df: pd.DataFrame, concept_df: pd.DataFrame) -> list:
        """行业板块和概念板块交叉验证"""
        flow_col_ind = self._find_flow_col(industry_df)
        flow_col_con = self._find_flow_col(concept_df)
        if not flow_col_ind or not flow_col_con:
            return []

        name_col_ind = '板块名称' if '板块名称' in industry_df.columns else '名称'
        name_col_con = '板块名称' if '板块名称' in concept_df.columns else '名称'

        if name_col_ind not in industry_df.columns or name_col_con not in concept_df.columns:
            return []

        # 取行业 TOP10 和概念 TOP10
        industry_df = industry_df.copy()
        concept_df = concept_df.copy()
        industry_df[flow_col_ind] = pd.to_numeric(industry_df[flow_col_ind], errors='coerce')
        concept_df[flow_col_con] = pd.to_numeric(concept_df[flow_col_con], errors='coerce')

        top_ind = industry_df.nlargest(10, flow_col_ind)
        top_con = concept_df.nlargest(15, flow_col_con)

        # 关键词映射（行业 → 概念的常见关联）
        keyword_pairs = [
            ("电子", ["半导体", "芯片", "光刻"]),
            ("通信", ["5G", "光模块", "通信"]),
            ("计算机", ["人工智能", "云计算", "信创"]),
            ("医药", ["创新药", "医疗", "生物"]),
            ("电力设备", ["光伏", "锂电", "新能源"]),
            ("汽车", ["新能源汽车", "无人驾驶", "智能驾驶"]),
            ("有色金属", ["锂矿", "稀土", "有色"]),
            ("房地产", ["房地产", "地产"]),
            ("军工", ["军工", "航天", "国防"]),
            ("食品饮料", ["白酒", "食品", "消费"]),
        ]

        results = []
        for _, ind_row in top_ind.iterrows():
            ind_name = ind_row[name_col_ind]
            ind_flow = ind_row[flow_col_ind]
            for keyword, concept_keywords in keyword_pairs:
                if keyword not in ind_name:
                    continue
                for _, con_row in top_con.iterrows():
                    con_name = con_row[name_col_con]
                    con_flow = con_row[flow_col_con]
                    if any(ck in con_name for ck in concept_keywords):
                        results.append({
                            "industry": ind_name,
                            "concept": con_name,
                            "industry_flow": ind_flow,
                            "concept_flow": con_flow,
                            "combined_flow": ind_flow + con_flow,
                        })

        results.sort(key=lambda x: x["combined_flow"], reverse=True)
        return results

    def _format_sector_row(self, row) -> str:
        """格式化板块数据行"""
        name = row.get('板块名称', row.get('名称', ''))
        change = row.get('涨跌幅', 0)
        flow_col = None
        for col in ['主力净流入', '今日主力净流入', '主力净流入-净额']:
            if col in row.index:
                flow_col = col
                break
        flow = pd.to_numeric(row.get(flow_col, 0), errors='coerce') if flow_col else 0
        up_count = row.get('上涨家数', 0)
        down_count = row.get('下跌家数', 0)
        total = up_count + down_count

        parts = [f"- {name}: 涨跌幅{change:+.2f}%"]
        if flow:
            parts.append(f"主力净流入{flow/1e8:.2f}亿")
        if total > 0:
            parts.append(f"上涨{up_count}/{total}")
        return ", ".join(parts)


if __name__ == "__main__":
    ds = SectorFundFlowTrendAkshare()
    df = asyncio.run(ds.get_data("2026-08-09 09:00:00"))
    if not df.empty:
        print(df.content.values[0])
    else:
        print("No data returned")
