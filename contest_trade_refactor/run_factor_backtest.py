"""
一键因子回测入口

使用方式：
    .venv/bin/python run_factor_backtest.py

功能：
- 读取 factor_store 中所有积累的历史因子数据
- 对每个因子跑 T+1/T+3/T+5 前向收益回测
- 输出 IC 值、分组收益、胜率等统计
- 生成 markdown 报告

需要至少积累 3-5 天数据后再运行才有意义。
"""

import sys
from pathlib import Path
from tools.factor_backtest import FactorBacktester, FactorRecord
from utils.factor_store import get_all_stores, print_store_summary


def main():
    print("=" * 60)
    print("因子回测系统")
    print("=" * 60)
    print()

    # 显示当前存储状态
    print_store_summary()
    print()

    stores = get_all_stores()
    backtester = FactorBacktester(horizons=[1, 3, 5])

    has_data = False
    for factor_name, store in stores.items():
        dates = store.get_available_dates()
        if not dates:
            print(f"[{factor_name}] 无数据，跳过")
            continue

        has_data = True
        print(f"\n{'='*60}")
        print(f"正在回测: {factor_name} ({len(dates)} 天数据)")
        print(f"{'='*60}")

        # 加载全部历史数据
        all_data = store.load_all()
        if all_data.empty:
            print(f"  数据加载失败，跳过")
            continue

        # 转为 FactorRecord
        records = []
        for _, row in all_data.iterrows():
            code = str(row.get("symbol_code", ""))
            # 跳过非股票代码（如板块名称）
            if not code.isdigit() or len(code) != 6:
                continue
            records.append(FactorRecord(
                symbol_code=code,
                symbol_name=str(row.get("symbol_name", "")),
                factor_date=str(row.get("factor_date", "")),
                factor_name=factor_name,
                factor_value=float(row.get("factor_value", 0)),
            ))

        if not records:
            print(f"  无有效因子记录，跳过")
            continue

        print(f"  共 {len(records)} 条因子记录")

        # 运行回测
        result = backtester.run(records, factor_name)

        # 生成并打印报告
        report = backtester.generate_report(result)
        print(report)

    if not has_data:
        print()
        print("=" * 60)
        print("提示：还没有积累任何历史因子数据。")
        print()
        print("请先运行主系统 1 次以上来采集数据：")
        print("  .venv/bin/python main_loop.py")
        print()
        print("每次运行都会自动将结构化因子存储到:")
        print("  agents_workspace/factor_store/{因子名}/{日期}.csv")
        print()
        print("积累 3-5 天数据后再运行本回测脚本即可获得有效结果。")
        print("=" * 60)


if __name__ == "__main__":
    main()
