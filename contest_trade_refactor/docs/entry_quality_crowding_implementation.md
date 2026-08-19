# 系统目标：T+1 ~ T+3（不再是 T+3 ~ T+5）

## 为什么改

- 当前证据显示 T+1 alpha 最强，T+3 中性偏弱，T+5 在 6 月极端行情下最差（-6.4%）。
- 用户确认把目标从 T+3~T+5 改成 **T+1 ~ T+3**。

## 已改点

1. `agents/prompts.py`
   - research agent 问句从“未来 3-5 天上涨”改为“未来 1-3 天上涨”。
   - catalyst horizon 重点改为 T+1 / T+2~3。
2. `config/strategies.py`
   - momentum 策略 horizon: 短线 1~3 交易日。
3. `agents/exit_manager.py`
   - 默认止盈 +15% → +6%
   - 默认止损 -8% → -6%
   - A/B/C 止盈、止损都下调，符合 1-3 日短持。
4. 保留 closed-loop 仍计算 T+1/T+3/T+5，但结论以 T+1/T+3 为主。

## 对评分含义的影响
- BuyScore/Probability 的目标含义改为：未来 1-3 个交易日上涨概率。
- catalyst 事件 3-5 天后才可能发生的，不再当主力 alpha。
- 拥挤/入场惩罚继续保留，但其目标更多是为了避免 T+1/T+3 的追高回吐。


## 当前系统历史回测（用已有 replay 数据，不做新 LLM 搜索）

汇总 `current_no_future_june17_30`, `current_system_0810_0813`, `historical_pilot_rescore_short3d_v4` 三组历史信号：

| 信号组 | T+1 平均 | T+3 平均 |
|---|---|---|
| buy_passed | +1.40% (n=64) | +1.76% (n=55) |
| watch | +0.21% | +0.46% |

按 entry_quality 分桶：

| entry_quality | T+1 | T+3 |
|---|---|---|
| <35 | +2.49% | -2.65% |
| 35~50 | +0.62% | +4.65% |
| >50 | +0.58% | +0.84% |

结论：
- **T+1 是最稳的 alpha**；
- T+3 在 8 月样本里还不错，但 trend 一致性弱；
- entry_quality <35 的信号“T+1 还能赚，T+3 回吐”，说明拥挤/追高分股的持仓周期应更短。

产物：`agents_workspace/trade_plan_backtest_fix2_0617/current_t1_t3_replay_samples.csv`


## 持有期规则已固化

- `agents/signal_tier_classifier.py` 输出：
  - `recommended_holding_days`：默认 2；当 `entry_quality>=50` 且 `crowding<70` 时返回 3。
  - `holding_rule`：默认 `T+1_2_fast_exit`；高质量信号返回 `T+3_ok`。
- `agents/exit_manager.py`：
  - 超过 `recommended_holding_days` 就提高卖出分。
  - 默认止盈 +6% / 止损 -6%；T+1~T+2 优先兑现。

历史回测模拟（201 条已有历史信号）：

| 规则 | T+1 | T+3 |
|---|---|---|
| T+1_2_fast_exit | +0.82% (n=46) | +1.72% (n=39) |
| T+3_ok | +0.56% (n=155) | +1.40% (n=141) |

buy_passed 单独看两者差异很小，T+3_ok 的 median 略好一点。当前规则作为默认是安全的：默认2天，优秀信号允许拿3天。
