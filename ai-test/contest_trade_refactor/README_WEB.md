# AI Trading System - H5 Responsive Web Interface

基于 FastAPI + WebSocket 的实时交易信号分析 Web 应用。

## ✨ 特性

### 🎨 界面设计
- **左侧 Chatbot**: 控制面板 + 实时进度显示
- **右侧结果面板**: 交易信号和分析结果
- **响应式布局**: 适配桌面、平板、手机
- **实时更新**: WebSocket 推送 agent 执行状态

### 🤖 Agent 状态显示
在聊天消息中实时显示：
- 📊 Data Agent 状态（数据分析）
- 🔍 Research Agent 状态（研究分析）
- ✅ 完成状态和结果统计
- ❌ 错误提示

### 📱 响应式设计
- **桌面**: 左右分栏布局（45% + 55%）
- **平板**: 左右分栏布局（适配窗口）
- **手机**: 上下分栏布局（60% + 40%）

## 🚀 快速启动

### 1. 安装依赖

```bash
# 安装 Web 依赖
pip install -r requirements_web.txt

# 确保已安装项目依赖
pip install -r requirements.txt
```

### 2. 配置

编辑 `config.yaml` 设置 API Keys：

```yaml
llm:
  provider: "openai"  # 或其他 LLM provider
  api_key: "your-api-key"
  model: "gpt-4"
```

### 3. 启动服务器

```bash
python web_app.py
```

服务器将在 http://localhost:8000 启动

### 4. 打开浏览器

访问：http://localhost:8000

## 📖 使用说明

### 启动分析

1. 在输入框中输入触发时间（可选，留空使用当前时间）
2. 点击 "Start Analysis" 按钮
3. 观察左侧聊天面板中的 agent 执行进度
4. 右侧面板会实时显示分析结果

### Agent 状态显示

在聊天消息中，你会看到：

```
🔄 Running market_data_agent...
  📊 market_data_agent
  
✅ market_data_agent completed
  📊 market_data_agent

🔄 Running tech_research_agent...
  🔍 tech_research_agent
  Belief: Focus on technology stocks
  
✅ tech_research_agent completed
  🔍 tech_research_agent
  5 signals found
```

### 结果面板

显示三个主要指标：
- **Data Factors**: 数据因子数量
- **Research Signals**: 研究信号数量  
- **Best Signals**: 最佳信号数量

以及详细的交易信号列表，包括：
- 股票代码和名称
- 买入/卖出建议
- 概率评估
- 证据数量
- 来源 Agent

## 🏗️ 架构说明

### 后端 (web_app.py)

```python
FastAPI + WebSocket
├── WebTradeCompany: 扩展原有 TradeCompany
│   ├── 保留所有原有功能
│   └── 新增实时状态推送
├── ConnectionManager: WebSocket 连接管理
└── REST API: 健康检查等
```

### 前端 (web_interface.html)

```
Single Page Application
├── 左侧聊天面板
│   ├── 系统消息
│   ├── Agent 状态消息
│   └── 输入控制
├── 右侧结果面板
│   ├── 统计摘要
│   └── 信号列表
└── WebSocket 客户端
    ├── 自动重连
    └── 实时消息处理
```

## 🎯 消息类型

### 客户端 → 服务器

```json
{
  "action": "start_analysis",
  "trigger_time": "2024-01-23 09:00:00"
}
```

### 服务器 → 客户端

#### 1. 系统消息
```json
{
  "type": "system",
  "data": {
    "message": "🚀 Starting analysis...",
    "stage": "init"
  }
}
```

#### 2. Agent 启动
```json
{
  "type": "agent_start",
  "data": {
    "agent_type": "data",
    "agent_id": 0,
    "agent_name": "market_data_agent",
    "message": "🔄 Running market_data_agent..."
  }
}
```

#### 3. Agent 完成
```json
{
  "type": "agent_complete",
  "data": {
    "agent_type": "research",
    "agent_id": 0,
    "agent_name": "tech_research_agent",
    "message": "✅ tech_research_agent completed",
    "signals_count": 5
  }
}
```

#### 4. 最终结果
```json
{
  "type": "result",
  "data": {
    "result": {
      "trigger_time": "2024-01-23 09:00:00",
      "data_factors": [...],
      "research_signals": [...],
      "best_signals": [...]
    }
  }
}
```

## 🎨 样式定制

所有样式使用 CSS 变量，方便定制：

```css
:root {
  --primary: #2563eb;      /* 主色调 */
  --success: #10b981;      /* 成功色 */
  --warning: #f59e0b;      /* 警告色 */
  --danger: #ef4444;       /* 错误色 */
  --bg-primary: #ffffff;   /* 主背景 */
  --bg-secondary: #f3f4f6; /* 次背景 */
}
```

## 📱 响应式断点

```css
/* 平板 */
@media (max-width: 1024px) {
  /* 垂直分栏 */
}

/* 手机 */
@media (max-width: 768px) {
  /* 紧凑布局 */
}
```

## 🔧 高级配置

### 修改端口

```python
# web_app.py 最后一行
uvicorn.run(app, host="0.0.0.0", port=8080)  # 改为 8080
```

### 自定义 CORS

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 生产环境部署

```bash
# 使用 Gunicorn + Uvicorn
gunicorn web_app:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

## 🐛 故障排除

### WebSocket 连接失败

检查防火墙设置，确保端口 8000 开放：

```bash
# macOS
sudo lsof -i :8000

# Linux
sudo netstat -tulpn | grep 8000
```

### Agent 执行缓慢

这是正常现象，因为：
- Data Agents 需要抓取数据
- Research Agents 需要调用 LLM
- 多个 Agent 并行执行

可以在 `config.yaml` 中调整：
- 减少 Agent 数量
- 降低 token 限制
- 使用更快的 LLM 模型

### 浏览器兼容性

支持的浏览器：
- ✅ Chrome 90+
- ✅ Firefox 88+
- ✅ Safari 14+
- ✅ Edge 90+

## 📊 性能优化

### 1. 连接池
```python
# 使用连接池复用 LLM 连接
```

### 2. 缓存
```python
# 缓存数据源结果，避免重复请求
```

### 3. 批处理
```python
# 批量处理 WebSocket 消息
```

## 🚀 下一步计划

- [ ] 添加历史记录查看
- [ ] 导出结果为 PDF/Excel
- [ ] 多用户支持和认证
- [ ] 实时图表展示
- [ ] 信号回测功能
- [ ] 邮件/通知推送

## 📝 开发日志

### 2026-08-07
- ✅ 创建 H5 响应式 Web 界面
- ✅ 实现 WebSocket 实时通信
- ✅ 在聊天消息中显示 Agent 状态
- ✅ 左右分栏布局（桌面）
- ✅ 上下分栏布局（移动端）
- ✅ 实时结果展示

## 📄 License

与主项目相同

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！
