# 量化研究共识 策略包

把旧 量化研究共识 完整主流程（`SimpleTradeCompany` / `main_loop.py`）作为策略保留。

回测入口：
```bash
.venv/bin/python scripts/strategy_backtest.py --strategy quant_research --run-replay --start 2026-06-01 --end 2026-08-18
```

CLI 运行：
```bash
.venv/bin/python scripts/run_pipeline_rerun.py --strategy quant_research
```

`config/strategies.py` 会自动发现 `strategies/quant_research`，因此 Web `/api/strategies` 也会带出该策略。
