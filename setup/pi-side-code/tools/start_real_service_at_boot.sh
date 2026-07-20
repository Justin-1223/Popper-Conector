#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
mkdir -p logs

PID_FILE=/tmp/joe-real-server.pid
HOST=0.0.0.0
PORT=8080
SESSION_ID="boot-$(date +%Y%m%d-%H%M%S)"
BOOT_LOG="logs/autostart-real-service.out"

if [[ -f "$PID_FILE" ]]; then
  existing_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
    echo "$(date -Is) real service already running pid=$existing_pid" >> "$BOOT_LOG"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

{
  echo "$(date -Is) starting real service session=$SESSION_ID"
  nohup .venv/bin/python tools/run_real_server.py \
    --host "$HOST" \
    --port "$PORT" \
    --log-dir logs \
    --session-id "$SESSION_ID" \
    --pid-file "$PID_FILE" \
    >> "$BOOT_LOG" 2>&1 &
  echo "$(date -Is) launched pid=$!"
} >> "$BOOT_LOG" 2>&1
