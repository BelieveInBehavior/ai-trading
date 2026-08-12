"""
涨停封单强度数据源（增强版）

Alpha 逻辑：
- 封单量/流通盘 > 5% = 封单极强，次日大概率高开或继续涨停
- 封单量/流通盘 在 2%-5% = 中等强度，有一定次日溢价
- 首次涨停且封单强 + 连板股 = 短线接力机会
- 尾盘封单减少（炸板后回封） = 分歧后一致，次日看高一线
- 涨停原因为事件催化（政策/业绩）vs 纯情绪（跟风）的区分

增强点：在现有 hot_money_akshare 的涨停数据基础上，加入封单量化分析
数据来源：akshare stock_zt_pool_em（涨停池）
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
from utils.factor_store import ZT_SEAL_STORE


class ZtSealStrengthAkshare(DataSourceBase):
    def __init__(self):
        super().__init__("zt_seal_strength_akshare")

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        try:
            trade_date = get_latest_completed_trading_date(trigger_time)
            df = self.get_data_cached(trigger_time)
            if df is not None and self.cached_data_has_trade_date(df, trade_date):
                return df

            logger.info(f"获取 {trade_date} 的涨停封单强度数据")

            report = self._build_zt_strength_report(trade_date)

            data = [{
                "title": f"{trade_date}:涨停封单强度分析",
                "content": report,
                "pub_time": trigger_time,
                "url": None,
                "market_relevance_score": 9,
                "market_relevance_label": "high",
                "signal_event_type": "limit_up",
                "signal_direction": "bullish",
                "signal_confidence": 0.7,
            }]
            df = pd.DataFrame(data)
            self.save_data_cached(trigger_time, df)
            return df

        except Exception as e:
            traceback.print_exc()
            logger.error(f"获取涨停封单强度数据失败: {e}")
            return pd.DataFrame()

    def _build_zt_strength_report(self, trade_date: str) -> str:
        """构建涨停封单强度分析报告"""
        sections = [f"## {trade_date} 涨停封单强度分析\n"]

        # 获取涨停池数据
        zt_df = self._get_zt_pool(trade_date)
        if zt_df.empty:
            return "涨停池数据获取失败"

        # 计算封单强度
        zt_df = self._compute_seal_strength(zt_df)

        # ===== 1. 封单极强（封单量/流通盘 > 5%）=====
        ultra_strong = zt_df[zt_df['封单强度'] > 5.0].sort_values('封单强度', ascending=False)
        if not ultra_strong.empty:
            sections.append("### 一、封单极强（封单占流通盘 > 5%）")
            sections.append("逻辑：极强封单表明多方高度一致看多，次日大概率高开或一字板\n")
            for _, row in ultra_strong.head(15).iterrows():
                sections.append(self._format_zt_row(row))

        # ===== 2. 封单较强（2% - 5%）=====
        strong = zt_df[(zt_df['封单强度'] >= 2.0) & (zt_df['封单强度'] <= 5.0)]
        strong = strong.sort_values('封单强度', ascending=False)
        if not strong.empty:
            sections.append("\n### 二、封单较强（封单占流通盘 2%-5%）")
            sections.append("逻辑：封单较强但未达极致，次日有溢价但需关注开盘竞价\n")
            for _, row in strong.head(15).iterrows():
                sections.append(self._format_zt_row(row))

        # ===== 3. 连板股封单分析 =====
        continuous = zt_df[zt_df['连板数'] >= 2].sort_values('连板数', ascending=False)
        if not continuous.empty:
            sections.append("\n### 三、连板股封单情况")
            sections.append("逻辑：连板股封单强度决定是否能继续打板\n")
            for _, row in continuous.head(15).iterrows():
                sections.append(self._format_zt_row(row, show_continuous=True))

        # ===== 4. 首板强封单（新龙头候选）=====
        first_board_strong = zt_df[
            (zt_df['连板数'] == 1) & (zt_df['封单强度'] > 3.0)
        ].sort_values('封单强度', ascending=False)
        if not first_board_strong.empty:
            sections.append("\n### 四、首板强封单（新龙头候选）")
            sections.append("逻辑：首次涨停即获得超强封单，可能是新题材龙头\n")
            for _, row in first_board_strong.head(10).iterrows():
                sections.append(self._format_zt_row(row))

        # ===== 5. 炸板回封（分歧一致信号）=====
        resealed = zt_df[zt_df['炸板次数'] > 0].sort_values('封单强度', ascending=False)
        if not resealed.empty:
            sections.append("\n### 五、炸板回封（分歧后一致）")
            sections.append("逻辑：日内多次打开涨停后回封，分歧后达成一致，次日看高一线\n")
            for _, row in resealed.head(10).iterrows():
                sections.append(self._format_zt_row(row, show_break=True))

        # ===== 6. 封单偏弱（可能次日低开）=====
        weak = zt_df[zt_df['封单强度'] < 1.0].sort_values('封单强度', ascending=True)
        if not weak.empty:
            sections.append("\n### 六、封单偏弱（次日低开风险）")
            sections.append("逻辑：封单不足流通盘1%，次日竞价可能被砸开\n")
            for _, row in weak.head(10).iterrows():
                sections.append(self._format_zt_row(row))

        # ===== 7. 统计摘要 =====
        sections.append(f"\n### 七、涨停封单统计摘要")
        total_zt = len(zt_df)
        ultra_count = len(ultra_strong) if not ultra_strong.empty else 0
        strong_count = len(strong) if not strong.empty else 0
        weak_count = len(weak) if not weak.empty else 0
        continuous_count = len(continuous) if not continuous.empty else 0
        avg_strength = zt_df['封单强度'].mean() if '封单强度' in zt_df.columns else 0

        sections.append(f"- 涨停总数: {total_zt}")
        sections.append(f"- 封单极强(>5%): {ultra_count}")
        sections.append(f"- 封单较强(2-5%): {strong_count}")
        sections.append(f"- 封单偏弱(<1%): {weak_count}")
        sections.append(f"- 连板股数量: {continuous_count}")
        sections.append(f"- 平均封单强度: {avg_strength:.2f}%")

        # 连板高度
        if not continuous.empty:
            max_board = continuous['连板数'].max()
            sections.append(f"- 当日最高连板: {max_board}板")

        # 保存结构化因子数据
        self._save_structured_factors(zt_df, trade_date)

        return "\n".join(sections)

    def _save_structured_factors(self, zt_df: pd.DataFrame, trade_date: str):
        """保存结构化因子到 FactorStore"""
        if zt_df.empty or '封单强度' not in zt_df.columns:
            return

        records = []
        for _, row in zt_df.iterrows():
            code = str(row.get('代码', '')).zfill(6)
            name = str(row.get('名称', ''))
            strength = float(row.get('封单强度', 0))
            continuous = int(row.get('连板数', 1))
            break_count = int(row.get('炸板次数', 0))
            seal_amount = float(row.get('封单额', 0))

            records.append({
                "symbol_code": code,
                "symbol_name": name,
                "factor_value": strength,
                "continuous_board": continuous,
                "break_count": break_count,
                "seal_amount": seal_amount,
                "turnover": float(row.get('换手率', 0)),
            })

        ZT_SEAL_STORE.save(records, trade_date)

    def _get_zt_pool(self, trade_date: str) -> pd.DataFrame:
        """获取涨停池数据"""
        try:
            df = akshare_cached.run(
                func_name="stock_zt_pool_em",
                func_kwargs={"date": trade_date},
                verbose=False
            )
            if df is None or df.empty:
                logger.warning(f"{trade_date} 无涨停数据")
                return pd.DataFrame()
            logger.info(f"获取涨停池成功，{len(df)}条")
            return df
        except Exception as e:
            logger.error(f"获取涨停池失败: {e}")
            return pd.DataFrame()

    def _compute_seal_strength(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算封单强度 = 封单额 / 流通市值 * 100"""
        working = df.copy()

        # 确保关键列存在且为数值
        for col in ['封单额', '流通市值']:
            if col in working.columns:
                working[col] = pd.to_numeric(working[col], errors='coerce').fillna(0)
            else:
                working[col] = 0

        # 封单强度 = 封单额 / 流通市值 * 100 (百分比)
        working['封单强度'] = np.where(
            working['流通市值'] > 0,
            working['封单额'] / working['流通市值'] * 100,
            0.0
        )

        # 连板数确保为数值
        if '连板数' in working.columns:
            working['连板数'] = pd.to_numeric(working['连板数'], errors='coerce').fillna(1).astype(int)
        else:
            working['连板数'] = 1

        # 炸板次数
        if '炸板次数' in working.columns:
            working['炸板次数'] = pd.to_numeric(working['炸板次数'], errors='coerce').fillna(0).astype(int)
        else:
            working['炸板次数'] = 0

        return working

    def _format_zt_row(self, row, show_continuous=False, show_break=False) -> str:
        """格式化涨停个股信息"""
        name = row.get('名称', '')
        code = row.get('代码', '')
        strength = row.get('封单强度', 0)
        seal_amount = row.get('封单额', 0)
        change_pct = row.get('涨跌幅', 0)
        continuous = row.get('连板数', 1)
        break_count = row.get('炸板次数', 0)
        turnover = row.get('换手率', 0)

        parts = [
            f"- {name}({code}): "
            f"封单强度{strength:.2f}%, "
            f"封单额{seal_amount/1e8:.2f}亿"
        ]

        if show_continuous:
            parts.append(f"连板{continuous}")
        elif continuous > 1:
            parts.append(f"{continuous}板")

        if show_break:
            parts.append(f"炸板{break_count}次")

        if turnover:
            parts.append(f"换手{turnover:.1f}%")

        return ", ".join(parts)


if __name__ == "__main__":
    ds = ZtSealStrengthAkshare()
    df = asyncio.run(ds.get_data("2026-08-09 09:00:00"))
    if not df.empty:
        print(df.content.values[0])
    else:
        print("No data returned")
