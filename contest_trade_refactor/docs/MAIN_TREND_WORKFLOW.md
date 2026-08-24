# 主升浪持仓状态 + 页面展示 + 通知

## 目标

T 日跑完系统后，候选股票直接显示在页面上；
T+1 日 9:30 前跑一次数据，
之后每天更新这些股票的 HOLD / REDUCE / SELL 状态，并通知到手机/群。

## 一、页面

打开前端后顶部有“主升浪持仓”入口，或直接访问：

```
http://localhost:3000/main_trend
```

页面数据来自后端：

- `GET /api/main_trend/dashboard`：聚合 T日候选 / T+1执行 / 持仓 / 退出状态
- `GET /api/main_trend/holdings?date=YYYYMMDD`
- `GET /api/main_trend/exit_decisions?date=YYYYMMDD`
- `GET /api/main_trend/candidates?date=YYYYMMDD`

## 二、日常运行

### T日：出候选

```bash
.venv/bin/python scripts/main_trend_tday_report.py \
  --result agents_workspace_main_trend/<T日>/result.json
```

会生成 `tday_pool.json`，页面“T日候选”自动读取最新目录。

### T+1 9:30前：跑执行数据 / 生成初始持仓

手工 6 字段快照放到 `config/manual_execution_<T+1>.json`（含 names 字段）。

```bash
.venv/bin/python scripts/main_trend_t1_execute.py \
  --tday agents_workspace_main_trend/<T日>/tday_pool.json \
  --manual config/manual_execution_<T+1>.json
```

把 BUY 固化为持仓：

```bash
.venv/bin/python scripts/main_trend_holdings.py \
  --date <T+1> \
  --tday agents_workspace_main_trend/<T日>/tday_pool.json \
  --t1 agents_workspace_main_trend/<T日>/t1_execution.json \
  --init
```

也可以在指定输出目录写入：

```bash
.venv/bin/python scripts/main_trend_holdings.py --date <T+1> --init
```

### T+2 起：每个交易日收盘/盘后更新状态

```bash
.venv/bin/python scripts/main_trend_holdings.py \
  --date <T+1次日> \
  --holdings agents_workspace_main_trend/<T+1>/holdings.json \
  --prices config/manual_execution_<T+1次日>.json \
  --update
```

会：

1. 读取持仓文件
2. 用 `strategies/main_trend/engine.evaluate_exits()` 跑退出状态机
3. 写 `exit_decisions.json`
4. 合并最新状态写回 `holdings.json`
5. 页面刷新后自动更新

## 三、通知

在 `strategies/main_trend/strategy.yaml` 配置：

```yaml
notify:
  enabled: true
  type: generic   # generic / dingtalk / serverchan
  webhook_url: "https://your.webhook.example/send"
```

或环境变量：

```bash
export MTF_NOTIFY_WEBHOOK_URL="https://your.webhook.example/send"
export MTF_NOTIFY_ENABLED=1
```

然后运行更新时加 `--notify`：

```bash
.venv/bin/python scripts/main_trend_holdings.py \
  --date 20260825 \
  --holdings agents_workspace_main_trend/20260824/holdings.json \
  --prices config/manual_execution_20260825.json \
  --update --notify
```

默认只在有 SELL / REDUCE 时发送；调试可用 `--notify-all --dry-run-notify` 打印内容不实际发送。

## 四、退出状态机（与 T+3/T+5 短线分开）

| 优先级 | 状态 | 退出条件 |
|---|---|---|
| P0 | SELL_NOW | Catalyst=EXTREME / 极端事件 |
| P1 | SELL_CONFIRM | Close<MA20 且前一日也<MA20（连续2日） |
| P2 | SELL_TRAILING | Close < Highest_Close - max(6%, 2×ATR%) |
| P3 | REDUCE | 高位放量滞涨等衰减信号 ≥2 |
| P4 | HOLD | 以上全否；可能带 DECAY 提示 |

配置文件在 `strategies/main_trend/strategy.yaml → holding.exit`。

## 五、目录约定

```
agents_workspace_main_trend/
  20260821/
    result.json
    tday_pool.json          # T日候选
    t1_execution.json       # T+1 执行
  <T+1>/
    holdings.json           # 持仓状态
    exit_decisions.json     # 当日退出决策
```

## 六、实时监控 / 收盘前自动检查

### 1. 页面实时收益

点击主升浪页面右上角 **「实时收益」**：
- 后端会调用腾讯财经接口拉取当前持仓最新价
- 返回整体平均收益、SELL / REDUCE 数量
- 不写文件、不落库，只临时展示

### 2. 命令行实时监控

```bash
# 只检查并打印（不写文件）
.venv/bin/python scripts/main_trend_realtime_monitor.py

# 检查并发送通知
.venv/bin/python scripts/main_trend_realtime_monitor.py --notify
```

### 3. 收盘前自动状态更新（建议每天 14:50）

```bash
./scripts/main_trend_preclose_monitor.sh --notify
```

等价于：
```bash
.venv/bin/python scripts/main_trend_realtime_monitor.py --write-back --notify
```

如果你要用系统定时任务（macOS launchd），可参考：

```
0 50 14 * * 1-5  cd /Users/ruby/Desktop/ai-trading/contest_trade_refactor && ./scripts/main_trend_preclose_monitor.sh --notify
```
