# Main Trend Following 主升浪趋势跟踪

独立策略包，不依赖旧 momentum/swing / Research Agent 链路。

## 架构
Layer 0 DataQuality（硬过滤）
-> Layer 1 MarketRegime（A/B/C/D）
-> Layer 2 TrendState（S0~S5，S1/S2/S3 才可新增候选）
-> Layer 3 TrendQuality（A/B/C）
-> Layer 4 SectorState（Ex-Self）
-> Layer 5 CatalystState
-> T+1 ExecutionState（Gap/Auction/Index/Sector/VWAP/Flow）
-> Layer 6 RiskState（风险预算）
-> Layer 7 PositionStateMachine（HOLD/ADD/DECAY/REDUCE/EXIT）

## 运行
```bash
.venv/bin/python scripts/main_trend_backtest.py --start 2026-06-01 --end 2026-08-18 --symbols-limit 200
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
| 7 | MA60 方向 | 5日 LR slope > 0 |
| 8 | Trend State | S1 / S2 / S3 |

对应实现: `engine.apply_hard_filter()`

