# Strong Diverge 强势分歧龙头战法

独立策略包，不依赖旧 momentum/swing / Research Agent 链路。

## 流程

1. **强势股票发现池**：全市场 → 基础过滤 → 260日K线 → 强势行为计算。
2. **三类分流**：
   - 连板型（最高优先）：连板数、封单强度、炸板次数
   - 突破型（次优先）：60日新高、20日新高、量价
   - 趋势启动型（降权）：周线/RS 只判断“刚启动”，MA20偏离过大降分
3. **分层观察池**：连板 / 突破 / 趋势各自 Top N + 板块去重。
4. **等待分歧**：严格首阴 / 断板（Divergence Event）。
5. **弱转强 Gate + T+1买入判断**：必须满足硬条件 Gate。
6. **T+1~T+3管理**：止损/止盈/移动止损/超期。
7. **卖出**。

## 关键概念
- `strength_watch_score`：进入观察池资格分（谁已经被市场验证强）。
- `divergence_event`：第一次断板 / 首阴，必须发生在强势生命周期后，不能只按当天涨跌判断。
- `divergence_quality_score` / `divergence_grade`：这次分歧健不健康（A类健康 / B类中性 / C类弱），
  与“是不是跌了”分离。
- `weak_to_strong_confirmed`：必须通过硬条件 Gate（默认 5 选 4）之后才能进入买入判断。
  Gate 严格定义：站上开盘、站上VWAP、回踩VWAP成功（low<=VWAP 且 close>=VWAP 且 close 接近 VWAP）、
  HH/HL 短线结构（前两日高点/低点均抬高）、量价确认（上涨放量或回调缩量+MA5）。
- `entry_quality_score`：只回答这个价格值不值得买。
- 四者是生命周期 Gate 依次通过，不是加权成一个总分。

## 调整入口
- `strategy.yaml`：`discovery / watchlist / divergence / confirmation / t1_buy / holding`
- 观察池分层配额：
  - `max_lianban`（默认20）
  - `max_tupo`（默认15）
  - `max_qushi`（默认10）
  - `max_per_concept`（每个板块最多 3 只）

## 运行
```bash
# 独立运行
.venv/bin/python scripts/strong_diverge_backtest.py --start 2026-08-11 --end 2026-08-18 --symbols-limit 200

# 统一入口
.venv/bin/python scripts/strategy_backtest.py --strategy strong_diverge --run-replay
```
