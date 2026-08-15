"""
结构化因子存储

每次数据源运行后，将关键的结构化信号（股票代码、因子值、日期）
存储到 CSV/Parquet 文件，供回测框架直接读取。

存储结构：
  agents_workspace/factor_store/{factor_name}/{date}.csv

每个 CSV 的标准列：
  symbol_code, symbol_name, factor_date, factor_value, metadata_json
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

from loguru import logger
from config.config import WORKSPACE_ROOT


FACTOR_STORE_DIR = WORKSPACE_ROOT / "factor_store"


class FactorStore:
    """结构化因子持久化存储"""

    def __init__(self, factor_name: str):
        self.factor_name = factor_name
        self.store_dir = FACTOR_STORE_DIR / factor_name
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def save(self, records: List[Dict[str, Any]], factor_date: str):
        """
        保存一批因子记录。

        Args:
            records: 列表，每条记录至少包含 symbol_code, symbol_name, factor_value
            factor_date: 因子日期 YYYYMMDD
        """
        if not records:
            return

        rows = []
        for r in records:
            rows.append({
                "symbol_code": r.get("symbol_code", ""),
                "symbol_name": r.get("symbol_name", ""),
                "factor_date": factor_date,
                "factor_value": r.get("factor_value", 0.0),
                "metadata_json": json.dumps(
                    {k: v for k, v in r.items() if k not in ("symbol_code", "symbol_name", "factor_value")},
                    ensure_ascii=False,
                ),
            })

        df = pd.DataFrame(rows)
        filepath = self.store_dir / f"{factor_date}.csv"
        df.to_csv(filepath, index=False, encoding="utf-8")
        logger.info(f"[FactorStore] 保存 {self.factor_name} @ {factor_date}: {len(rows)} 条")

    def load(self, factor_date: str) -> pd.DataFrame:
        """加载某天的因子数据"""
        filepath = self.store_dir / f"{factor_date}.csv"
        if not filepath.exists():
            return pd.DataFrame()
        return pd.read_csv(filepath, encoding="utf-8")

    def load_range(self, start_date: str, end_date: str) -> pd.DataFrame:
        """加载日期范围内所有因子数据"""
        all_dfs = []
        for filepath in sorted(self.store_dir.glob("*.csv")):
            date_str = filepath.stem  # YYYYMMDD
            if start_date <= date_str <= end_date:
                try:
                    df = pd.read_csv(filepath, encoding="utf-8")
                    all_dfs.append(df)
                except Exception as e:
                    logger.warning(f"加载 {filepath} 失败: {e}")

        if not all_dfs:
            return pd.DataFrame()
        return pd.concat(all_dfs, ignore_index=True)

    def load_all(self) -> pd.DataFrame:
        """加载全部历史因子数据"""
        all_dfs = []
        for filepath in sorted(self.store_dir.glob("*.csv")):
            try:
                df = pd.read_csv(filepath, encoding="utf-8")
                all_dfs.append(df)
            except Exception as e:
                logger.warning(f"加载 {filepath} 失败: {e}")

        if not all_dfs:
            return pd.DataFrame()
        return pd.concat(all_dfs, ignore_index=True)

    def get_available_dates(self) -> List[str]:
        """获取所有可用日期"""
        return sorted([f.stem for f in self.store_dir.glob("*.csv")])

    def get_stats(self) -> Dict[str, Any]:
        """获取存储统计"""
        dates = self.get_available_dates()
        return {
            "factor_name": self.factor_name,
            "total_dates": len(dates),
            "date_range": f"{dates[0]} ~ {dates[-1]}" if dates else "N/A",
            "store_path": str(self.store_dir),
        }


# ===== 全局因子存储实例 =====

FUND_FLOW_STORE = FactorStore("individual_fund_flow")
MARGIN_TRADING_STORE = FactorStore("margin_trading")
BLOCK_TRADE_STORE = FactorStore("block_trade")
SECTOR_FLOW_STORE = FactorStore("sector_fund_flow")
ZT_SEAL_STORE = FactorStore("zt_seal_strength")


def get_all_stores() -> Dict[str, FactorStore]:
    """获取所有因子存储实例"""
    return {
        "individual_fund_flow": FUND_FLOW_STORE,
        "margin_trading": MARGIN_TRADING_STORE,
        "block_trade": BLOCK_TRADE_STORE,
        "sector_fund_flow": SECTOR_FLOW_STORE,
        "zt_seal_strength": ZT_SEAL_STORE,
    }


def print_store_summary():
    """打印所有因子存储的摘要"""
    stores = get_all_stores()
    print("=" * 60)
    print("因子存储摘要")
    print("=" * 60)
    for name, store in stores.items():
        stats = store.get_stats()
        print(f"  {name}: {stats['total_dates']} 天 ({stats['date_range']})")
    print("=" * 60)


if __name__ == "__main__":
    print_store_summary()
