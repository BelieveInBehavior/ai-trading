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
- `data_source/`: 数据源适配器

## 参考文档

- 设计文档: `agent_loop_refactor_design.md`
- 最终方案: `agent_loop_final_recommendation.md`
