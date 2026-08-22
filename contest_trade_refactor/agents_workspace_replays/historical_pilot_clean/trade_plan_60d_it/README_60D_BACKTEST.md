# 60 天窗口回测（增量，后台补拉中）

生成时间: 2026-08-17 15:15（中途）

## 数据覆盖
已纳入 28 个 trade_decisions（全部审计 `No findings`）：
- 2026-06-17、06-18、06-22、06-23、06-24、06-25、06-26
- 2026-07-15 ~ 2026-08-13
共 unique 信号 44 个。

后台正在补拉：
- 2026-06-29 起（目标补全 06-29~07-14）

## 回测结果（44 unique signals）
| 指标 | 值 |
|---|---|
| T1 胜率 | 47.7%（44） |
| T1 平均 | +0.79% |
| T3 平均 | -1.31%（41) |
| T5 平均 | -4.33%（40) |
| buy_passed | 7 个，T1 平均 -1.04%，T3 -3.61%，T5 -7.38% |
| watch | 31 个，T1 平均 +0.71%，T3 -1.08% |
| consensus | 6 个，T1 平均 +3.37%，T3 +0.53% |
| trade_plan_pass | 2 个 |

### 组合模拟（含 watch/consensus/research、T+3、含费）
- 37 trades
- 胜率 45.9%
- 平均每笔 -0.58%
- 总 P&L -14,932
- 收益 -1.49%
- 最大回撤 -6.53%
- Profit factor 0.84

## 结论（诚实）
- 已覆盖天数增加后，组合模拟亏损从 -2.05% 收窄到 -1.49%。
- 但 buy_passed 只有 7 笔且 T1 胜率 14.3%、T5 平均 -7.38%，不能证明策略能赚钱。
- watch/consensus 的 T1 平均为正，但 T3/T5 转负，说明 1-5 天波段中持仓拉长反而更差。
- 当前不能把 trade_plan_pass 当硬门控（只有 2 笔 pass）。

## 续跑
后台已自动续跑到 0629~。若中断，可手动：
```bash
.venv/bin/python scripts/replay_historical_no_future.py \
  --strategy momentum --start-date 2026-06-29 --end-date 2026-07-14 \
  --output-dir agents_workspace_replays/historical_pilot_clean \
  --symbols-limit 0 --concurrency 4 --hour 18 --skip-existing
```
