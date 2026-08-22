# 主升浪趋势跟踪系统（Main Trend Following Engine / MTF）

策略包：`strategies/main_trend/`。

## 架构（对应 README 文档）
Layer 0 DataQuality（硬过滤）
-> Layer 1 MarketRegime（A/B/C/D）
-> Layer 2 TrendState（S0~S5，S1/S2/S3 才可新增候选）
-> Layer 3 TrendQuality（A/B/C）
-> Layer 4 SectorState（Ex-Self）
-> Layer 5 CatalystState
-> T+1 ExecutionState（Gap/Auction/Index/Sector/VWAP/Flow）
-> Layer 6 RiskState（风险预算）
-> Layer 7 PositionStateMachine（HOLD/ADD/DECAY/REDUCE/EXIT）

## LLM 边界
LLM 只做新闻解析 / 事件分类 / 异常解释，输出结构化变量。
Engine 是确定性引擎，决定是否买、买多少、何时止损/退出。

## 运行
```bash
.venv/bin/python scripts/main_trend_backtest.py --date 2026-08-18 --symbols-limit 200
.venv/bin/python scripts/main_trend_backtest.py --start 2026-06-01 --end 2026-08-18
.venv/bin/python scripts/strategy_backtest.py --strategy main_trend --run-replay
```

## Layer 1 Market Regime（A/B/C/D 七维输入）

指数趋势 / 指数动量 / 市场广度 / 新高-新低 / 市场成交额 / 板块广度 / 市场波动

- A/B: allow_new=True, risk_multiplier=1.0
- C: allow_new=True, risk_multiplier=0.5
- D: allow_new=False, risk_multiplier=0.0

对应实现：`engine.evaluate_market_regime()`。

## Layer 2 Trend State（S0~S5 主升浪状态机）

- S0 Base Preparation：尚未形成有效主升浪，PASS。
- S1 Breakout / Launch：平台突破 + 量扩张 + 短期均线转强 + RS增强；价格站上关键成本区（筹码/成本仅辅助加分，不硬条件）。
- S2 Acceleration：创新高 + RS强 + 量价健康 + MA多头（MA5>MA20>MA60），允许正常建仓和加仓。
- S3 Continuation / Consolidation：涨后盘整、缩量、MA20继续上行、重新突破；不因未创新高判死。
- S4 Exhaustion：主升末端，不预测顶部，只记录趋势质量下降维度（创新高减速 / RS 回调 / ATR 异常 / 量异常 / 板块转弱）风险预警，不新增。
- S5 Trend Breakdown：趋势破坏硬退出，Close<MA20+RSI 弱；ATR Trailing Stop / 次日无法站回在持仓状态机处理。

对应实现：`engine.assess_trend_state()`。

## T 日硬过滤（最终 8 条）

| # | 硬过滤 | 条件 |
|---|---|---|
| 1 | Market Regime | Regime != D |
| 2 | 交易状态 | 非 ST / 非停牌 / 非退市整理 |
| 3 | 上市时间 | TradingDays >= 120 |
| 4 | 流动性 | 20D Median Turnover >= 全市场横截面 P20 |
| 5 | 价格生命线 | Close > MA20 |
| 6 | 趋势结构 | MA20 > MA60 |
| 7 | MA60 方向 | 5日线性回归标准化斜率 > 0 |
| 8 | Trend State | S1 / S2 / S3 |

对应实现：`engine.apply_hard_filter()`。

T 日公式：
```text
T日硬过滤 = Market AND TradingStatus AND History AND Liquidity AND Close>MA20
          AND MA20>MA60 AND MA60Slope>0 AND TrendState∈{S1,S2,S3}
```

## 当前验证（示例）

2026-08-18，`symbols_limit=50`：

```text
universe      : 50
candidates    : 19   (pre hard-filter + TrendState S1/S2/S3)
eligible      : 4    (after 8-item T-day hard filter)
buy_ready     : 1    (after execution scoring)
```


## Layer 3 Trend Quality（因子族内去重 + 残差 RS）

- 不简单相加 Trend / Breakout / Momentum / RS。
- `assess_trend_quality()` 内部按 **信息族** 分：Trend / Breakout / Momentum / RS / Volume / Volatility / Structure，
  每个族内取代表性指标，不重复计同源（例如不再把 5D Return / 10D Return / ROC5 / ROC10 全部叠加）。
- `utils/factor_dedup.py` 提供金融口径诊断：
  - `correlation_matrix()`：默认 Spearman（Rank IC 同口径），也可切 Pearson；
  - `vif_table()`：VIF = 1 / (1 - R²)，OLS 回归口径，样本不足 / 完全共线返回 None；
  - `family_dedup_report()`：对全市场 raw factor 输出高相关对、VIF、以及每个因子族的代表性指标建议；
  - `pick_representatives()`：按族取代表性字段。

### 残差 RS

- Residual vs Index：`residual_rs_vs_index_20d/60d` 来自对指数日收益率 OLS 的真实残差，
  `alpha/beta/r2` 一并输出；只有日线数据缺失时才退化为 simple excess，并明确命名为 `excess_rs_vs_index_*`，不再冒充 residual。
- Residual vs Sector：`utils/sector_enrichment.py` 在板块日线数据可用时做个股 vs 板块的 OLS 残差，
  输出 `residual_rs_vs_sector_20d/60d` + beta/alpha/r2；无板块日线时输出 `excess_rs_vs_sector_*`。
- 横截面：`discover()` 会对 `relative_strength_20d/60d`、`residual_rs_vs_index_20d`、`residual_rs_vs_sector_20d`
  计算百分位 rank（`*_pct`），避免把“跟着指数/板块上涨”误当成独立强。

## 简写约定

- `relative_strength_score`：0~100 综合 RS（截面百分位 + 原始相对收益）。
- `residual_rs_vs_*_pct`：残差 RS 的横截面百分位。
- `_factor_family_dedup`：挂在 factor 上的因子族诊断报告（相关矩阵/VIF/代表因子）。


## Layer 4 Sector Engine（Ex-Self 与四层板块因子）

- Sector Trend：`sector_1d_return` / `sector_5d_return` / `sector_10d_return`。
- Sector Momentum：板块 N 日复合收益（`utils.sector_enrichment._lookback_return_from_daily`）。
- Sector Breadth：`上涨家数/下跌家数`，以及剔除本股后的 `sector_breadth_ex_self`。
- Stock vs Sector：`stock_vs_sector_{1,3,5,10}d` 超额收益，`residual_rs_vs_sector_20d/60d` OLS 残差。

`utils.sector_enrichment.compute_ex_self_sector_metrics()` 计算：
- `sector_return_ex_self_1d`：板块1D - 个股1D（剔除本股贡献的近似）
- `sector_return_ex_self_5d`：板块 5D 与个股 5D 复合收益差
- `sector_breadth_ex_self`：(板块上涨家数 - 本股是否上涨) / (板块总家数 - 1)
- `sector_ex_self_status`：枚举 ok / missing

当缺乏板块成分/日线数据时这些字段为 None，系统显示 `Ex-Self 数据缺失`，不会伪造一个假分。

## Layer 5 Catalyst Engine（Catalyst × Price Reaction）

`assess_catalyst()` 使用结构化事件字段：
`event_type/event_level/freshness/company_specific/earnings_impact/credibility/source_quality/price_reaction/expected_return_pct/actual_return_pct/gap_pct/intraday_return_pct`。

关键原则：**不把"次日 Close < Open"直接清零**。
- 若 `expected_return_pct` 与 `actual_return_pct` 存在，计算 `actual/expected`，这是金融上常用的 Price Reaction；
- 若只有实际收益，用门槛分档（+3% 强正 / -5% 强负 / 负收益减分）；
- gap 与 intraday 结构作为辅助；
- 事件质量（event_level、company_specific、credibility、source_quality、earnings_impact）先行计分，再 × 价格反应；
- 没有催化时保持 `catalyst_score=50` 中性，不因为无新闻而否定候选。

## 当前状态说明

以上为当前仓库已落地的实现。仍有一些可延展项未强制：
- Ex-Self 目前用“个股收益近似剔除”与“成分股上涨广度剔除本股”表达，未对全板块市值/权重做精确 decomposing（数据结构限制）；
- Catalyst 的预期收益/实际收益来自 structured input；LLM 尚未统一产出该 JSON 到 factor（现有 prompts 仍是 `catalyst_certainty/market_impact` 风格）。

## Layer 6：T+1 Execution Engine & Risk Budget

### 两阶段执行
- **Phase 1（9:25 Auction Signal）**：竞价先验，只做预判不立即满仓。
- **Phase 2（9:30+ Real-time Confirmation）**：实时检查价格/VWAP/成交量/盘口/指数/板块，满足才 `PHASE2_EXECUTE`。
- 若高开跌破 VWAP 且反抽失败 → `ABANDON` / `CANCEL`。

### 七个执行因子
1. Opening Gap（动态 Gap Penalty = f(Gap, Market Regime, Trend State, Catalyst)）
2. Auction Quality（竞价先验）
3. Index State（市场 Regime）
4. Sector State（Ex-Self 板块不弱）
5. VWAP（价格 >= VWAP 承担）
6. Order Flow（主动买入占比、委比、VWAP 承接、回踩恢复、破低失败）
7. Intraday Price Structure（HH/HL、低点未破、回踩恢复）

### 风险预算定仓位
```
Position = AccountRiskBudget / StopDistance * QualityMultiplier
```
质量乘数来自 Trend Quality、板块/催化、执行确认等；再受最大单股 / 流动性 / 板块 / 市场 Regime 上限约束。绝不为了凑满仓位去买 B/C 级机会。

## Layer 7：持仓状态机

```
ENTRY -> HOLD -> ADD / HOLD / DECAY / REDUCE -> EXIT
```
- **ADD**：只允许“盈利 + 回踩健康 + 重新突破 + 板块/RS 强”的 Pyramiding，不允许亏损补仓。
- **Trend Decay**：创新高频率下降、RS 下降、Sector 转弱、量价背离、ATR 异常放大、VWAP 弱化、市场恶化。
- **双轨退出**：MA20 结构止损（Close<MA20 且次日无法站回）或 ATR trailing stop，任一出即 EXIT。
- **S4 是风险预警**（触发 REDUCE 阈值），只有 S5 / 硬止损 / 严重衰减才 EXIT。

## Tencent 实时行情 + 手动输入
- `utils/tencent_realtime.py`：腾讯 `qt.gtimg.cn` 实时快照（价格、VWAP、买/卖盘口、成交额/量、涨跌）。
- 腾讯失败或关闭时自动使用 `config/manual_realtime.json`（参考模板 `config/manual_realtime.example.json`）/ 环境变量 `REQ_TRADE_MANUAL_REALTIME` 手动输入。
- 启动参数：`execution.use_tencent_realtime: true`、`execution.prefer_realtime: auto`。

### 手动输入 JSON 示例
```json
{
  "600519": {
    "price": 1500,
    "prev_close": 1480,
    "open": 1490,
    "high": 1520,
    "low": 1480,
    "vwap": 1495,
    "bid": 1499,
    "ask": 1501,
    "active_buy_pct": 60,
    "timestamp": "20260822100000"
  }
}
```
