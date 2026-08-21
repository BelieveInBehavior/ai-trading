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

## Strong Diverge（强势分歧龙头战法）

- 位置：`strategies/strong_diverge/`。
- **完全独立**：有自己的规则引擎 `engine.py`，不依赖旧 `main_loop` / Research Agent 链路。
- 独立运行：
  ```bash
  .venv/bin/python scripts/strong_diverge_backtest.py --start 2026-08-11 --end 2026-08-18 --symbols-limit 200
  ```
- 统一入口会自动分发到独立脚本：
  ```bash
  .venv/bin/python scripts/strategy_backtest.py --strategy strong_diverge --run-replay
  ```

## First Board Continue（首板后延续）

- 位置：`strategies/first_board_continue/`。
- **完全独立**：有自己的规则引擎 `engine.py`，不依赖旧 `main_loop` / Research Agent 链路。
- 做“首板 → T+1 正常延续”的 C 类机会，不要求 weak-to-strong。
- 独立运行：
  ```bash
  .venv/bin/python scripts/first_board_continue_backtest.py --start 2026-08-11 --end 2026-08-18 --symbols-limit 200
  ```
- 统一入口会自动分发到独立脚本：
  ```bash
  .venv/bin/python scripts/strategy_backtest.py --strategy first_board_continue --run-replay
  ```
