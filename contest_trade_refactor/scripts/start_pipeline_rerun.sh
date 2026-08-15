#!/usr/bin/env bash
# Durable background launcher for full-market pipeline rerun.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LOG="${ROOT}/logs/pipeline_rerun.log"
PIDFILE="${ROOT}/logs/pipeline_rerun.pid"

mkdir -p "${ROOT}/logs"
source "${ROOT}/.venv/bin/activate"

if [[ -f "$PIDFILE" ]]; then
  OLD_PID="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "${OLD_PID}" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Pipeline already running (PID=${OLD_PID}). Log: $LOG"
    exit 0
  fi
fi

nohup env PYTHONUNBUFFERED=1 PYTHONPATH="$ROOT" \
  python -u scripts/run_pipeline_rerun.py >> "$LOG" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PIDFILE"
disown "$NEW_PID" 2>/dev/null || true

echo "Started pipeline PID=${NEW_PID}"
echo "Log: $LOG"
echo "Tail: tail -f $LOG"
