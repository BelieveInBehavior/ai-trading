# ContestTrade Refactor - Agent Loop + Pipeline

重构后的 ContestTrade 项目，使用正确的架构模式：
- **ResearchAgent**: Agent Loop Pattern (动态决策)
- **DataAnalysisAgent**: Pipeline Pattern (固定流程)
- **TradeCompany**: Simple Async Orchestration

## 项目结构

```
contest_trade_refactor/
├── agents/
│   ├── base_agent_loop.py          # Agent Loop 基础框架
│   ├── research_agent_loop.py      # Research Agent (Loop 模式)
│   ├── data_analysis_pipeline.py   # Data Analysis Agent (Pipeline 模式)
│   └── prompts.py                  # Prompt 模板
├── config/                         # 配置文件
├── models/                         # LLM 模型封装
├── tools/                          # 工具集 (搜索、股票信息等)
├── utils/                          # 工具函数
├── data_source/                    # 数据源
├── main_loop.py                    # 主入口（简化版）
├── config.yaml                     # 配置文件
└── test_refactor.py               # 测试脚本

```

## 安装依赖

```bash
cd contest_trade_refactor
pip install -r requirements.txt
```

## 配置

**敏感信息（API Key、模型地址等）一律放在 `.env`，不要写入 `config.yaml`。**

```bash
cp .env.example .env
# 编辑 .env 填入 LLM、Tushare、豆包搜索等密钥
```

项目启动时会自动加载根目录 `.env`（`start_web.sh` 也会 `source` 它）。

| 环境变量 | 说明 |
|---------|------|
| `CONTEST_TRADE_MARKET` | `CN-Stock`（默认）或 `US-Stock` |
| `LLM_PROVIDER` / `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL_NAME` | 主 LLM |
| `LLM_THINKING_*` | 思考模型（留空则复用 `LLM_*`） |
| `VLM_*` | 视觉模型（留空则复用 `LLM_*`） |
| `TUSHARE_KEY` | Tushare 数据 |
| `JQDATA_USERNAME` / `JQDATA_PASSWORD` | [聚宽 JQData](https://www.joinquant.com/help/api/doc?name=JQDatadoc)（手机号 + 官网登录密码） |
| `JQDATA_ACCOUNT_TYPE` | `formal`（默认，全量历史含最近交易日）或 `trial` |
| `CN_MARKET_DATA_PROVIDER` | 正式会员推荐 **`jqdata`**；`akshare` 仅作备用 |
| `VOLC_WEB_SEARCH_API_KEY` | [豆包搜索](https://docs.volcengine.com/docs/87772/2272949?lang=zh) |
| `BOCHA_KEY` / `SERP_KEY` | 搜索备用源 |
| `FMP_KEY` / `FINNHUB_KEY` / `POLYGON_KEY` / `ALPHA_VANTAGE_KEY` | 美股数据源 |

`config.yaml` 只保留 Agent 列表、信号门控阈值等非敏感业务配置；**不含任何 API Key 或模型凭证**（全部由 `config/config.py` 从 `.env` 注入）。

首次运行或缺少股票映射缓存时，会自动从 AkShare 生成 `utils/cache/market_manager/stock_basic_cache.json` 与 `namechange_data.json`。

**JQData（正式会员）**：`.env` 填入手机号、聚宽登录密码，并确认：

```bash
JQDATA_ACCOUNT_TYPE=formal
CN_MARKET_DATA_PROVIDER=jqdata
```

正式账号：**2005 至今全量 K 线（含最近交易日）**，日流量 2 亿条，全市场预筛可直接跑。AkShare 仅在 JQData 请求失败时 fallback。

验证：

```bash
PYTHONPATH=. python - <<'PY'
from utils.jqdata_utils import ensure_jqdata_auth, is_jqdata_trial_account
from utils.cn_price_provider import get_stock_zh_a_hist
print("auth:", ensure_jqdata_auth())
print("trial:", is_jqdata_trial_account())  # 应为 False
df = get_stock_zh_a_hist("600519", "20260801", "20260811", adjust="qfq")
print("bars:", len(df), "last:", df["日期"].iloc[-1] if len(df) else None)
PY
```

AkShare 结构化数据缺失时，各 Data Agent 会自动触发**豆包联网搜索**补充（融资融券、北向、龙虎榜、大宗等）；另有 `web_search_market_supplement_agent` 做通用市场信息补充。K 线历史数据仍走 AkShare/腾讯，失败则跳过该标的（不做 Yahoo 回退）。

信号筛选（严格门控，不放宽阈值）：
```yaml
signal_selection_config:
  require_min_buys: 0         # 默认只跑一轮研究，不做“没票硬凑”
  max_research_rounds: 10   # 最多重跑研究阶段轮次（防止无限循环）
  reject_future_evidence: true  # 拒绝分析时点之后的证据
  risk_veto_enabled: true      # 开启硬风险和数据质量 veto
  consensus_enabled: true      # 启用多研究 Agent 的确定性共识
  consensus_method: weighted_majority
  consensus_require_majority: true
  multi_timeframe_enabled: true       # 周线定方向、相对强度选股、日线找买点
  relative_strength_benchmark: sh000300 # 相对沪深300计算20/60日超额收益
  min_weekly_trend_score: 55
  min_relative_strength_score: 50
  min_relative_strength_20d_pct: 0
  min_daily_entry_score: 50
  quantitative_screen_enabled: true
  quantitative_screen_fail_open: false
  quantitative_screen_max_symbols: 0  # 0 = 扫描全部股票
  quantitative_screen_top_k: 80
  quantitative_screen_concurrency: 8
  quantitative_screen_history_days: 260
```
默认已改为 `require_min_buys: 0`，即只跑一轮研究，不再“没买到就强制重试”，避免制造假阳性信号。

买入候选会先检查周线趋势和相对沪深 300 的 20/60 日相对强度，再用日线技术因子确认入场；缺少这些多周期数据时不会通过买入门控。
启用全市场预筛选后，Research Agent 只能研究量化筛选通过的股票；首次扫描会请求全市场历史 K 线，后续运行复用 JQData/AkShare 磁盘缓存。



### 盘后 / 周度报告脚本

```bash
# 1) 只做评估+写报告（不跑 pipeline）
.venv/bin/python scripts/post_market_quant_report.py --date 2026-08-14

# 2) 先跑 pipeline 再评估
.venv/bin/python scripts/post_market_quant_report.py --run-pipeline --strategy momentum

# 3) walk-forward 因子验证（需要更多成熟样本才有意义）
.venv/bin/python scripts/walk_forward_validation.py \
  --input agents_workspace/backtest_results/signal_performance.csv
```

组合模拟也可直接从原始 trade_decision 触发，自动先生成信号 CSV：

```bash
.venv/bin/python scripts/portfolio_simulator.py \
  --decision-glob 'agents_workspace/results/trade_decisions/*.json' \
  --include-consensus --holding-days 3
```

### 当前建议配置
- `require_min_buys: 0` 已改为默认：只跑一轮，不做“没票硬凑”。
- 用 `--include-watch` / `--include-research` / `--include-consensus` 做敏感性测试，但真实交易应只信任通过门控的 `buy_passed`。


### 历史回放（尽量不让 LLM 看见未来）

```bash
# 先跑小范围、小股票池冒烟，避免过多 LLM 调用
.venv/bin/python scripts/replay_historical_no_future.py \
  --start-date 2026-08-11 --end-date 2026-08-12 \
  --strategy momentum \
  --symbols-limit 10 \
  --output-dir agents_workspace_replays/historical_no_future

# 只审计已有 trade_decision 是否存在未来数据
.venv/bin/python scripts/audit_future_leak.py \
  --glob 'agents_workspace/results/trade_decisions/*.json' \
  --output agents_workspace/backtest_results/audit
```

说明：
- `CONTEST_TRADE_ASOF_DATE` 环境变量会让 `get_stock_zh_a_hist` 默认把 K 线 end 限制在触发日，从价格层面降低未来泄漏。
- 审计脚本会扫描 `report_date`、`pub_time`、`analysis_as_of_date` 等字段，挑出超过触发时间的时间戳。
- 目前对已有数据的审计发现：`2026-08-08` 的一个报告里 `report_date=20260810`，说明历史生成结果里已存在未来泄漏，需要重建历史回放或用审计结果过滤。

> ⚠️ 极限：这只能减少“价格/显式时间戳”的未来泄漏，不能完全阻断：
> - 新闻/公告数据源可能未按 trigger_time 过滤
> - LLM 世界知识可能知道历史结果
> - 缓存/报告文件可能用了当前时间

## 量化回测闭环（新）

把 Agent 产生的信号变成可验证的前向收益 / 组合模拟，避免“只选不验”。

```bash
# 1) 用历史 trade_decisions 计算 T+1/T+3/T+5 前向收益
.venv/bin/python scripts/backtest_signal_closed_loop.py \
  --glob 'agents_workspace/results/trade_decisions/*.json' \
  --horizons 1,3,5

# 2) 组合模拟（含手续费、滑点、止损/止盈、按 tier 仓位）
.venv/bin/python scripts/portfolio_simulator.py \
  --include-watch --include-research --holding-days 5
```

输出目录：`agents_workspace/backtest_results/`
- `signal_performance.csv`: 已成熟（至少 T+1 收盘价存在）的信号 + 前向收益
- `signal_performance_pending.csv`: 尚未有足够未来数据、等待后续天数 pass 后补评估的信号
- `threshold_ic_candidates.csv`: 初步 IC / 分位收益，用于逐步校验阈值
- `portfolio_trades.csv` / `portfolio_equity.csv` / `portfolio_summary.md`: 组合模拟结果

> 注意：目前 `signal_performance.jsonl` 同时保留成熟与 pending，便于后续续跑。

## 运行测试

```bash
# 测试完整流程
python test_refactor.py

# 单独测试 Pipeline
python -c "
import asyncio
from agents.data_analysis_pipeline import DataAnalysisPipeline

async def test():
    pipeline = DataAnalysisPipeline(
        agent_name='test',
        source_list=['data_source.sina_news.SinaNews']
    )
    result = await pipeline.run('2024-01-23 09:00:00')
    print(result['context_string'][:200])

asyncio.run(test())
"

# 单独测试 Loop
python -c "
import asyncio
from agents.research_agent_loop import ResearchAgentLoop, ResearchAgentLoopConfig, ResearchAgentInput

async def test():
    config = ResearchAgentLoopConfig(
        agent_name='test',
        belief='Focus on tech stocks',
        max_iterations=3
    )
    agent = ResearchAgentLoop(config)
    result = await agent.run(ResearchAgentInput(
        trigger_time='2024-01-23 09:00:00',
        background_information='<market_information>Test</market_information>'
    ))
    print(result.final_result[:200])

asyncio.run(test())
"
```

## 全市场 Pipeline 重跑

```bash
source .venv/bin/activate
./scripts/start_pipeline_rerun.sh
# 或手动：
PYTHONUNBUFFERED=1 PYTHONPATH=. nohup python -u scripts/run_pipeline_rerun.py \
  >> logs/pipeline_rerun.log 2>&1 &
echo $! > logs/pipeline_rerun.pid
tail -f logs/pipeline_rerun.log
```

`scripts/run_pipeline_rerun.py` 会开启 Stage 0 全市场预筛（`max_symbols=0`，约 5000 只）。Stage 0 历史 K 线使用稳定磁盘缓存，跨小时不会重复拉取。

AkShare K 线拉取失败时不再回退 Yahoo（避免 `YFRateLimitError`），该股票在预筛中跳过；市场类 Data Agent 在 AkShare 失败时会自动用豆包联网搜索补充。

## 架构对比

### 原版 (LangGraph)
```python
# 需要定义 StateGraph、节点、边
workflow = StateGraph(State)
workflow.add_node("step1", func1)
workflow.add_node("step2", func2)
workflow.add_edge("step1", "step2")
...
```

### 重构版 (Loop + Pipeline)
```python
# Pipeline: 简单的函数调用
async def run(trigger_time):
    data = await fetch_data()
    batches = await process_batches()
    return await merge_results()

# Loop: 显式循环
async def run(input_data):
    while not should_terminate():
        tool = await select_tool()
        result = await execute_tool(tool)
    return await finalize()
```

## 核心改进

1. **代码减少 30%**
   - 去除 LangGraph 抽象层
   - 更直接的控制流

2. **更清晰的架构**
   - Loop 归 Loop (动态决策)
   - Pipeline 归 Pipeline (固定流程)

3. **更易维护**
   - 每个文件职责单一
   - 逻辑一目了然

4. **完全兼容**
   - 输入输出格式不变
   - 所有工具和数据源完全兼容

## 文件说明

### 核心文件

- `base_agent_loop.py`: Agent Loop 框架基类
- `research_agent_loop.py`: 研究 Agent，使用 ReAct Loop
- `data_analysis_pipeline.py`: 数据分析 Agent，使用 Pipeline
- `main_loop.py`: 主编排逻辑

### 支持文件

- `config/`: 配置管理
- `models/`: LLM 封装
- `tools/`: 金融工具集
- `utils/`: 辅助函数
  - `system_health_utils.py`：仅统计真实 tool/数据源失败，忽略「无法交易」等风控表述
- `data_source/`: 数据源适配器
  - akshare 日期参数需使用 `YYYYMMDD`（见 `utils/date_utils.normalize_trade_date_compact`）

## Git 提交说明

仓库根目录 `.gitignore` 已排除以下内容，**请勿手动 `git add`**：

- `frontend/node_modules/`、`frontend/.next/`（前端依赖与构建缓存）
- `utils/akshare_cache/`、`utils/jqdata_cache/`、`tools/stock_summary_akshare_cache/`（数据缓存）
- `__pycache__/`、`.venv/`、`.env`

`agents_workspace/` 下的配置与运行数据（如 `factor_thresholds.yaml`、因子结果、回测报告等）会正常提交。

## 参考文档

- 设计文档: `agent_loop_refactor_design.md`
- 最终方案: `agent_loop_final_recommendation.md`

## 双交易策略（Agent 风格）

系统目前内置两套独立选股 Agent 风格（前端可切换）：

| 策略 | 定位 | 量化预筛 | 买点门控 |
|------|------|---------|--------|
| `swing` 中长线 / 趋势交易 | 趋势确认 + 回踩 20 日线，不追高 | MA20 偏离 ≤ 6%，前日涨幅 ≤ 5%，对偏离大扣分 | MA20 偏离 ≤ 6%，前日涨幅 ≤ 5%，要求风险报酬比更高 |
| `momentum` 短期收益 / 动量交易 | 最热主线、强资金共识、高弹性，严格止损 | MA20 偏离 ≤ 45%，前日涨幅 ≤ 15%，允许强者占优 | MA20 偏离 ≤ 45%，前日涨幅 ≤ 14%，容忍强趋势并加强动量分 |

核心差异：中长线把“已经涨很多、靠近 20 日线很远”的追高票在 Stage 0 就尽量拦掉；短期策略则留着高动量主线候选，但通过止损纪律和最终门控控制风险。

切换方式：
- Web 界面左下角选择“中长线/趋势”或“短期收益”。
- 命令行：`scripts/run_pipeline_rerun.py --strategy swing` / `--strategy momentum`。
- API：`POST /api/start {"strategy":"swing"}`；`GET /api/strategies` 获取策略详情。
