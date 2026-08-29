# Market Data Architecture

本文档定义 `contest_trade_refactor` 的真实行情数据存储架构。目标是把“策略代码”和“生产级市场数据”彻底分层：代码进 Git，真实数据落本地目录，并通过 OSS 做备份与共享。

## 1. 设计目标

- 策略会持续变化，但历史行情是可复用的公共资产
- 不把大体量真实行情文件提交到普通 Git
- 本地运行路径稳定，策略层不感知 OSS 细节
- 支持后续从单机扩展到 NAS / 对象存储 / DVC
- 尽量避免未来因为数据重算、覆盖、历史膨胀而拖慢仓库

## 2. 分层原则

### 2.1 Git 主仓库 `ai-trading`

主仓库负责：

- 策略代码
- 回测脚本
- 数据抓取逻辑
- 数据结构定义
- 数据质量检查
- 数据同步脚本
- 文档

主仓库不负责：

- 真实日线 / 分钟线 / Tick 数据文件
- 长期累积的生产级缓存
- 每日持续增长的大体量行情快照

### 2.2 Submodule `market-data`

当前已接入：

- 上游仓库：`https://github.com/BelieveInBehavior/market-data.git`
- 接入位置：`contest_trade_refactor/market-data`

这个 submodule 只建议管理：

- 抓取程序
- schema / manifest
- 质量校验规则
- 小型测试样本
- 数据迁移脚本

不建议放入：

- 大体量真实行情文件
- 高频增量更新文件
- 每日回写的大 parquet / pickle / csv

### 2.3 本地真实数据目录

真实行情数据以本地目录为主存储，策略运行只访问本地目录。

推荐通过环境变量指定：

```bash
CN_MARKET_BAR_STORE=1
CN_MARKET_BAR_STORE_DIR=/absolute/path/to/local-market-data/bar_store
```

如果未配置 `CN_MARKET_BAR_STORE_DIR`，当前代码会回落到：

```text
utils/cache/market_bars/
```

开发环境可用这个默认值，但长期建议把真实数据迁出仓库目录。

### 2.4 OSS 远端镜像

OSS 的角色是：

- 备份
- 多机共享
- 灾难恢复

OSS 不是策略运行时的主读写入口。默认流程应是：

1. 策略读写本地目录
2. 收盘后或人工触发同步到 OSS
3. 需要恢复时，再从 OSS 拉回本地

## 3. 当前落地形态

### 3.1 代码入口

当前已落地的关键文件：

- [utils/market_bar_store.py](/Users/ruby/Desktop/ai-trading/contest_trade_refactor/utils/market_bar_store.py)
- [utils/cn_price_provider.py](/Users/ruby/Desktop/ai-trading/contest_trade_refactor/utils/cn_price_provider.py)
- [utils/oss_sync.py](/Users/ruby/Desktop/ai-trading/contest_trade_refactor/utils/oss_sync.py)
- [scripts/sync_market_bars_to_oss.py](/Users/ruby/Desktop/ai-trading/contest_trade_refactor/scripts/sync_market_bars_to_oss.py)

职责划分：

- `market_bar_store.py`：本地市场数据缓存的统一读写入口
- `cn_price_provider.py`：先看本地是否覆盖，不够再补抓远端，再回写本地
- `oss_sync.py`：OSS 配置解析、本地路径到对象 key 的映射
- `sync_market_bars_to_oss.py`：手动把本地目录镜像上传到 OSS

### 3.2 运行链路

```text
策略 / 回测脚本
    -> utils.cn_price_provider
    -> utils.market_bar_store
    -> 本地市场数据目录
    -> 如有缺口则抓 JQData / AkShare
    -> 回写本地目录

人工 / 定时同步
    -> scripts/sync_market_bars_to_oss.py
    -> Aliyun OSS
```

### 3.3 Git 忽略策略

以下内容必须保持不进 Git：

- `.env`
- `.env.local`
- 本地真实数据目录
- 临时中间文件

当前仓库已经忽略：

- `.env`
- `.env.local`
- `utils/cache/market_bars/`

如果将本地真实数据目录迁到仓库外，则不再需要依赖 `.gitignore` 兜底。

## 4. 推荐目录结构

推荐使用仓库外的专用数据目录，例如：

```text
/absolute/path/to/local-market-data/
└── bar_store/
    ├── stocks/
    │   ├── qfq/
    │   ├── hfq/
    │   └── raw/
    ├── indexes/
    └── metadata/
```

后续如果要扩展，可增加：

```text
/absolute/path/to/local-market-data/
├── bar_store/
├── snapshots/
├── manifests/
└── logs/
```

说明：

- `stocks/qfq`：复权个股日线
- `stocks/hfq`：后复权个股日线
- `stocks/raw`：不复权原始数据
- `indexes`：指数日线
- `metadata`：版本、来源、同步记录

## 5. OSS 约定

推荐环境变量：

```bash
OSS_ACCESS_KEY_ID=...
OSS_ACCESS_KEY_SECRET=...
OSS_BUCKET=beseen
OSS_ENDPOINT=oss-cn-beijing.aliyuncs.com
OSS_PREFIX=market-bars
OSS_SIGN_EXPIRES_SECONDS=3600
```

对象 key 映射规则：

```text
本地文件:
/absolute/path/to/local-market-data/bar_store/stocks/qfq/600519.pkl

OSS 对象:
oss://beseen/market-bars/stocks/qfq/600519.pkl
```

原则：

- 保持本地相对路径和 OSS 相对路径一致
- 尽量只做追加和覆盖单文件，不做复杂重命名
- 同步工具跳过 `.tmp` 和隐藏目录

## 6. 操作规范

### 6.1 新机器初始化

1. 拉取主仓库
2. 初始化 submodule
3. 配置 `.env`
4. 指定 `CN_MARKET_BAR_STORE_DIR`
5. 从 OSS 恢复本地市场数据

### 6.2 日常运行

1. 策略运行时只读写本地市场数据目录
2. 若本地缺数据，由 `cn_price_provider` 自动补抓
3. 新数据写回本地 store
4. 收盘后手动或定时执行同步脚本上传 OSS

### 6.3 同步命令

预演：

```bash
.venv/bin/python scripts/sync_market_bars_to_oss.py --dry-run
```

正式上传：

```bash
.venv/bin/python scripts/sync_market_bars_to_oss.py
```

强制全量上传：

```bash
.venv/bin/python scripts/sync_market_bars_to_oss.py --force
```

## 7. 安全要求

- Access Key 只能放本地 `.env` 或受控密钥系统
- 不把密钥写入 `README`、脚本常量或 Git 历史
- 一旦密钥出现在聊天、截图、日志或终端历史中，应立即轮换
- 仓库私有不等于密钥安全，私有仓库同样不能承载长期明文凭证

## 8. 为什么不把真实行情数据放进 Git

不是绝对不能，而是不适合当前场景。

主要原因：

- 历史行情会持续增长
- 二进制文件 diff 价值很低
- Git 历史会不断膨胀
- 高频覆盖会让 Git LFS 成本变高

所以这里采用：

- Git 管代码和元数据
- 本地目录管生产数据
- OSS 管远端备份和共享

## 9. 后续演进路线

### 阶段 A：当前方案

- 本地目录主存储
- OSS 手动同步
- Git + submodule 管代码与规范

### 阶段 B：增强方案

- 增加从 OSS 下载到本地的恢复脚本
- 增加同步 manifest
- 增加收盘后自动同步任务

### 阶段 C：更强版本化

如果未来需要“代码版本”和“数据版本”精确绑定，可继续演进到：

- DVC + OSS
- 或对象存储 + manifest + hash 校验

那时 Git 仍然只管理：

- manifest
- schema
- 迁移脚本
- 校验逻辑

不直接管理真实行情文件本体。

## 10. 当前结论

本项目的市场数据架构正式定为：

- `ai-trading` 主仓库管理策略代码与数据工程代码
- `contest_trade_refactor/market-data` submodule 管数据工程规范与样本
- 真实行情数据存储在本地专用目录
- Aliyun OSS 作为远端镜像与备份层
- 策略运行不直接依赖 OSS

这套方案兼顾了：

- 本地运行速度
- Git 仓库可维护性
- 数据资产可复用性
- 后续扩展到多机 / NAS / DVC 的可演进性
