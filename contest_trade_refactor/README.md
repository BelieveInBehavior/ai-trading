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

编辑 `config.yaml` 填入必要的 API Keys：
- LLM API (必需)
- 数据源 API (可选)

信号筛选（严格门控，不放宽阈值）：
```yaml
signal_selection_config:
  require_min_buys: 1       # 至少 N 只严格通过门控的买入才停止研究重试
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
设为 `require_min_buys: 0` 可恢复「只跑一轮研究」的旧行为。

买入候选会先检查周线趋势和相对沪深 300 的 20/60 日相对强度，再用日线技术因子确认入场；缺少这些多周期数据时不会通过买入门控。
启用全市场预筛选后，Research Agent 只能研究量化筛选通过的股票；首次扫描会请求全市场历史 K 线，后续运行复用 AkShare 缓存。

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
- `utils/akshare_cache/`、`tools/stock_summary_akshare_cache/`（数据缓存）
- `agents_workspace/results/`、`reports/`、`factors/`、`factor_store/`、`performance/`（运行产物）
- `__pycache__/`、`.venv/`、`.env`

`agents_workspace/factor_thresholds.yaml` 等配置文件仍会正常提交。

## 参考文档

- 设计文档: `agent_loop_refactor_design.md`
- 最终方案: `agent_loop_final_recommendation.md`
