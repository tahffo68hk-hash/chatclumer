#!/usr/bin/env bash
# 只结束带有本次启动标记的进程及其子进程。端口若仍被其他进程占用，明确报错。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/roomctl.py" stop \
  --token-file "$ROOT/.run/instance.token" \
  --port 43123 \
  --port 43124
