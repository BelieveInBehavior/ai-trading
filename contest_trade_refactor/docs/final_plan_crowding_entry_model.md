# 综合方案：T+3~T+5 事件驱动短期系统的“强度 + 时点”重构

> 目标不是把系统从趋势策略变成另一套更复杂的趋势策略，
> 而是回答一个更短的问题：
> **这个机会虽然很强，但今天这个位置还能不能追？**

## 一、结论

当前系统已经完成从长周期趋势筛选到 **T+3~T+5 Event-Driven Momentum** 的第一步重构：

- 硬过滤已放松为：数据质量 / 极端过热 / 长期破烂；
- 已加入 `close_above_ma5`、`ma5_slope_pct`、`ret_3d/5d`、`breakout_20d/60d`、`volume_ratio/amount_ratio`；
- 修正了 volume_ratio 定义（今日量 / 前5日均量，不含今日）；
- 板块富化已接入，覆盖约 2370 只（`enrich_factor_with_sector` 同时支持 6/9 位代码）。

但 6 月 no-future replay 暴露的核心问题是：
buy 信号的 T+1 还能正收益，T+3/T+5 转负，且 **score>90 的 T+5 最差（-6.93%）**。

这印证了用户的判断：**问题不是选错股票，而是买错位置**。
我们把“已经发生的强势”错误地当成“未来仍有空间”。

因此综合方案为：

**不增加“5日涨幅 >20% reject”这类硬过滤，改成在 Ranker 中增加第五维度：**
**「入场位置 / 拥挤度 / 加速末端」风险调整评分。**

## 二、总体架构

```
                 短期机会
                    │
        ┌───────────┴───────────┐
        ↓                       ↓
      强度                       时点
        │                       │
  启动/量价/板块/催化       拥挤/加速/获利盘
        │                       │
        └───────────┬───────────┘
                    ↓
          Risk-Adjusted Short-term Score
                    │
             T+1 / T+3 / T+5
```

对应到当前代码分层：

| 当前层 | 作用 | 改动 |
|---|---|---|
| Stage 0 基础过滤 | 排除不可交易/极端异常 | 基本保留，仅保留数据质量、极端过热、长期破烂 |
| Stage 1 短期趋势/启动 | 判断是否在启动 | 保留并继续加 `ret_10d/20d`、加速斜率 |
| Stage 2 量价确认 | 今日放量 + 资金参与 | 修正后的 ratio（已做） |
| Stage 3 板块强度 | 板块强不强 | 保留，补 sector_5d/10d、板块拥挤度 |
| Stage 4 事件催化 | 3~5 天催化 | 保留 |
| **Stage 5 拥挤度/入场位置** | **现在还能不能追** | **新增，核心改动** |

## 3. 入场位置 / 拥挤度因子设计

### 3.1 个股近期涨幅（非硬过滤，仅软评分）

```
ret_3d_pct      已有
ret_5d_pct      已有
stock_return_20d_pct  已有（来自 relative_strength_factor）
新增 ret_10d_pct
```

示例档位（先用于评分，不用于 reject）：

| 5D涨幅 | 含义 | 评分方向 |
|---|---|---|
| < 8% | 正常/初期 | 不加分不扣分 |
| 8~15% | 已启动 | 轻微扣分（-2~-5） |
| 15~25% | 明显加速 | 明显扣分（-8~-12） |
| > 25% | 高风险 | 扣分最高，除非催化剂极强或刚突破 60 日高点 |

### 3.2 个股加速/衰竭

```
day_return = ret_1d_pct
recent_offset = ret_5d - ret_3d  # 5日去掉最近3日，近似“前段 vs 近段”
accel = ret_1d_pct - (ret_3d_pct - ret_1d_pct)/2  # 简化加速斜率
```

规则：
- `accel > 8` 且 `ret_5d > 18` → 加速末端惩罚；
- `ret_1d` 大涨但 `amount_ratio < 1.2` → 假突破降权；
- `close_vs_20d_high_pct < -1` 但 `ret_5d > 20` → 冲高回落降权。

### 3.3 板块拥挤度（重要，当前缺口）

当前板块富化只给了 `sector_1d_return / sector_3d_return / sector_rank`，缺少关键拥挤因子。

建议新增（可先用现有 90 个行业指数 + industry_map 重建每日 upsert 快照）：

```
sector_3d_return     已有（部分快照只有 1d）
sector_5d_return     新增
sector_10d_return    新增
sector_up_ratio      板块内上涨股票占比   （需要个股/行业成分计算）
sector_volume_ratio  板块成交量放大      （需要板块指数成交量）
sector_rank          已有
sector_continuous_up_days  新增
```

板块拥挤度可定义为复合分：

```
crowding_score =
  band(sector_3d_return)     x 25
+ band(sector_5d_return)     x 20
+ band(sector_10d_return)    x 15
+ band(up_ratio)             x 15
+ band(sector_volume_ratio)  x 15
+ band(continuous_up_days)   x 10
```

高阶：crowding_score 归一到 0~100，然后：

```
crowding_penalty = -0.35 * max(0, crowding_score-50)   # 最多约 -17.5 分
```

若拥挤 80 以上且“个股 ret_5d >15”，再追加 `-8`，只有催化剂极强或刚突破才能部分对冲。

### 3.4 个股相对板块

```
stock_vs_sector_strength = ret_3d_pct - sector_3d_return
stock_vs_sector_5d     = ret_5d_pct - sector_5d_return
```

规则：
- `stock_vs_sector >5` 且板块不拥挤 → 加分（资金集中度高）；
- `stock_vs_sector >5` 且板块拥挤 ≥75 → 个别股可能脱离板块，但也可能已透支，不额外加分；
- `stock_vs_sector < -5` → 弱于板块，降权。

## 4. Ranker / Score 结构

建议把当前 BuyScore 改造成两段式：

```
BuyScore = 基础分(原四维) + 入场质量分(新增) - 拥挤/衰竭惩罚
```

| 维度 | 当前权重 | 建议权重 |
|---|---|---|
| catalyst_score | 0.22 | 0.18~0.20 |
| short_momentum_score | 0.12 | 0.12~0.14 |
| volume_amount_score | 0.12 | 0.12 |
| sector_score | 0.10 | 0.08~0.10 |
| technical_score | 0.12 | 0.10 |
| daily_entry_score | 0.05 | 0.08~0.10 |
| weekly/RS | 0.06/0.08 | 降为 0.03~0.05（信息参考，不作为核心） |
| **entry_quality/crowding_penalty** | 无 | **-0.15~-0.20** |

实现上：
- 不要先把 `total` 归一化到 [0,100]，再加惩罚；
- 先 `total = 强度分`, 再 `total += entry_delta + crowding_delta`；
- 最终再 clamp 到 [0,99.5]。

评分含义重定义：
- 95 分 ≠ “今天涨得最猛的股票”；
- 95 分 = **“当前市场上风险收益比最好的短期机会”**。
- 高分信号如果 `crowding_penalty` 过大，应降至 watch 或降档。

## 5. 事件催化层不变，但要防止“事件已经定价”

已做：`risk_veto` 里 `catalyst_already_priced`（事件日期 ≤ 触发日 → stale）。
后续可再补充：
- 事件驱动研究 Agent 仍回答“未来 3~5 天有无东西继续推动”，而非“公司是不是好公司”。
- 对“业绩快报/新订单”等公告类，同一天收盘后公告的“盘后发布”标记不应成为次日追买依据；除非次日盘中量和价确认。

## 6. Hard filter vs soft score 落地约束

保留**不硬杀超涨**原则，但考虑两个“风险限制”：

1. **个股极端异常**：`prev_day_gain_pct > 20` 且非突破，维持硬过滤（当前已有，级联可放宽）。
2. **中奖价风险**：`ma20_deviation > 45%` 且 `sector_5d > 8%` 且 `buy_score < 65` 可降为 watch（非 reject），避免在高拥挤 + 高过高中再给高分。

> 不放硬 `5D >15/20 reject` 的原因：真正启动主升也可能 5D 涨 20%+。
> 我们惩罚的是“板块拥挤+个股涨幅+加速末端”这一组合。

## 7. 回测验证 / 下一步

### 7.1 先做实验，不先调阈值

在 6 月 no-future replay 上重新生成字段：
```
stock_return_3d_pct
stock_return_5d_pct
stock_return_10d_pct（新增）
stock_return_20d_pct
sector_3d_return
sector_5d_return（新增）
sector_10d_return（新增）
sector_up_ratio（新增）
crowding_score（新增）
buy_score
t1/t3/t5
```

重点做二维分析：

1. `个股5D涨幅 × T+5收益`
2. `板块5D涨幅 × T+5收益`
3. `个股5D ∩ 板块5D × T+5收益`

目标：验证以下假设（大概率会成立）

> 危险的不是“个股涨很多”，而是“个股已经涨很多 + 所属板块也已经涨很多”。

### 7.2 后再实现 penalty

如果第一张图显示 `个股涨幅高 + 板块涨幅低` 的 T+5 其实没那么差，就更加坚定不要砍 5D>20。

直接改代码路径：

```
data_source/technical_indicators_akshare.py  -> 新增 ret_10d_pct, stock_return_3d_pct
utils/sector_enrichment.py                  -> 新增 sector_5d/sector_10d/crowding 等字段结构
agents/quantitative_universe_screener.py   -> 在 short_score/sector_score 里加软权重
agents/stock_opportunity_ranker.py         -> 第五维度：_score_entry_quality/crowding_penalty
config.yaml                                -> 保留 hard filter 不变，target 改为 T+3~T+5
```

### 7.3 重新回测只跑 no-future，避免过拟合

- 继续用 `scripts/replay_historical_no_future.py`，设 `CONTEST_TRADE_ASOF_DATE`；
- 6 月样本跑完后再跑 7 月、8 月作为 out-of-sample；
- 每次改动后跑 6 月全量 + 8 月全量，不单独拿 6 月拟合阈值；
- 审计未来泄漏：`scripts/audit_future_leak.py`。

如果最终模型对“拥挤度惩罚”的验证很好，再考虑：

- `crowding_score > 75` 时按严重程度把 BuyScore 下调；
- score>90 的 T+5 如果仍然差，则在 Ranker`gate_report` 里加 `high_score_crowding_penalty` 作为降档观察，但仍不直接 reject。

## 8. 完整架构落地顺序

1. 补因子：`ret_10d_pct`、`stock_return_3d/5d/10d/20d`（部分已有）。
2. 补板块拥挤：`sector_5d/10d`、`sector_up_ratio`、`sector_volume_ratio`、`continuous_up_days`；
   - 先做能落地的：用行业指数 percent_change 分日计算 1/3/5/10 日涨幅，板块成交量用 factory 的成交量。
3. 在 `stock_opportunity_ranker.py` 加 `_score_entry_quality_crowding`：
   - 返回 `entry_delta`（-20~+5）。
4. 在 `_score_single_signal` 权重接入，并把 scorecard 输出 `entry_quality_score` 与 `crowding_score`。
5. 跑 6 月天数 no-future 回测、生成二维/三维分析表。
6. 若数据验证后，再加 `sector_crowding_score` 的默认/最高惩罚，并固化阈值。

### 9. 风险约束仍保留，但不是机会来源

| 维度 | 用途 |
|---|---|
| Weekly / Weinstein | 用于低分预警，除非高分数跳过 |
| MA20 偏离 | 仅作为昂贵位的一部分，不高分时超过 12 才罚 |
| RS 20/60D | 参考旧动量，不构成 T3/5 alpha |
| 板块资金流 | 用于“强度”，不用“绝对拥挤” |
| 事件催化 | 未来 3~5 天是否有东西推动，还是盘后已定价 |

## 10. 最后判断

方向：**把“强度”系统升级成“强度 + 时点”双模型是合理且必要的**。

不要做：
- 不加 5D>20 reject；
- 不加回 Weekly/Weinstein/MA20 作为核心买点；
- 不立即拿着 6 月数据拟合阈值。

要做：
- 5 层评分 = 启动 + 量价 + 板块 + 催化 + **入场位置/拥挤度**；
- 先补 sector_5d/10d/crowding 因子，再跑 no-future 分类分析；
- 4~8 月滚动 out-of-sample 验证后，再固化 penalized scoring。

这样可以把当前从“追热点 → T+1 赚”改造成“选择那些强度还在、位置不挤的机会 → T+3/T+5 更容易赚”的状态机。
