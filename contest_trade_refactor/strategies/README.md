# 策略包（Strategy Packages）

每个策略是一个独立目录，包含：

- `strategy.yaml`：策略筛选、研究、生命周期、回测参数。
- `beliefs.yaml`：研究 Agent 的信念列表。
- `tools.yaml`：研究 Agent 可用工具清单。
- `SKILL.md`：给 Codex / 开发者的策略说明与调整指引。

新增策略：复制一个现有目录为模板，新建目录名，修改上述文件即可，不需要改 `main_loop.py`。

统一回测入口：
```bash
.venv/bin/python scripts/strategy_backtest.py --strategy <name> --start YYYY-MM-DD --end YYYY-MM-DD
.venv/bin/python scripts/strategy_backtest.py --strategies <a> <b> --compare
```
