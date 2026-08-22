# 基于已有 trade_decisions 的 Trade Plan 真实历史回测

生成时间: 2026-08-16

## 数据
- 重建文件：`agents_workspace/trade_plan_backtest/*.json`（给 buy/watch/consensus 信号附加 trade_plan）
- 回测 CSV：`agents_workspace/trade_plan_backtest/backtest_results/signal_performance.csv`
- 组合模拟：`agents_workspace/trade_plan_backtest/backtest_results/portfolio_trades.csv`

## 组合模拟总览（18 笔模拟交易，T+1 交易日，含手续费/滑点/印花税）

| 指标 | 值 |
|---|---|
| 交易数 | 18 |
| 胜率 | 38.9% |
| 平均每笔收益 | -0.14% |
| 总盈亏 | -4,213 |
| 策略回报 | -0.42% |
| 最大回撤 | -1.06% |
| 盈利因子 | 0.72 |

## 关键发现：trade_plan_pass 目前不具备正向甄别力

在组合模拟的 18 笔里：

| trade_plan_pass | 笔数 | 胜率 | 平均收益 | 总盈亏 |
|---|---|---|---|---|
| FALSE | 15 | 46.7% | +0.18% | -553 |
| TRUE  | 3  | 0%   | -1.70% | -3,660 |

说明：**在当前初版 RR>=1.5 等规则下，PASS 信号反而更差。**
- PASS 样本极少（仅 3 笔）
- 全是小样本，不能据此得出“RR<1.5 更好”
- 但至少说明：不能直接把 trade_plan_pass 升级为硬门控；需要先优化规则/更多样本。

## 按信号组

| 信号组 | pass | 笔数 | 胜率 | 平均收益 | 总盈亏 |
|---|---|---|---|---|---|
| buy_passed | FALSE | 1 | 100% | +1.08% | +834 |
| consensus | FALSE | 4 | 50% | +2.42% | +4,253 |
| consensus | TRUE | 1 | 0% | -1.50% | -893 |
| watch | FALSE | 10 | 40% | -0.81% | -5,640 |
| watch | TRUE | 2 | 0% | -1.80% | -2,767 |

注意：buy_passed 只有 2 个原始信号，样本太少。

## 建议

1. 不要直接开硬门控。
2. 当前 trade_plan 规则（RR>=1.5 作为 PASS）在历史上没有证明有优势。
3. 下一步应该优化 trade_plan 规则：
   - 也许 RR>=2.5 或 3 更严格
   - 或者把 VWAP 位置、量能确认加权重
   - 或者用 watch/consensus 的失败样本反向提炼“好计划”的特征
4. 需要更多成熟样本（目前 only ~18 笔模拟，buy 信号很少）。

## 最终建议规则（基于小样本，仅供参考）

经过规则扫描，当前更合理的 `trade_plan_pass` 规则是：

```
trade_plan_pass =
  信号级别 ∈ {buy_passed, consensus}   # 只把 buy/consensus 当可执行
  AND RR ≥ 1.0
  AND 量比 ≥ 1.0
  AND RSI ≤ 70
  AND 止损存在
```

理由：
- 历史 watch 信号大量亏损，不适合作为买入核心
- RR 单独越高反而不明显；叠量比后更有区分力
- 该规则在 33 个历史信号中只选出 1 个 PASS（300308），T1 +4.64%

⚠️ 样本极少，不能视为赚钱保证。**
它更像是「下一步用真实数据验证的初始参数」，不是一个已被证明的盈利规则。
