#!/usr/bin/env bash
# 主升浪收盘前监控（建议 14:50 跑）
# 用法：
#   ./scripts/main_trend_preclose_monitor.sh [--notify]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
EXTRA=""
if [[ "${1:-}" == "--notify" ]]; then
  EXTRA="--notify"
fi
.venv/bin/python scripts/main_trend_realtime_monitor.py --write-back $EXTRA
