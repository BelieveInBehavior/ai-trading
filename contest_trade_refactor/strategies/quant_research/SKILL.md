# 量化研究共识 策略（旧版完整主流程）

把 `main_loop.SimpleTradeCompany` 这套完整 Agent + Pipeline 流程参数化为一个策略包：
- Stage 0：全市场量化预筛（`QuantitativeUniverseScreener`）
- Stage 1：Data Agents（新闻/技术指标/资金/板块/龙虎榜等）
- Stage 2+3：Research Agent 分片 + Consensus + Ranker（严格门控）
- Trade Plan：给 buy/watch 附加 1~5 天计划，`trade_plan_pass` 灰度加分
- Stage 4：Signal tracking / 回测

## 调整入口
- `strategy.yaml`：筛选/门控/回测默认参数，字段与 `config/strategies.py` 兼容。
- `beliefs.yaml`：研究 Agent 信念。
- `tools.yaml`：研究 Agent 工具（或留空回退 `config.yaml` 默认）。

## 运行
```bash
.venv/bin/python scripts/run_pipeline_rerun.py --strategy quant_research
.venv/bin/python scripts/strategy_backtest.py --strategy quant_research --run-replay --start 2026-06-01 --end 2026-08-18
```

## 与 V2 的关系
量化研究共识 是当前 `main_loop.py` 的旧主流程；V2（changqi 分支 `pipeline_v2/`）
是新的机会发现器 + Regime 前置的条件 Alpha 系统。本策略包只用于把旧 量化研究共识 流程
保留为"策略模式"，不改变 `main_loop.py`。
