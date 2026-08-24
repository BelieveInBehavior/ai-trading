#!/usr/bin/env bash
# 主升浪每日更新（T+1 9:30 前运行 / 盘中运行都可）
# 用法：
#   ./scripts/main_trend_daily_update.sh 20260825 \
#       agents_workspace_main_trend/20260824/holdings.json \
#       config/manual_execution_20260825.json
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DATE="${1:?请传入日期，如 20260825}"
HOLDINGS="${2:?请传入持仓文件路径}"
PRICES="${3:?请传入当日手工行情快照，如 config/manual_execution_20260825.json}"

echo "==> [main_trend] 更新 $DATE 持仓状态"
.venv/bin/python scripts/main_trend_holdings.py \
  --date "$DATE" \
  --holdings "$HOLDINGS" \
  --prices "$PRICES" \
  --update \
  --notify
echo "==> 完成，页面 http://localhost:3000/main_trend 已可查看"
