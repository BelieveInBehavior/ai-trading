"""
大宗交易数据源

Alpha 逻辑：
- 溢价成交（成交价 > 收盘价）= 机构急于买入，看好后市
- 连续折价成交 = 大股东/机构出货，后市看跌
- 折价率极低（< -5%）+ 成交量大 = 抛压最后一波，可能见底
- 多笔溢价买入集中在同一标的 = 强烈看多信号

数据来源：akshare stock_dzjy_mrtj（大宗交易每日统计）
"""
import pandas as pd
import numpy as np
import asyncio
import traceback
from datetime import datetime
from data_source.data_source_base import DataSourceBase
from utils.akshare_utils import akshare_cached
from loguru import logger
from utils.date_utils import (
    get_latest_completed_trading_date,
    get_trading_date_range,
    normalize_trade_date_compact,
)
from utils.factor_store import BLOCK_TRADE_STORE


class BlockTradeAkshare(DataSourceBase):
    def __init__(self):
        super().__init__("block_trade_akshare")

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        try:
            trade_date = get_latest_completed_trading_date(trigger_time)
            df = self.get_data_cached(trigger_time)
            if df is not None and self.cached_data_has_trade_date(df, trade_date):
                return df

            logger.info(f"获取 {trade_date} 的大宗交易数据")

            report = self._build_block_trade_report(trade_date)

            data = [{
                "title": f"{trade_date}:大宗交易折溢价分析",
                "content": report,
                "pub_time": trigger_time,
                "url": None,
                "market_relevance_score": 7,
                "market_relevance_label": "high",
                "signal_event_type": "block_trade",
                "signal_direction": "neutral",
                "signal_confidence": 0.6,
            }]
            df = pd.DataFrame(data)
            self.save_data_cached(trigger_time, df)
            return df

        except Exception as e:
            traceback.print_exc()
            logger.error(f"获取大宗交易数据失败: {e}")
            return pd.DataFrame()

    def _build_block_trade_report(self, trade_date: str) -> str:
        """构建大宗交易分析报告"""
        sections = [f"## {trade_date} 大宗交易折溢价分析\n"]

        # 获取当日大宗交易数据
        daily_df = self._get_daily_summary(trade_date)

        # 获取近5个交易日的大宗交易（用于连续性分析）
        start_date, end_date = get_trading_date_range(trade_date, count=5, include_end=True)
        detail_df = self._get_detail_data(start_date, end_date)

        if daily_df.empty and detail_df.empty:
            return "大宗交易数据获取失败"

        working_df = daily_df if not daily_df.empty else detail_df

        # ===== 1. 溢价成交（机构抢筹）=====
        premium = self._find_premium_trades(working_df)
        if not premium.empty:
            sections.append("### 一、溢价成交（机构抢筹信号）")
            sections.append("逻辑：成交价高于收盘价，买方愿意付出溢价，极度看好\n")
            for _, row in premium.head(15).iterrows():
                sections.append(self._format_trade_row(row, highlight="premium"))

        # ===== 2. 大幅折价成交（出货信号）=====
        discount = self._find_deep_discount_trades(working_df)
        if not discount.empty:
            sections.append("\n### 二、大幅折价成交（出货警告）")
            sections.append("逻辑：折价超过5%，卖方急于出手，后续可能继续承压\n")
            for _, row in discount.head(10).iterrows():
                sections.append(self._format_trade_row(row, highlight="discount"))

        # ===== 3. 成交金额巨大（机构级别）=====
        large_amount = self._find_large_amount_trades(working_df)
        if not large_amount.empty:
            sections.append("\n### 三、大额成交（> 1亿元）")
            sections.append("逻辑：大宗交易金额巨大，通常为机构间转让或战略布局\n")
            for _, row in large_amount.head(15).iterrows():
                sections.append(self._format_trade_row(row, highlight="amount"))

        # ===== 4. 同一标的多笔买入（集中看多）=====
        concentrated = self._find_concentrated_buying(working_df)
        if not concentrated.empty:
            sections.append("\n### 四、同一标的多笔大宗买入（集中看多）")
            sections.append("逻辑：多个买方同日通过大宗交易买入同一标的\n")
            for _, row in concentrated.head(10).iterrows():
                code = row.get('证券代码', row.get('代码', ''))
                name = row.get('证券简称', row.get('名称', ''))
                count = row.get('成交笔数', 0)
                total = row.get('总成交额', 0)
                avg_premium = row.get('平均溢折率', 0)
                sections.append(
                    f"- {name}({code}): "
                    f"成交{count}笔, "
                    f"合计{total/1e8:.2f}亿, "
                    f"平均溢折率{avg_premium:+.2f}%"
                )

        # ===== 5. 近5日连续出现大宗交易的标的 =====
        if not detail_df.empty:
            consecutive = self._find_consecutive_trades(detail_df)
            if not consecutive.empty:
                sections.append("\n### 五、近5日连续大宗交易标的")
                sections.append("逻辑：连续出现大宗交易，可能有系统性建仓或出货行为\n")
                for _, row in consecutive.head(10).iterrows():
                    code = row.get('证券代码', row.get('代码', ''))
                    name = row.get('证券简称', row.get('名称', ''))
                    days = row.get('出现天数', 0)
                    total = row.get('总成交额', 0)
                    avg_premium = row.get('平均溢折率', 0)
                    sections.append(
                        f"- {name}({code}): "
                        f"近5日出现{days}天, "
                        f"合计{total/1e8:.2f}亿, "
                        f"平均溢折率{avg_premium:+.2f}%"
                    )

        # ===== 6. 统计摘要 =====
        sections.append(f"\n### 六、大宗交易市场统计")
        if not working_df.empty:
            total_amount = self._safe_sum(working_df, '成交总额', '成交金额')
            total_count = len(working_df)
            premium_count = len(premium) if not premium.empty else 0
            discount_count = len(discount) if not discount.empty else 0
            sections.append(f"- 当日大宗交易笔数: {total_count}")
            sections.append(f"- 当日大宗交易总额: {total_amount/1e8:.2f}亿")
            sections.append(f"- 溢价成交笔数: {premium_count}")
            sections.append(f"- 深度折价成交笔数: {discount_count}")

        # 保存结构化因子数据
        self._save_structured_factors(working_df, trade_date)

        return "\n".join(sections)

    def _save_structured_factors(self, df: pd.DataFrame, trade_date: str):
        """保存结构化因子到 FactorStore"""
        if df.empty:
            return

        records = []
        for _, row in df.iterrows():
            code_col = self._find_code_col(df)
            name_col = self._find_name_col(df)
            code = str(row.get(code_col, '')) if code_col else ''
            name = str(row.get(name_col, '')) if name_col else ''
            premium = self._get_premium_rate(row)
            amount_col = self._find_amount_col(df)
            amount = float(pd.to_numeric(row.get(amount_col, 0), errors='coerce')) if amount_col else 0

            records.append({
                "symbol_code": code.split('.')[0] if '.' in code else code,
                "symbol_name": name,
                "factor_value": premium,  # 溢折率作为因子值
                "amount": amount,
            })

        BLOCK_TRADE_STORE.save(records, trade_date)

    def _get_daily_summary(self, trade_date: str) -> pd.DataFrame:
        """获取大宗交易每日统计"""
        try:
            formatted_date = normalize_trade_date_compact(trade_date)
            df = akshare_cached.run(
                func_name="stock_dzjy_mrtj",
                func_kwargs={"start_date": formatted_date, "end_date": formatted_date},
                verbose=False
            )
            if df is None or df.empty:
                logger.warning(f"大宗交易每日统计为空 ({trade_date})")
                return pd.DataFrame()
            logger.info(f"获取大宗交易每日统计成功，{len(df)}条")
            return df
        except Exception as e:
            logger.error(f"获取大宗交易每日统计失败: {e}")
            return pd.DataFrame()

    def _get_detail_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        """获取大宗交易明细数据"""
        try:
            s = normalize_trade_date_compact(start_date)
            e = normalize_trade_date_compact(end_date)
            df = akshare_cached.run(
                func_name="stock_dzjy_mrmx",
                func_kwargs={"start_date": s, "end_date": e},
                verbose=False
            )
            if df is None or df.empty:
                return pd.DataFrame()
            logger.info(f"获取大宗交易明细成功，{len(df)}条")
            return df
        except Exception as e:
            logger.error(f"获取大宗交易明细失败: {e}")
            return pd.DataFrame()

    def _get_premium_rate(self, row) -> float:
        """获取溢折率"""
        # 不同 akshare 版本可能列名不同
        for col in ['折溢率', '溢折率', '折溢价率', '溢价率']:
            if col in row.index:
                val = pd.to_numeric(row[col], errors='coerce')
                if not np.isnan(val):
                    return val
        # 自行计算
        price_col = None
        close_col = None
        for c in ['成交价', '成交均价']:
            if c in row.index:
                price_col = c
                break
        for c in ['收盘价', '前收盘价']:
            if c in row.index:
                close_col = c
                break
        if price_col and close_col:
            price = pd.to_numeric(row[price_col], errors='coerce')
            close = pd.to_numeric(row[close_col], errors='coerce')
            if close > 0 and not np.isnan(price):
                return (price - close) / close * 100
        return 0.0

    def _find_premium_trades(self, df: pd.DataFrame) -> pd.DataFrame:
        """找到溢价成交的大宗交易"""
        if df.empty:
            return pd.DataFrame()
        working = df.copy()
        working['_premium_rate'] = working.apply(self._get_premium_rate, axis=1)
        mask = working['_premium_rate'] > 0
        return working[mask].sort_values('_premium_rate', ascending=False)

    def _find_deep_discount_trades(self, df: pd.DataFrame) -> pd.DataFrame:
        """找到深度折价成交"""
        if df.empty:
            return pd.DataFrame()
        working = df.copy()
        working['_premium_rate'] = working.apply(self._get_premium_rate, axis=1)
        mask = working['_premium_rate'] < -5.0
        return working[mask].sort_values('_premium_rate', ascending=True)

    def _find_large_amount_trades(self, df: pd.DataFrame) -> pd.DataFrame:
        """找到大额成交"""
        if df.empty:
            return pd.DataFrame()
        working = df.copy()
        amount_col = self._find_amount_col(working)
        if not amount_col:
            return pd.DataFrame()
        working[amount_col] = pd.to_numeric(working[amount_col], errors='coerce')
        mask = working[amount_col] > 1e8  # > 1亿
        return working[mask].sort_values(amount_col, ascending=False)

    def _find_concentrated_buying(self, df: pd.DataFrame) -> pd.DataFrame:
        """找到同一标的多笔买入"""
        if df.empty:
            return pd.DataFrame()
        code_col = self._find_code_col(df)
        name_col = self._find_name_col(df)
        amount_col = self._find_amount_col(df)
        if not code_col:
            return pd.DataFrame()

        working = df.copy()
        if amount_col:
            working[amount_col] = pd.to_numeric(working[amount_col], errors='coerce')

        working['_premium_rate'] = working.apply(self._get_premium_rate, axis=1)

        grouped = working.groupby(code_col).agg(
            成交笔数=(code_col, 'count'),
            总成交额=(amount_col, 'sum') if amount_col else (code_col, 'count'),
            平均溢折率=('_premium_rate', 'mean'),
        ).reset_index()

        if name_col and name_col in working.columns:
            name_map = working.drop_duplicates(code_col).set_index(code_col)[name_col]
            grouped[name_col] = grouped[code_col].map(name_map)

        # 同一标的 >= 3 笔
        mask = grouped['成交笔数'] >= 3
        result = grouped[mask].sort_values('成交笔数', ascending=False)

        # Rename for consistent output
        result = result.rename(columns={code_col: '证券代码'})
        if name_col:
            result = result.rename(columns={name_col: '证券简称'})
        return result

    def _find_consecutive_trades(self, df: pd.DataFrame) -> pd.DataFrame:
        """找到近5日连续出现大宗交易的标的"""
        if df.empty:
            return pd.DataFrame()
        code_col = self._find_code_col(df)
        name_col = self._find_name_col(df)
        date_col = self._find_date_col(df)
        amount_col = self._find_amount_col(df)
        if not code_col or not date_col:
            return pd.DataFrame()

        working = df.copy()
        if amount_col:
            working[amount_col] = pd.to_numeric(working[amount_col], errors='coerce')
        working['_premium_rate'] = working.apply(self._get_premium_rate, axis=1)

        agg_dict = {
            '出现天数': (date_col, 'nunique'),
            '平均溢折率': ('_premium_rate', 'mean'),
        }
        if amount_col:
            agg_dict['总成交额'] = (amount_col, 'sum')

        grouped = working.groupby(code_col).agg(**agg_dict).reset_index()

        if name_col and name_col in working.columns:
            name_map = working.drop_duplicates(code_col).set_index(code_col)[name_col]
            grouped[name_col] = grouped[code_col].map(name_map)

        mask = grouped['出现天数'] >= 3
        result = grouped[mask].sort_values('出现天数', ascending=False)
        result = result.rename(columns={code_col: '证券代码'})
        if name_col:
            result = result.rename(columns={name_col: '证券简称'})
        return result

    def _format_trade_row(self, row, highlight: str = "") -> str:
        """格式化单条大宗交易记录"""
        code = row.get('证券代码', row.get('代码', row.get('股票代码', '')))
        name = row.get('证券简称', row.get('名称', row.get('股票简称', '')))
        amount_col = None
        for col in ['成交总额', '成交金额', '成交额']:
            if col in row.index:
                amount_col = col
                break
        amount = pd.to_numeric(row.get(amount_col, 0), errors='coerce') if amount_col else 0
        premium = row.get('_premium_rate', 0)

        parts = [f"- {name}({code}):"]
        if highlight == "premium":
            parts.append(f"溢价率{premium:+.2f}%")
        elif highlight == "discount":
            parts.append(f"折价率{premium:.2f}%")
        if amount:
            parts.append(f"成交额{amount/1e8:.2f}亿")

        for col in ['成交价', '成交均价']:
            if col in row.index:
                parts.append(f"成交价{row[col]}")
                break
        return " ".join(parts)

    def _find_code_col(self, df: pd.DataFrame) -> str:
        for col in ['证券代码', '代码', '股票代码']:
            if col in df.columns:
                return col
        return ""

    def _find_name_col(self, df: pd.DataFrame) -> str:
        for col in ['证券简称', '名称', '股票简称']:
            if col in df.columns:
                return col
        return ""

    def _find_date_col(self, df: pd.DataFrame) -> str:
        for col in ['交易日期', '日期', '成交日期']:
            if col in df.columns:
                return col
        return ""

    def _find_amount_col(self, df: pd.DataFrame) -> str:
        for col in ['成交总额', '成交金额', '成交额']:
            if col in df.columns:
                return col
        return ""

    def _safe_sum(self, df: pd.DataFrame, *cols) -> float:
        for col in cols:
            if col in df.columns:
                return pd.to_numeric(df[col], errors='coerce').sum()
        return 0.0


if __name__ == "__main__":
    ds = BlockTradeAkshare()
    df = asyncio.run(ds.get_data("2026-08-09 09:00:00"))
    if not df.empty:
        print(df.content.values[0])
    else:
        print("No data returned")
