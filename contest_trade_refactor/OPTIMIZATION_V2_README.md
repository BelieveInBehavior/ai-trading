# AI交���系统���化方案 v2.0

## 已完成���核心改进

### ✅ ���段1：信���分级系���（���决"过度保守"问题）

#### 1. 信号分级器 (`agents/signal_tier_classifier.py`)

**���能：**���候选���票分为A/B/C三个等级，对应���同���位策���

**分级���准���**

- **A级信���（高确定���）**
  - 综合���≥70，置���度≥75
  - 周线≥60，相对���度≥55，日���≥55
  - ���主要催���剂 或 ���化剂���≥60���资���流≥60
  - MA20偏���≤8%，���日涨幅���5%
  - **建议仓位：15%**

- **B级���号（���准）**
  - 综合���≥60，置信度���60
  - 周线≥55，相对���度≥50，日线���50
  - MA20偏离≤12%，���日���幅≤6%
  - **建���仓位：8%**

- **C级信号（���察）**
  - 综合分���50，���信度���50
  - 周���≥50，相对强度≥45
  - MA20偏���≤15%
  - **建议仓位：5%（或仅���察）**

**优���：**
- 不���"���刀切"���允许不���质���的信号共存
- ���低���整体���槛���震荡市也能选���标的
- ���位管理自动���，高质���信号���仓

#### 2. 市场环���识别��� (`agents/market_regime_detector.py`)

**功能：**自动判断当前市���状态（牛市/震���/熊市���

**���断维���：**
- 市场趋���（market_trend: up/neutral/down）
- 风险情绪（risk_sentiment: risk_on/neutral/risk_off）
- 指数技术面（均线排���、近���涨跌幅���
- 资���流向数据可���性

**动态调整策���：**
- **���市：**���低门槛5分，允许MA20���离+3%，���涨幅度+2%
- **震荡：**保持标准门���
- **熊市：**提高门槛10分，只���最强标的���要求���金���确认

**示例输出：**
```
市场环境识别: bull (���信度: 72.5%)
判断依据:
  - ���场趋势���上
  - 风险偏好积极
  - 指数10日涨幅5.3%
```

#### 3. ���流程集成 (`main_loop.py`)

**已完成：**
- ���入新模块：`SignalTierClassifier`, `MarketRegimeDetector`, `SignalTracker`
- 修改`_select_signal_groups`方���，集成���场环境识别和���号分���

**新的选股流���：**
```
1. 市场环境识别 → regime (bull/neutral/bear)
2. ���识聚合 ��� consensus_signals
3. 排���打分 → ranked_signals
4. 信号���级 → tier_A, tier_B, tier_C, tier_reject
5. 构建���入���表 → A+B���信号
6. 构建观察列��� → C级 + watch���号
```

### ✅ 阶段2：���测与验证���统（���决"纸上谈兵"问题）

#### 4. 信号���踪器 (`utils/signal_tracker.py`)

**功能���**记录每个信号���后续���现，验证策略有效性

**核心方法：**

1. **记录信号** (`record_signals`)
   ```python
   tracker.record_signals(
       signals=buy_signals,
       trigger_time="2024-01-23 09:00:00",
       metadata={"market_regime": "bull", "regime_confidence": 72.5}
   )
   ```
   自动保���到：`agents_workspace/signals_tracking/signal_performance.jsonl`

2. **更新表现** (`update_performance`)
   ```python
   tracker.update_performance(
       symbol_code="600519.SH",
       trigger_time="2024-01-23 09:00:00",
       performance_data={
           "entry_price": 1850.0,
           "t1_return_pct": 2.5,
           "t3_return_pct": 4.2,
           "t5_return_pct": 6.8,
           "max_gain_pct": 8.1,
           "max_loss_pct": -1.2,
       }
   )
   ```

3. **生���统计摘���** (`get_performance_summary`)
   ```python
   summary = tracker.get_performance_summary(days_back=30)
   ```

**���出示例：**
```json
{
  "total_signals": 45,
  "tracked_signals": 45,
  "by_tier": {
    "A": {
      "count": 12,
      "avg_t1_return": 3.2,
      "avg_t5_return": 7.8,
      "win_rate_t1": 75.0,
      "win_rate_t5": 83.3,
      "sharpe_ratio": 1.85
    },
    "B": {
      "count": 18,
      "avg_t1_return": 1.8,
      "avg_t5_return": 4.5,
      "win_rate_t1": 61.1,
      "win_rate_t5": 66.7,
      "sharpe_ratio": 1.12
    },
    "C": {
      "count": 15,
      "avg_t1_return": 0.5,
      "avg_t5_return": 2.1,
      "win_rate_t1": 53.3,
      "win_rate_t5": 60.0,
      "sharpe_ratio": 0.67
    }
  },
  "probability_calibration": {
    "slope": 0.88,
    "intercept": 0.05,
    "sample_size": 45
  }
}
```

**概���校准：**
- 系统会���动分���"预测���率 vs 实���胜率"的���差
- ���成校���参数：`calibrated_prob = raw_prob * 0.88 + 0.05`
- ���以将校���参数���入 `agents_workspace/models/probability_calibration.json`

### ✅ 阶段3：���态出场���辑（解决"只���不卖"问���）

#### 5. 出场管理��� (`agents/exit_manager.py`)

**功能：**根据技���指标���资金���向、盈亏情况���态决定���损/���盈

**核心���辑���**

1. **分���止损/���盈**
   - A级：���损-10%，止���+18%���让利润���跑）
   - B级：止损-8%，���盈+15%
   - C���：���损-6%，止盈+12%���快速落���为安）

2. **移���止损**
   - 盈利超过8%时启���
   - 从最高点回撤5%���触发

3. **技���面恶���检测**
   - MA20空���排列（-5%以下）��� +15分
   - 相���强度转���（<45���→ +10分
   - 周线���势转弱（<50）→ +10分
   - 温斯坦Stage 3/4 → +15���

4. **市场环���恶化**
   - ���场趋势���弱 ��� +10���
   - 风险情绪���避险 ��� +10分

5. **持���时间过长**
   - 超���20个���易日 → 每���+0.5分

**使用示���：**
```python
from agents.exit_manager import ExitManager

manager = ExitManager()

# 评���单个持���
evaluation = manager.evaluate_position(
    position={
        "symbol_code": "600519.SH",
        "entry_price": 1850.0,
        "entry_date": "2024-01-15",
        "signal_tier": "A",
        "highest_price": 1995.0,
    },
    current_price=1920.0,
    technical_factor={...},
    market_context={...}
)

if evaluation["action"] == "sell":
    print(f"建议卖���：{evaluation['reason']}")
    print(f"出场得分���{evaluation['exit_score']}")
    print(f"���前收���：{evaluation['current_return_pct']}%")
```

**输���示���：**
```
建议卖出���移动止损���发，���最高���1995.00回撤3.8% | ���术面恶���评分+12.0
出场得���：52.0
���前���益：+3.8%
紧急程度���urgent
```

---

## ���用指南

### 1. ���成到现有系统

由于字符编���问���，���要手动���成最后���集成步骤：

#### 步���1：在 `main_loop.py` ��� `__init__` 方���中添加

在第387-389���后面添加：
```python
# ���增：信号跟踪器（用于回���验证）
from utils.signal_tracker import SignalTracker
self.signal_tracker = SignalTracker(self.workspace_dir)
```

#### ���骤2：在 `run` 方���中���录信号

在生成best_signals后���加���
```python
# 记录信���用���后续跟踪
if best_signals:
    self.signal_tracker.record_signals(
        signals=best_signals,
        trigger_time=trigger_time,
        metadata={
            "market_regime": selection_groups.get("market_regime"),
            "regime_confidence": selection_groups.get("regime_confidence"),
        }
    )
```

### 2. ���看优化效果

#### 运行一次完整流程
```bash
python main_loop.py
```

���会看到���增的���出：
```
市场���境识���: bull (���信度: 72.5%)
  - 市场趋���向���
  - 风险偏好积极

============================================================
信号���级结果
============================================================

A���信号 (2个):
  1. 贵州茅台(600519.SH) | 分数72.3 | 置信���78.5 | 建议仓位15.0%
     理由: 综���分72.3+置信度78.5 | 周���62.1/RS58.3/日线55.7 | 主要催化���确认

B级信号 (3个):
  2. 宁德���代(300750.SZ) | 分数65.2 | 置信度65.8 | 建议���位8.0%
  ...

C级信号 (2个):
  ...
```

#### ���看历���信号���现
```python
from utils.signal_tracker import SignalTracker

tracker = SignalTracker()
summary = tracker.get_performance_summary(days_back=30)

print(f"总信号数���{summary['total_signals']}")
print(f"A级胜���：{summary['by_tier']['A']['win_rate_t5']}%")
print(f"B级平均���益：{summary['by_tier']['B']['avg_t5_return']}%")
```

### 3. 评���持仓���场

```python
from agents.exit_manager import ExitManager
from data_source.price_market_akshare import get_latest_price
from data_source.technical_indicators_akshare import compute_stock_technical_factor

manager = ExitManager()

# 假设有3个持仓
positions = [
    {"symbol_code": "600519.SH", "entry_price": 1850, "entry_date": "2024-01-15", "signal_tier": "A"},
    {"symbol_code": "300750.SZ", "entry_price": 175, "entry_date": "2024-01-18", "signal_tier": "B"},
    {"symbol_code": "600036.SH", "entry_price": 42.5, "entry_date": "2024-01-20", "signal_tier": "C"},
]

# ���取当前价���和技术���子
prices = {pos["symbol_code"]: get_latest_price(pos["symbol_code"]) for pos in positions}
factors = {pos["symbol_code"]: compute_stock_technical_factor(...) for pos in positions}

# 批���评估
evaluations = manager.batch_evaluate_positions(
    positions=positions,
    prices=prices,
    technical_factors=factors,
    market_context=market_context,
)

# 打印报告
print(manager.format_exit_report(evaluations))
```

---

## 优化���果���期

### 解决的核心问题

| 问题 | 优化前 | 优化后 |
|------|--------|--------|
| 选不���标的 | 10+个���格门槛，���荡市选不出 | 分级���统���降低整���门槛 |
| 市场适���性 | 固定门槛，牛熊不��� | ���态调���，牛市���宽/熊市收紧 |
| 仓位管理 | 所���信号统一仓位 | A级15%/B���8%/C级5% |
| 策略���证 | 无���测���据 | 自���跟踪30天表现+统���分析 |
| 概���校准 | raw_prob×0.92+0.03（硬编码） | 基于实际数据动态校准 |
| 出场策略 | 无 | ���级止损+移动止���+技术恶化检测 |

### 预期改进

1. **���股数���：**���平均2-3个 ��� 5-8个（A+B级）
2. **胜率提升：**
   - A级信号：预期T+5胜率70-80%
   - B级信号：预期T+5胜率60-70%
   - C级信���：预���T+5胜���50-60%
3. **风险控制：**
   - 动态止损避���大���回撤
   - ���动止���锁定利���
   - ���术���化主动退���
4. **策���迭代：**
   - 30天后有���实表现���据
   - 可以调���分级门槛
   - 优化���率���准参数

---

## ���续优化���议

### 短期（1周内���

1. **���成���成**：手���添加上���代码到main_loop.py
2. **运行���试**：跑一次完整���程，检查���出是否���常
3. **记录信���**：���证每次���行都记录信号到tracker

### ���期（2-4周）

1. **收集数���**：累积30个交���日���信号表���数据
2. **分���结���**：
   ```python
   summary = tracker.get_performance_summary()
   print(json.dumps(summary, indent=2, ensure_ascii=False))
   ```
3. **调���参���**：
   - 如���A级胜率<70%，提高A级���槛
   - ���果整体选股数<3个，降低B/C级门槛
   - 更新概率校准参���

### 长期（持���优化）

1. **���加出���信号跟踪**：记录每次出场���策的���效���
2. **优化市场环境���断**���接���真实指数数据（���前只用market_context）
3. **多策略���合**���
   - 趋���跟踪策���（当���）
   - 均值���归���略（���增���
   - 事件驱动策略（���增���
4. **���器学���增强**：
   - 用���史数���训练���号分级模型
   - ���XGBoost替代规则���分

---

## 常见问题

### Q1: 为���么还是选���出标的？

**检���：**
1. 量化筛选是否���功？看`Stage 0 progress`日志
2. 市���环境判断是否正确���看`市���环境���别`输���
3. 信号分级是否有C级���如果连C级都没���，���明整体���场没���符���条件的股票

**调整：**
```python
# 临时���低门槛���试
# 在 agents/signal_tier_classifier.py 的 _classify_single ���法中
# ��� C 级门槛从 score >= 50 改为 score >= 45
```

### Q2: 如何���动触发信号���踪更新？

```python
from utils.signal_tracker import SignalTracker
from data_source.price_market_akshare import get_stock_price_range

tracker = SignalTracker()
recent_signals = tracker.get_recent_signals(days=7)

for signal in recent_signals:
    if signal["performance"]["tracked"]:
        continue
    
    code = signal["symbol_code"]
    entry_date = signal["trigger_time"][:10]
    
    # 获取���续���格
    prices = get_stock_price_range(code, entry_date, days=5)
    
    # 计算���现
    performance = calculate_performance(signal["entry_price"], prices)
    
    # 更新
    tracker.update_performance(code, signal["trigger_time"], performance)
```

### Q3: 如何导出���据���于Excel分���？

```python
import pandas as pd

# 读取所有跟踪记录
records = []
with open("agents_workspace/signals_tracking/signal_performance.jsonl") as f:
    for line in f:
        records.append(json.loads(line))

df = pd.DataFrame(records)
df.to_excel("signal_performance.xlsx", index=False)
```

---

## 总结

这个优化版本���决了原���统���三大核心问题：

1. **过���保守** → 信号分���系统，允许���同质量共存
2. **纸上���兵** → 信号跟���器，用真���数据验证策略
3. **只买不卖** → 出场管���器���动态止���止���

**关���改进���**
- 从"一刀切"到"分���管理"
- 从"固���门���"到"���态适应"
- 从"理���推���"到"数据驱动"

**下一步：**
1. 完成最后的代���集成
2. 运行30天收���数���
3. ���据���际表现调优参数

Good luck! 🚀
