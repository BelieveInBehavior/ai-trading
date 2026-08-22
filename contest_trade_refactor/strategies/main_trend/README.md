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

## Layer 1 Market Regime（A/B/C/D 七维输入）

指数趋势 / 指数动量 / 市场广度 / 新高-新低 / 市场成交额 / 板块广度 / 市场波动

- A/B: allow_new=True, risk_multiplier=1.0
- C: allow_new=True, risk_multiplier=0.5
- D: allow_new=False, risk_multiplier=0.0

对应实现：`engine.evaluate_market_regime()`。

## Layer 2 Trend State（S0~S5 主升浪状态机）

- S0 Base Preparation：尚未形成有效主升浪，PASS。
- S1 Breakout / Launch：平台突破 + 量扩张 + 短期均线转强 + RS增强；价格站上关键成本区（筹码/成本仅辅助加分，不硬条件）。
- S2 Acceleration：创新高 + RS强 + 量价健康 + MA多头（MA5>MA20>MA60），允许正常建仓和加仓。
- S3 Continuation / Consolidation：涨后盘整、缩量、MA20继续上行、重新突破；不因未创新高判死。
- S4 Exhaustion：主升末端，不预测顶部，只记录趋势质量下降维度（创新高减速 / RS 回调 / ATR 异常 / 量异常 / 板块转弱）风险预警，不新增。
- S5 Trend Breakdown：趋势破坏硬退出，Close<MA20+RSI 弱；ATR Trailing Stop / 次日无法站回在持仓状态机处理。

对应实现：`engine.assess_trend_state()`。

## T 日硬过滤（最终 8 条）

| # | 硬过滤 | 条件 |
|---|---|---|
| 1 | Market Regime | Regime != D |
| 2 | 交易状态 | 非 ST / 非停牌 / 非退市整理 |
| 3 | 上市时间 | TradingDays >= 120 |
| 4 | 流动性 | 20D Median Turnover >= 全市场横截面 P20 |
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

