"""
基于 akshare 的北向资金（沪深港通）数据源
纯数据格式化，不使用LLM

主要功能：
1. 获取沪股通/深股通历史净买入数据
2. 获取北向资金汇总数据
3. 生成结构化文本摘要

实际可用的akshare接口：
- stock_hsgt_hist_em(symbol='沪股通'/'深股通') -> 历史净买入
- stock_hsgt_fund_flow_summary_em() -> 资金流向汇总
"""
import pandas as pd
import asyncio
import traceback
from datetime import datetime
from data_source.data_source_base import DataSourceBase
from utils.akshare_utils import akshare_cached
from loguru import logger
from utils.date_utils import get_latest_completed_trading_date


class NorthboundFlowAkshare(DataSourceBase):
    def __init__(self):
        super().__init__("northbound_flow_akshare")

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        try:
            trade_date = get_latest_completed_trading_date(trigger_time)
            df = self.get_data_cached(trigger_time)
            if df is not None and self.cached_data_has_trade_date(df, trade_date):
                return df

            logger.info(f"获取 {trade_date} 的北向资金数据")

            # 获取沪股通历史数据
            hu_hist_df = self._get_hsgt_hist("沪股通")
            # 获取深股通历史数据
            shen_hist_df = self._get_hsgt_hist("深股通")
            # 获取资金流向汇总
            summary_df = self._get_fund_flow_summary()

            # 防止 future leak：只保留 trade_date 及之前的数据
            hu_hist_df = self._filter_asof(hu_hist_df, trade_date)
            shen_hist_df = self._filter_asof(shen_hist_df, trade_date)
            summary_df = self._filter_summary_asof(summary_df, trade_date)

            # 生成文本摘要
            summary = self._build_summary(trade_date, hu_hist_df, shen_hist_df, summary_df)
            summary = await self.maybe_web_search_supplement(
                summary,
                query=f"北向资金{trade_date}",
                trigger_time=trigger_time,
                section_title="北向资金联网补充",
            )

            data = [{
                "title": f"{trade_date}:北向资金数据汇总",
                "content": summary,
                "pub_time": trigger_time,
                "url": None
            }]
            df = pd.DataFrame(data)
            self.save_data_cached(trigger_time, df)
            return df

        except Exception as e:
            traceback.print_exc()
            logger.error(f"获取北向资金数据失败: {e}")
            trade_date = get_latest_completed_trading_date(trigger_time)
            return await self.akshare_web_search_fallback(
                title=f"{trade_date}:北向资金数据汇总",
                query=f"北向资金{trade_date}",
                trigger_time=trigger_time,
                section_title="北向资金联网补充",
            )

    def _get_hsgt_hist(self, symbol: str) -> pd.DataFrame:
        """获取沪股通/深股通历史数据"""
        try:
            df = akshare_cached.run(
                func_name="stock_hsgt_hist_em",
                func_kwargs={"symbol": symbol},
                verbose=False
            )
            if df is None or df.empty:
                logger.warning(f"无{symbol}历史数据")
                return pd.DataFrame()
            logger.info(f"获取{symbol}历史数据成功，{len(df)} 条记录")
            return df
        except Exception as e:
            logger.error(f"获取{symbol}历史数据失败: {e}")
            return pd.DataFrame()

    def _get_fund_flow_summary(self) -> pd.DataFrame:
        """获取北向资金流向汇总"""
        try:
            df = akshare_cached.run(
                func_name="stock_hsgt_fund_flow_summary_em",
                func_kwargs={},
                verbose=False
            )
            if df is None or df.empty:
                logger.warning("无北向资金流向汇总数据")
                return pd.DataFrame()
            logger.info(f"获取北向资金流向汇总成功，{len(df)} 条记录")
            return df
        except Exception as e:
            logger.error(f"获取北向资金流向汇总失败: {e}")
            return pd.DataFrame()

    def _filter_asof(self, df: pd.DataFrame, trade_date: str, date_col: str = "日期") -> pd.DataFrame:
        """仅保留日期列 <= trade_date 的历史数据，防止 future leak。"""
        if df is None or df.empty or date_col not in df.columns:
            return df
        work = df.copy()
        work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
        asof = pd.to_datetime(trade_date, format="%Y%m%d")
        return work[work[date_col].notna() & (work[date_col] <= asof)]

    def _filter_summary_asof(self, df: pd.DataFrame, trade_date: str, date_col: str = "交易日") -> pd.DataFrame:
        """仅保留资金流向汇总中交易日 <= trade_date 的行。"""
        if df is None or df.empty or date_col not in df.columns:
            return df
        work = df.copy()
        work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
        as_of = pd.to_datetime(trade_date, format="%Y%m%d")
        return work[work[date_col].notna() & (work[date_col] <= as_of)]

    def _build_summary(self, trade_date: str, hu_hist_df: pd.DataFrame,
                       shen_hist_df: pd.DataFrame, summary_df: pd.DataFrame) -> str:
        """构建纯数据文本摘要（不使用LLM）"""
        sections = [f"## {trade_date} 北向资金数据汇总\n"]

        # 1. 资金流向汇总（最新日期）
        if not summary_df.empty:
            sections.append("### 一、当日北向资金汇总")
            # 筛选北向数据
            north_rows = summary_df[summary_df['资金方向'] == '北向'] if '资金方向' in summary_df.columns else pd.DataFrame()
            if not north_rows.empty:
                for _, row in north_rows.iterrows():
                    channel = row.get('板块', '')
                    date = row.get('交易日', '')
                    net_buy = row.get('成交净买额', 0)
                    net_flow = row.get('资金净流入', 0)
                    up_count = row.get('上涨数', 0)
                    down_count = row.get('下跌数', 0)
                    index_name = row.get('相关指数', '')
                    index_chg = row.get('指数涨跌幅', 0)
                    trade_status = row.get('交易状态', None)
                    amount_note = ""
                    if self._is_missing_amount(net_buy) and self._is_missing_amount(net_flow):
                        amount_note = "（盘中/数据源暂未披露净买额，以下涨跌停家数与指数仍可供参考）"
                    sections.append(
                        f"- **{channel}** ({date}): 成交净买额{self._format_amount(net_buy)}, "
                        f"资金净流入{self._format_amount(net_flow)}, "
                        f"上涨{up_count}/下跌{down_count}, "
                        f"{index_name} {index_chg:+.2f}%{amount_note}"
                    )
            else:
                sections.append("当日无北向资金汇总数据")
        else:
            sections.append("### 一、当日北向资金汇总\n无数据")

        # 2. 沪股通历史净买入（近期数据）
        self._append_hist_summary(sections, hu_hist_df, "沪股通", "二")

        # 3. 深股通历史净买入（近期数据）
        self._append_hist_summary(sections, shen_hist_df, "深股通", "三")

        if summary_df.empty and hu_hist_df.empty and shen_hist_df.empty:
            sections.append("当日无北向资金相关数据")

        return "\n".join(sections)

    def _append_hist_summary(self, sections: list, hist_df: pd.DataFrame,
                             channel: str, section_num: str):
        """添加历史净买入摘要"""
        if hist_df.empty:
            sections.append(f"\n### {section_num}、{channel}历史净买入\n无数据")
            return

        sections.append(f"\n### {section_num}、{channel}历史净买入")

        # 列: 日期, 当日成交净买额, 买入成交额, 卖出成交额, 历史累计净买额, 领涨股, 领涨股-涨跌幅
        if '日期' in hist_df.columns:
            sorted_df = hist_df.sort_values('日期', ascending=False).head(10).copy()

            # 取有效数据（非NaN）
            net_col = '当日成交净买额'
            if net_col in sorted_df.columns:
                valid_df = sorted_df.dropna(subset=[net_col])
                if not valid_df.empty:
                    # 最新有效日
                    latest = valid_df.iloc[0]
                    sections.append(f"**最近有效日净买入**: {self._format_amount(latest[net_col])} ({latest['日期']})")

                    # 近5日累计
                    recent_5 = valid_df.head(5)
                    cum_5 = recent_5[net_col].sum()
                    sections.append(f"**近5个有效交易日累计**: {self._format_amount(cum_5)}")

                    sections.append("\n**近期逐日明细**:")
                    for _, row in valid_df.head(5).iterrows():
                        date_str = str(row['日期'])[:10]
                        flow_str = self._format_amount(row[net_col])
                        leader = row.get('领涨股', '')
                        leader_chg = row.get('领涨股-涨跌幅', 0)
                        leader_str = f", 领涨: {leader}({leader_chg:+.2f}%)" if leader else ""
                        sections.append(f"- {date_str}: 净买入{flow_str}{leader_str}")
                else:
                    # 近期全部NaN，展示领涨股信息并提示最近可用净买额
                    last_valid = self._find_last_valid_hist_row(hist_df, net_col)
                    sections.append("近期净买额数据暂缺（可能为非交易日、盘中未更新或数据源延迟）")
                    if last_valid is not None:
                        sections.append(
                            f"**最近可用净买额**: {self._format_amount(last_valid[net_col])} "
                            f"({str(last_valid['日期'])[:10]})"
                        )
                    recent = sorted_df.head(5)
                    for _, row in recent.iterrows():
                        leader = row.get('领涨股', '')
                        leader_chg = row.get('领涨股-涨跌幅', 0)
                        index_val = row.get('上证指数', '')
                        index_chg = row.get('上证指数-涨跌幅', 0)
                        if leader:
                            sections.append(
                                f"- {str(row['日期'])[:10]}: 领涨{leader}({leader_chg:+.2f}%), "
                                f"上证{index_val}({index_chg:+.2f}%)"
                            )
            else:
                sections.append(f"数据列不匹配，可用列: {list(hist_df.columns)}")
        else:
            sections.append(f"数据列不匹配，可用列: {list(hist_df.columns)}")

    @staticmethod
    def _is_missing_amount(value) -> bool:
        try:
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return True
            return abs(float(value)) < 1e-9
        except (ValueError, TypeError):
            return True

    @staticmethod
    def _find_last_valid_hist_row(hist_df: pd.DataFrame, net_col: str):
        if hist_df.empty or net_col not in hist_df.columns:
            return None
        working = hist_df.copy()
        if '日期' in working.columns:
            working = working.sort_values('日期', ascending=False)
        valid = working.dropna(subset=[net_col])
        if valid.empty:
            return None
        return valid.iloc[0]

    @staticmethod
    def _format_amount(value) -> str:
        """格式化金额显示"""
        try:
            value = float(value)
            if abs(value) >= 1e8:
                return f"{value / 1e8:.2f}亿元"
            elif abs(value) >= 1e4:
                return f"{value / 1e4:.2f}万元"
            else:
                return f"{value:.2f}元"
        except (ValueError, TypeError):
            return str(value) if value else "N/A"


if __name__ == "__main__":
    nb = NorthboundFlowAkshare()
    df = asyncio.run(nb.get_data("2026-08-08 09:00:00"))
    print(df.head())
    if len(df) > 0:
        print("北向资金分析内容:")
        print(df.content.values[0])
