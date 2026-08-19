# Swing 策略

适用于中长线/趋势交易，筛选趋势初期/回踩确认，避免追高。

## 调整入口
- `strategy.yaml`：筛选 / 排名 / 研究轮次 / 生命周期门控参数。
- `beliefs.yaml`：研究 Agent 的信念。
- `tools.yaml`：研究 Agent 可用工具。

## 回测
```bash
.venv/bin/python scripts/strategy_backtest.py --strategy swing --start 2026-06-01 --end 2026-08-18
.venv/bin/python scripts/strategy_backtest.py --strategies momentum swing --compare
```
