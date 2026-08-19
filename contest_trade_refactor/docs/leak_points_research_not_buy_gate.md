# 漏点定位：不是 Buy 门控，而是 research 覆盖 + LLM JSON 解析

## 结论

当前系统漏掉高收益股票，主要是漏在**更早的两级**，不是最终 `buy_signals` 门控:

1. quantitative_candidates 里有这些股票，research agent 没有覆盖（`research_signals=N`）。
2. 即使 research agent 输出里提到东方钽/金钼/壹石通，旧 `parse_json_signals` 只保留重复 key 的最后一个，导致大量 name 被丢弃。

所以给代码加“research_scope + 修 JSON 解析”是对的、但**不是为了让这些股票无脑 buy**；这些股票里很多 T3/T5 也是亏的。

## 数字

### 漏网 top120 高分候选（quantitative 高分但从未进任何流程）

- T3: win 48.3%，avg **+1.06%**
- T5: win 46.7%，avg **+0.35%**

说明这些“漏掉的名字”整体只有很弱的正向，并不是必须全捞。

### 被当前系统选中的信号（现有 trade_decisions）

- buy_passed T3: win 30%，avg -3.62%
- buy_passed T5: win 11%，avg -6.75%
- watch T3: win 38.2%，avg -2.56%
- consensus T3: n=5, avg +0.53%

### 如果把漏掉的高分候选盲目全放进来

不是赚钱，而是放进了一批 +16%/-17% 混合的噪音。真正的问题不是“门槛太紧”，而是**当前 research 选择的股票本身（AI/半导体/题材）在 3-5 天并没有正 edge**。

## 建议

1. **先不要为了捞回东方钽业/兴业科技而放松 buy 门控**。这两只是个例，强制捞回来会在像金刚光伏、安德利、中稀有色上踩大亏。
2. **下一步应该是把 research 输出改为“决策可验证”的结构**：给每个候选打上 horizon 内催化剂 + 事件日期 + 量化技术面是否对齐，然后用 T3 真实回报做监督信号找规则。
3. 真正要修的可能是**选股规则**，不是解析和覆盖——当前 buy_passed T5 只有 11% 胜率，不是“漏掉好的”，而是**选了不该选的**。

## 追加：因子对比矩阵（2026-06 回测实时因子）

已生成 `agents_workspace/trade_plan_backtest_fix2_0617/factor_return_matrix.csv`，
把两组数据合并：

- `missed`：从未进任何流程的高分候选 120 只（T3/T5 收益已知）
- 当前 captured：buy/watch/consensus 信号（T3/T5 收益）

### 各组平均

| 组 | n | T3 avg | T5 avg |
|---|---|---|---|
| buy_passed | 10 | -3.62% | -6.75% |
| watch | 34 | -2.56% | -4.75% |
| consensus | 5 | +0.53% | -6.90% |
| missed | 120 | +1.06% | +0.35% |

### 单因子切分（n≈140，全部 trigger-day 数据）

| 条件 | T3 avg | T5 avg |
|---|---|---|
| RSI ≤50% | +1.2% | -0.9% |
| RSI >50% | +0.2% | -0.0% |
| MA20偏离 ≤中位 | +0.8% | +0.0% |
| MA20偏离 >中位 | +0.6% | -0.9% |
| 量比 >中位 | +1.0% | +1.2% |
| 量比 ≤中位 | +0.4% | -2.1% |

### 组合规则试跑（没有发现能to稳定选赢家的规则）

- `ma20<=15 & RSI<75`：T3 avg +0.62%，WR 48%
- `vol>=1`：T3 avg +0.93%，WR 49%
- `rsi 40-70 & ma20<=15`：T3 avg +0.45%，WR 46%

结论：**这批实时因子对 T3 的区分度很弱**，无法靠简单的触发日数值把“换错掉的好股”从“坏股”分离。要做出赚钱规则，应该用 T3 真实收益做监督，而不是直接“把高分全部买进来”。

## 追加：quant 候选 vs research override 的实际收益

上一轮已经发现 most captured signals 是从 research 硬覆盖进来的，不是 quantitative 候选。这里再把它和买/看分开算：

### captured group 里是否来自 quant 候选的影响

- buy_passed 来自 quant：n=6，T3 avg -1.72%
- buy_passed override（非量化候选，如中际旭创/中微公司/天孚通信/新易盛等）：T3 avg **-6.47%**（4笔全亏）
- watch 来自 quant：11笔，T3 avg -1.79%
- watch override：23笔，T3 avg -2.93%
- consensus override：5笔，T3 avg +0.53%（样本太小）

结论：**当前买信号里最差的一批就是“research 越过量化候选直接覆盖”的那些 AI/CPO/光模块/半导体题材股**。它们没有量化技术因子，但反而更容易被 research agent 投票买上。这比“量化高分被漏掉”更值得优先处理。

## 我认为被你“没考虑”的因子

不是缺计算，而是这些已经有但没在筛选里做限制：

1. **相对强度（relative_strength_20d/60d）**：已算，但当前只映射为分数，没做“相对强度过高=过热”的过滤。
2. **量比（volume_ratio）**：已算；对 T5 略正，但没用于“放量突破必须温和”的门控。
3. **weekly_close_vs_ma20_pct / weekly_ma20_slope_pct / weinstein_close_vs_ma30_pct**：已算，但当前只用于 weekly_trend_score 一把和，趋势斜率没有被单独惩罚。
4. **long_term_structure（ma50/ma200/52w 距离）**：已算；可以区分“真正的新趋势”和“已经涨到天上去的妖股”。
5. **MACD/ATR/volatility 位置**：已算，但没有做成“不要在 ATR 极端放大日追”的过滤。
6. **机会分本身**：`short_score / room_score / forward_opportunity_score` 已算，但对 T3 的区分度在我试了之后几乎没有。

所以结论不是“缺因子”，而是“因子都在，但没有形成一个能降低当前负 edge 的可执行规则”。之前的简单筛选（RSI区间、MA20、量比）都验证了没有显著区分度。下一步是要把这些已有因子组合成稳定规则并 walk-forward 验证。

## 改法建议

真正值得优先拦掉的是 non-quant override（research 越界覆盖）。毕竟上面已经证明 override 信号 T3 avg -2.84%，比 quant 候选还差。可以先做一个“白名单化”：

- 没有量化技术因子（不在 quantitative_candidates）的 research 覆盖，除非有明确 T+3/T+5 催化剂且非题材/非 AI 硬覆盖，否则不许进 watch/buy。
- 或者在最终 buy 门控中加一条：`quantitative_screen.passed == True`（目前还是会被 `_restrict_to_quantitative_candidates` 之外的研究覆盖绕过）。


## 2026-08-17 追加：移除 research 硬覆盖的验证

### 代码修改（已生效）

1. `main_loop._restrict_to_quantitative_candidates`：**移除 `_is_strong_research_override_signal` 白名单**。现在 research signal 如果不在 `quantitative_candidates`，直接丢弃，不能进入 watch/buy/consensus。
2. `agents.prompts.prompt_for_research_invest_task`：research agent 的 `<research_scope>` 从“除非强覆盖”改为**“只能是这份列表里的股票，不许用题材/板块自行硬覆盖”**。

### 2026-06-17 smoke（新白名单）

- research_signals=5，buy=2，watch=3，consensus=5，全部在 `quantitative_candidates` 内。
- 买/观察名单里不再出现中际旭创/中微/天孚/新易盛等非量化覆盖。
- 新选出：中国稀土、盛和资源（buy）；华锡/中稀/神工（watch）。
- 用真实 T3 回测：
  - buy 中国稀土 T+3 +1.83%、盛和资源 T+3 +7.07%
  - watch 华锡 -2.62%、中稀 +1.02%、神工 +3.22%

### 对“research agent 是否需要硬覆盖题材股”的回答

**不需要，而且应当关闭。**

证据：
- 非量化 research override 在当前 30 天历史里 T3 avg **-2.84%**、WR 31%（32 笔），其中 buy 的 4 笔**全亏**（-6.47%）。
- 量化候选即使漏网，整体 T3 +1.06%；不是优秀，但远好于 override。
- 移除 override 后 2026-06-17 smoke 的候选全部落在量化池内，且当日仍能选出两只 T3 正向 buy。

下一步应继续以量化池为硬入口，research 只需在池内做“催化剂/事件”评价，不要自己扩展题材池。


## 2026-08-17 追加 2：rule 初筛（勿写死生产）

在 140 个既有（多为漏网高分 + captured）样本里做了粗筛。结论有限，但可作方向：

### 唯一在 T3/T5 上稳定的信号

| 因子 | T3 corr | T5 corr | 说明 |
|---|---|---|---|
| `weekly_close_vs_ma20_pct`（周线相对 MA20 距离） | **-0.207** | **-0.27** | 周线越拉伸，T3/T5 越差 |
| `weekly_ma20_slope_pct`（周 MA20 斜率） | **-0.203** | **-0.23** | 斜率越陡，后续越容易回吐 |
| `short_score` | +0.14 | +0.23 | 短线 setup 越高，T5 越好 |
| `volume_ratio` | +0.01 | +0.11 | 量比对 T5 轻微正，T3 无效 |
| other（RSI/MA20/相对强度/forward） | 近 0 | 近 0 | 无单因子意义 |

### 组合规则（时间剖，train 130 : test 6，taget 太小不给结论）

- `周线延伸<=22 & short_score>=78`：train T3 +2.18% / WR 55%
- `周线延伸<=22 & 周MA20斜率<=10`：train T3 +2.13% / WR 54%
- `short_score>=80 & 周延伸<=25 & 量比>=1`：train T3 +1.89%，T5 +3.35%

**但这些规则在样本外 test n=6，没足够统计意义；另一方面它展示方向：短线偏好的短强但“别太拉伸”。**

### 不应落地的结论

- 不要在 T1/T5 里用单一因子把候选拒死。
- 当前样本太小，不足以把“并条件规则”写死进生产。
- 下一步建议：扩大样本（补拉 2026-05~06 或 2026-05 到现在的所有已收盘 T3/T5），再做 walk-forward。


## 2026-08-17 追加 3：用 8 月数据验证筛选因子 —— 不成立 🚫

把 6/7 月份训练得到的因子组合在 2026-08 的真实量化候选 + 前收后收益做了 forward 验证（用 trigger 当日因子，T3/T5 用未来的买卖价算），结果：

### 8 月全体量化候选（基线）

- T3：n=560，avg +2.78%，WR 60%
- T5：n=480，avg +3.59%，WR 59%

### 用 6/7 月找到的规则（周线延伸≤22% + short_score≥70 + 量比≥0.8）

- T3：n=213，avg **+1.38%**，WR 53%  ← 比全体候选更差
- T5：n=182，avg +2.10%，WR 51%

### 更严格版本（周延伸≤15 + short≥75）

- T3：n=78，avg **+0.16%**，WR 42%
- T5：n=66，avg +0.54%，WR 39%

### 按日看（T3 平均收益）

| 日期 | 全体候选 | 规则候选 |
|---|---|---|
| 08-03 | +3.61% | +1.26% |
| 08-04 | +3.97% | +1.86% |
| 08-05 | +4.86% | +2.22% |
| 08-06 | +3.67% | +3.13% |
| 08-07 | +1.32% | +1.70% |
| 08-10 | +0.40% | -0.01% |
| 08-12 | +1.65% | -0.25% |

### 结论：这批因子存在明显的过拟合风险

- 8 月整体是结构性 “普涨” 状态，全体候选本身就很好；规则反而砍掉了赢家。
- 那些 T3 +25%~+31% 的赢家几乎都是高周延伸、不高 short 或者量比低的“非规则”股，而规则过滤掉了它们。
- 用 6/月 因子直接套 8 月，不具备稳健性。

需要换思路：不能用一个固定规则套所有月份；要么做“卷动/回归切割”，要么只做事件催化型的 T3 信号（有明确买卖点）而不是用因子打分。

### 产物文件

- `agents_workspace/trade_plan_backtest_fix2_0617/august_all_outcomes.csv`
- `agents_workspace/trade_plan_backtest_fix2_0617/august_filtered_rule_outcomes.csv`
- `agents_workspace/trade_plan_backtest_fix2_0617/august_signals_outcomes.csv`

