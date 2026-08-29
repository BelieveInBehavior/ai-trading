# Agent instructions

## Push 前必须同步本地行情到 OSS

每次执行 `git push`（或用户要求推送）之前，先把本地 market 数据上传到阿里云 OSS。行情文件不进 Git。

同步失败则停止，不要继续 push。

```bash
.venv/bin/python scripts/sync_market_bars_to_oss.py
```

- 只在用户明确要求时才加 `--force`
- 凭证和路径从项目根目录 `.env` 读取：`OSS_ACCESS_KEY_ID`、`OSS_ACCESS_KEY_SECRET`、`OSS_BUCKET`、`OSS_ENDPOINT`、`OSS_PREFIX`、`CN_MARKET_BAR_STORE_DIR`
- `CN_MARKET_BAR_STORE_DIR` 未设置或路径不存在时，脚本会退回 `utils/cache/market_bars`
- 不要把 `.env`、OSS 密钥或 `utils/cache/market_bars/` 提交进 Git
