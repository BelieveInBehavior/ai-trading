# 主升浪趋势跟踪系统（Main Trend Following Engine / MTF）

策略包：`strategies/main_trend/`。

## 架构（对应 README 文档）
Layer 0 DataQuality（硬过滤）
-> Layer 1 MarketRegime（A/B/C/D）
-> Layer 2 TrendState（S0~S5，S1/S2/S3 才可新增候选）
-> Layer 3 TrendQuality（A/B/C）
-> Layer 4 SectorState（Ex-Self）
-> Layer 5 CatalystState
-> T+1 ExecutionState（Gap/Auction/Index/Sector/VWAP/Flow）
-> Layer 6 RiskState（风险预算）
-> Layer 7 PositionStateMachine（HOLD/ADD/DECAY/REDUCE/EXIT）

## LLM 边界
LLM 只做新闻解析 / 事件分类 / 异常解释，输出结构化变量。
Engine 是确定性引擎，决定是否买、买多少、何时止损/退出。

## 运行
```bash
.venv/bin/python scripts/main_trend_backtest.py --date 2026-08-18 --symbols-limit 200
.venv/bin/python scripts/main_trend_backtest.py --start 2026-06-01 --end 2026-08-18
.venv/bin/python scripts/strategy_backtest.py --strategy main_trend --run-replay
```

## T 日硬过滤（最终 8 条）

| # | 硬过滤 | 条件 |
|---|---|---|
| 1 | Market Regime | Regime != D |
| 2 | 交易状态 | 非 ST / 非停牌 / 非退市整理 |
| 3 | 上市时间 | TradingDays >= 120 |
| 4 | 流动性 | 20D Median Turnover >= 全市场 P20 |
| 5 | 价格生命线 | Close > MA20 |
| 6 | 趋势结构 | MA20 > MA60 |
| 7 | MA60 方向 | 5日线性回归标准化斜率 > 0 |
| 8 | Trend State | S1 / S2 / S3 |

对应实现：`engine.apply_hard_filter()`。

T 日公式：
```text
T日硬过滤 = Market AND TradingStatus AND History AND Liquidity AND Close>MA20
          AND MA20>MA60 AND MA60Slope>0 AND TrendState∈{S1,S2,S3}
```

## 当前验证（示例）

2026-08-18，`symbols_limit=50`：

```text
universe      : 50
candidates    : 19   (pre hard-filter + TrendState S1/S2/S3)
eligible      : 4    (after 8-item T-day hard filter)
buy_ready     : 1    (after execution scoring)
```
