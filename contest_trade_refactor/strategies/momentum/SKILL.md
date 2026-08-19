# Momentum 策略

适用于短线 1~3 日、强势主线 / 资金动量交易。

## 调整入口
- `strategy.yaml`：筛选 / 排名 / 研究轮次 / 生命周期门控参数。
- `beliefs.yaml`：研究 Agent 的信念。
- `tools.yaml`：研究 Agent 可用工具。
- `backtest` 段：回测默认区间 / horizons / 是否只跑规则链路。

## 回测
```bash
.venv/bin/python scripts/strategy_backtest.py --strategy momentum --start 2026-06-01 --end 2026-08-18
.venv/bin/python scripts/strategy_backtest.py --strategies momentum swing --compare
```
