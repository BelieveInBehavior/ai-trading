"""
融资融券数据源

Alpha 逻辑：
- 融资余额突增（日增幅 > 3%）= 杠杆多头进场，看涨信号
- 融券余额骤降（日降幅 > 10%）= 空头回补，短期看涨
- 融资余额/流通市值比值异常高 = 杠杆过高，需警惕
- 融资连续 N 天增加 = 持续看多共识

数据来源：akshare stock_margin_detail_szse / stock_margin_detail_sse
"""
import pandas as pd
import numpy as np
import asyncio
import traceback
from datetime import datetime, timedelta
from data_source.data_source_base import DataSourceBase
from utils.akshare_utils import akshare_cached
from loguru import logger
from utils.date_utils import (
    get_latest_completed_trading_date,
    get_previous_trading_dates,
    normalize_trade_date_compact,
)
from utils.factor_store import MARGIN_TRADING_STORE
from utils.threshold_manager import THRESHOLD_MANAGER


class MarginTradingAkshare(DataSourceBase):
    def __init__(self):
        super().__init__("margin_trading_akshare")

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        try:
            trade_date = get_latest_completed_trading_date(trigger_time)
            df = self.get_data_cached(trigger_time)
            if df is not None and self.cached_data_has_trade_date(df, trade_date):
                return df

            logger.info(f"获取 {trade_date} 的融资融券数据")

            report = self._build_margin_report(trade_date)

            data = [{
                "title": f"{trade_date}:融资融券异动分析",
                "content": report,
                "pub_time": trigger_time,
                "url": None,
                "market_relevance_score": 7,
                "market_relevance_label": "high",
                "signal_event_type": "margin_trading",
                "signal_direction": "neutral",
                "signal_confidence": 0.65,
            }]
            df = pd.DataFrame(data)
            self.save_data_cached(trigger_time, df)
            return df

        except Exception as e:
            traceback.print_exc()
            logger.error(f"获取融资融券数据失败: {e}")
            return pd.DataFrame()

    def _build_margin_report(self, trade_date: str) -> str:
        """构建融资融券分析报告"""
        sections = [f"## {trade_date} 融资融券异动分析\n"]

        # 获取沪深两市融资融券明细
        sh_df = self._get_margin_detail("sh", trade_date)
        sz_df = self._get_margin_detail("sz", trade_date)

        # 合并
        all_df = pd.concat([sh_df, sz_df], ignore_index=True)
        if all_df.empty:
            return "融资融券数据获取失败"

        # 标准化列名（沪深两市列名可能不同）
        all_df = self._normalize_columns(all_df)

        if '融资余额' not in all_df.columns:
            return "融资融券数据格式异常，缺少融资余额字段"

        # ===== 1. 融资余额大幅增加（杠杆多头进场）=====
        margin_buy_surge = self._find_margin_buy_surge(all_df)
        if not margin_buy_surge.empty:
            sections.append("### 一、融资余额大幅增加（杠杆多头进场）")
            sections.append("逻辑：融资净买入额占比高，表明杠杆资金看多\n")
            for _, row in margin_buy_surge.head(15).iterrows():
                code = row.get('股票代码', row.get('证券代码', ''))
                name = row.get('股票简称', row.get('证券简称', ''))
                rz_balance = row.get('融资余额', 0)
                rz_buy = row.get('融资买入额', 0)
                rz_repay = row.get('融资偿还额', 0)
                rz_net = rz_buy - rz_repay if rz_buy and rz_repay else 0
                sections.append(
                    f"- {name}({code}): "
                    f"融资余额{rz_balance/1e8:.2f}亿, "
                    f"融资净买入{rz_net/1e8:.2f}亿, "
                    f"融资买入{rz_buy/1e8:.2f}亿"
                )

        # ===== 2. 融券余额大幅减少（空头回补）=====
        short_cover = self._find_short_covering(all_df)
        if not short_cover.empty:
            sections.append("\n### 二、融券卖出/偿还异动（空头行为）")
            sections.append("逻辑：融券偿还量显著大于卖出量，空头在回补\n")
            for _, row in short_cover.head(10).iterrows():
                code = row.get('股票代码', row.get('证券代码', ''))
                name = row.get('股票简称', row.get('证券简称', ''))
                rq_balance = row.get('融券余量', 0)
                rq_sell = row.get('融券卖出量', 0)
                rq_repay = row.get('融券偿还量', 0)
                sections.append(
                    f"- {name}({code}): "
                    f"融券余量{rq_balance:.0f}股, "
                    f"融券卖出{rq_sell:.0f}股, "
                    f"融券偿还{rq_repay:.0f}股"
                )

        # ===== 3. 融资净买入额 TOP 排名 =====
        net_buy_top = self._get_net_buy_ranking(all_df)
        if not net_buy_top.empty:
            sections.append("\n### 三、融资净买入额 TOP20")
            sections.append("逻辑：杠杆资金当日净流入最多的标的\n")
            for _, row in net_buy_top.head(20).iterrows():
                code = row.get('股票代码', row.get('证券代码', ''))
                name = row.get('股票简称', row.get('证券简称', ''))
                rz_net = row.get('融资净买入', 0)
                rz_balance = row.get('融资余额', 0)
                sections.append(
                    f"- {name}({code}): "
                    f"融资净买入{rz_net/1e8:.2f}亿, "
                    f"融资余额{rz_balance/1e8:.2f}亿"
                )

        # ===== 4. 融资净卖出额 TOP（杠杆多头出逃）=====
        net_sell_top = self._get_net_sell_ranking(all_df)
        if not net_sell_top.empty:
            sections.append("\n### 四、融资净偿还额 TOP10（杠杆多头出逃）")
            for _, row in net_sell_top.head(10).iterrows():
                code = row.get('股票代码', row.get('证券代码', ''))
                name = row.get('股票简称', row.get('证券简称', ''))
                rz_net = row.get('融资净买入', 0)
                sections.append(
                    f"- {name}({code}): 融资净偿还{abs(rz_net)/1e8:.2f}亿"
                )

        # ===== 5. 市场整体融资融券统计 =====
        sections.append(f"\n### 五、市场融资融券统计摘要")
        total_rz = all_df['融资余额'].sum() if '融资余额' in all_df.columns else 0
        total_buy = all_df['融资买入额'].sum() if '融资买入额' in all_df.columns else 0
        total_repay = all_df['融资偿还额'].sum() if '融资偿还额' in all_df.columns else 0
        total_net = total_buy - total_repay
        net_buy_count = len(all_df[(all_df.get('融资买入额', pd.Series()) - all_df.get('融资偿还额', pd.Series())) > 0]) if '融资买入额' in all_df.columns else 0

        sections.append(f"- 全市场融资余额: {total_rz/1e8:.2f}亿")
        sections.append(f"- 当日融资买入: {total_buy/1e8:.2f}亿")
        sections.append(f"- 当日融资偿还: {total_repay/1e8:.2f}亿")
        sections.append(f"- 当日融资净买入: {total_net/1e8:.2f}亿")
        sections.append(f"- 融资净买入股票数: {net_buy_count}")

        # 保存结构化因子数据
        self._save_structured_factors(all_df, trade_date)

        return "\n".join(sections)

    def _save_structured_factors(self, all_df: pd.DataFrame, trade_date: str):
        """保存结构化因子到 FactorStore"""
        if all_df.empty or '融资买入额' not in all_df.columns:
            return

        records = []
        code_col = '股票代码' if '股票代码' in all_df.columns else '证券代码'
        name_col = '股票简称' if '股票简称' in all_df.columns else '证券简称'

        for _, row in all_df.iterrows():
            code = str(row.get(code_col, ''))
            name = str(row.get(name_col, ''))
            rz_buy = float(row.get('融资买入额', 0))
            rz_repay = float(row.get('融资偿还额', 0))
            rz_net = rz_buy - rz_repay
            rz_balance = float(row.get('融资余额', 0))

            records.append({
                "symbol_code": code.split('.')[0] if '.' in code else code,
                "symbol_name": name,
                "factor_value": rz_net,
                "rz_balance": rz_balance,
                "rz_buy": rz_buy,
                "rz_repay": rz_repay,
                "rq_balance": float(row.get('融券余量', 0)),
            })

        MARGIN_TRADING_STORE.save(records, trade_date)

    def _get_margin_detail(self, market: str, trade_date: str) -> pd.DataFrame:
        """获取沪/深市融资融券明细"""
        try:
            formatted_date = normalize_trade_date_compact(trade_date)

            if market == "sh":
                func_name = "stock_margin_detail_sse"
                kwargs = {"date": formatted_date}
            else:
                func_name = "stock_margin_detail_szse"
                kwargs = {"date": formatted_date}

            df = akshare_cached.run(
                func_name=func_name,
                func_kwargs=kwargs,
                verbose=False
            )

            if df is None or df.empty:
                logger.warning(f"{market}市融资融券明细为空 ({trade_date})")
                return pd.DataFrame()

            df['_market'] = market
            logger.info(f"获取{market}市融资融券明细成功，{len(df)}条")
            return df

        except Exception as e:
            logger.error(f"获取{market}市融资融券明细失败: {e}")
            return pd.DataFrame()

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化列名（沪深两市可能列名不同）"""
        rename_map = {
            '信用交易日期': '交易日期',
            '标的证券代码': '股票代码',
            '标的证券简称': '股票简称',
            '证券代码': '股票代码',
            '证券简称': '股票简称',
        }
        for old, new in rename_map.items():
            if old in df.columns and new not in df.columns:
                df = df.rename(columns={old: new})

        # 确保数值列为数值类型
        numeric_cols = [
            '融资余额', '融资买入额', '融资偿还额',
            '融券余量', '融券卖出量', '融券偿还量', '融券余额',
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        return df

    def _find_margin_buy_surge(self, df: pd.DataFrame) -> pd.DataFrame:
        """找到融资买入激增的股票"""
        if '融资买入额' not in df.columns or '融资偿还额' not in df.columns:
            return pd.DataFrame()

        working = df.copy()
        working['融资净买入'] = working['融资买入额'] - working['融资偿还额']
        # 融资净买入 > 5000万
        mask = working['融资净买入'] > 5e7
        return working[mask].sort_values('融资净买入', ascending=False)

    def _find_short_covering(self, df: pd.DataFrame) -> pd.DataFrame:
        """找到空头回补信号"""
        if '融券偿还量' not in df.columns or '融券卖出量' not in df.columns:
            return pd.DataFrame()

        working = df.copy()
        working['融券净偿还'] = working['融券偿还量'] - working['融券卖出量']
        # 融券偿还量 > 卖出量 * 2，且绝对量有一定规模
        mask = (
            (working['融券净偿还'] > 0)
            & (working['融券偿还量'] > working['融券卖出量'] * 2)
            & (working['融券偿还量'] > 10000)
        )
        return working[mask].sort_values('融券净偿还', ascending=False)

    def _get_net_buy_ranking(self, df: pd.DataFrame) -> pd.DataFrame:
        """融资净买入排名"""
        if '融资买入额' not in df.columns or '融资偿还额' not in df.columns:
            return pd.DataFrame()
        working = df.copy()
        working['融资净买入'] = working['融资买入额'] - working['融资偿还额']
        return working[working['融资净买入'] > 0].sort_values('融资净买入', ascending=False)

    def _get_net_sell_ranking(self, df: pd.DataFrame) -> pd.DataFrame:
        """融资净偿还（净卖出）排名"""
        if '融资买入额' not in df.columns or '融资偿还额' not in df.columns:
            return pd.DataFrame()
        working = df.copy()
        working['融资净买入'] = working['融资买入额'] - working['融资偿还额']
        return working[working['融资净买入'] < 0].sort_values('融资净买入', ascending=True)


if __name__ == "__main__":
    ds = MarginTradingAkshare()
    df = asyncio.run(ds.get_data("2026-08-09 09:00:00"))
    if not df.empty:
        print(df.content.values[0])
    else:
        print("No data returned")
