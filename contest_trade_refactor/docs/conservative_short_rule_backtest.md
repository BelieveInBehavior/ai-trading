# 短线保守组合（Conservative Short Rule）回测

## Rule 定义
在 `utils/conservative_short_rule.py` 正式加入，公式只使用 trigger 日已知因子，无 future leak：

- **RSI 中低位**：`rsi <= 65`
- **距 52 周高点有缓冲**：`lt_distance_to_52w_high_pct <= -8%`（即至少低于 52 周高点 8%）
- **MA20 不过度偏离**：`ma20_deviation_pct <= 12%`
- **MA50 不过度偏离**：`lt_ma50_deviation_pct <= 25%`

## 月度回测结果（unified_month_panel，2400 条候选项）

| 月份 | 样本 | T3 avg | T3 胜率 | T5 avg | T5 胜率 |
|---|---|---|---|---|---|
| 6月 全体 | 719 | +0.59% | 48.1% | -0.14% | 43.7% |
| 6月 保守组合 | 118 | **+0.85%** | 49.2% | **+0.53%** | 45.8% |
| 7月 全体 | 1039 | -1.42% | 43.9% | -1.16% | 44.7% |
| 7月 保守组合 | 475 | **-1.43%** | 42.9% | **-0.29%** | 47.8% |
| 8月 全体 | 560 | +2.78% | 60.0% | +3.59% | 59.2% |
| 8月 保守组合 | 271 | **+3.56%** | 65.3% | **+5.32%** | 66.5% |

## 关键结论

1. **7 月是个 regime 逆风月**：无论全体还是保守组合，T3 均值都是负/微负；不是这个规则能修复的。
2. **保守组合在 6 月、8 月优于全体**，尤其 8 月胜率提升明显（T3 60%→65%，T5 59%→67%）。
3. **7 月 T5 有缓解**：保守组合 T5 从 -1.16% 回到 -0.29%，但 T3 仍 -1.43%，不能宣布“稳定正期望”。
4. 因此当前 `unified_month_panel` 的月度结论：**规则可以降波动、8月增强、6月微增强；7月不能治**。要达到“月度正期望稳定”，还需要 regime 过滤（弱月缩仓）或事件/资金面补充。

## 已补的日线字段
`scripts/enrich_conservative_daily_fields.py` 生成了 `daily_enriched_panel.csv`，加入：
- 换手率：`turnover_pct` / `turnover_5d_avg_pct` / `turnover_20d_avg_pct` / `turnover_ratio_5_20`
- 短动量：`mom_3d_pct` / `mom_5d_pct`
- 前高距离：`dist_20d_high_pct` / `dist_60d_high_pct`
- 布林位置：`boll_pct_b` / `boll_above_pct`

### 新字段跨月稳定性（T3 spearman corr）
| 字段 | 6月 | 7月 | 8月 |
|---|---|---|---|
| 换手率 | -0.04 | -0.25 | +0.28 |
| 换手率2020均 | -0.02 | -0.26 | +0.32 |
| 换手率 5/20 | -0.05 | -0.01 | -0.06 |
| 3日动量 | +0.01 | -0.14 | +0.12 |
| 20日前高距离 | -0.05 | +0.11 | -0.31 |
| 布林 %B | -0.05 | +0.01 | -0.19 |

**没有出现跨 3 个月方向一致的固定因子**；8 月“低前高/低布林”有效，7 月反而偏无效。任何把 8 月的因子写死都有过拟合风险。

## 产物
- `utils/conservative_short_rule.py`
- `scripts/backtest_conservative_rule.py`
- `scripts/enrich_conservative_daily_fields.py`
- `agents_workspace/trade_plan_backtest_fix2_0617/conservative_rule_with_rule.csv`
- `agents_workspace/trade_plan_backtest_fix2_0617/daily_enriched_panel.csv`

## 敏感性（不同阈值，T3 月均）

| 变体 | 6月 n/avg | 7月 n/avg | 8月 n/avg | 3个月全正 |
|---|---|---|---|---|
| 默认 RSI≤65 dist≤-8 ma20≤12 ma50≤25 | 118 / +0.85% | 475 / -1.43% | 271 / +3.56% | 否 |
| RSI≤60 dist≤-12 ma20≤10 ma50≤20 | 35 / -2.91% | 246 / -0.44% | 140 / +4.59% | 否 |
| RSI≤60 dist≤-15 ma20≤10 ma50≤20 | 18 / -2.50% | 183 / +0.02% | 106 / +4.00% | 否 |
| RSI≤62 dist≤-10 ma20≤6 ma50≤15 | 28 / -1.05% | 256 / -0.54% | 140 / +4.17% | 否 |
| RSI≤60 dist≤-20 ma20≤5 ma50≤30 | 0 / - | 74 / +0.74% | 36 / +4.96% | (6月无样本) |

**结论：想靠提高“远离52周/MA20更严”让 7 月翻正，会牺牲 6 月样本和样本量；这是典型的 regime 差异，不是稳定因子。**
