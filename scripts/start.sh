#!/usr/bin/env bash
# 启动本项目的后端和前端。每个服务在自己的会话里运行，停止时按标记清理子进程。
# 端口上若已有其他进程，立即失败，不用它的 HTTP 200 充当就绪。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
LAN="${LAN:-0}"
FRONT_HOST="127.0.0.1"
FRONT_PORT=43123
BACK_PORT=43124
if [[ "$LAN" == "1" ]]; then
  FRONT_HOST="0.0.0.0"
  echo "警告：前端将监听 0.0.0.0（手机模式）。局域网里的设备必须先扫电脑上「手机连接」的二维码配对，未配对一律拒绝。不要暴露到公网或做端口转发。"
  echo "后端仍只绑定 127.0.0.1，浏览器通过前端反代访问。"
fi
mkdir -p .run backend/data
TOKEN_FILE="$ROOT/.run/instance.token"
CTL=(python3 "$ROOT/scripts/roomctl.py")

listener() {
  "${CTL[@]}" listener "$1"
}

refuse_foreign() {
  local port="$1"
  local pid="$2"
  local cmd
  cmd="$("${CTL[@]}" cmdline "$pid")"
  echo "端口 ${port} 已被其他进程占用（PID ${pid}：${cmd:-无法读取命令}）。本次没有启动，也不会把该进程的 HTTP 响应当作本项目就绪。" >&2
  exit 1
}

ours() {
  local pid="$1"
  [[ -n "$pid" && -f "$TOKEN_FILE" ]] || return 1
  "${CTL[@]}" owns "$pid" "$(cat "$TOKEN_FILE")"
}

BACK_PID="$(listener "$BACK_PORT" || true)"
FRONT_PID="$(listener "$FRONT_PORT" || true)"
if [[ -n "$BACK_PID" ]] && ! ours "$BACK_PID"; then
  refuse_foreign "$BACK_PORT" "$BACK_PID"
fi
if [[ -n "$FRONT_PID" ]] && ! ours "$FRONT_PID"; then
  refuse_foreign "$FRONT_PORT" "$FRONT_PID"
fi

service_ready() {
  local back front
  back="$(curl -sf --max-time 1 "http://127.0.0.1:${BACK_PORT}/api/health" || true)"
  front="$(curl -sf --max-time 1 "http://127.0.0.1:${FRONT_PORT}/backend/api/health" || true)"
  [[ "$back" == *'"service":"multi-llm-chat-room"'* && "$front" == *'"service":"multi-llm-chat-room"'* ]]
}

if [[ -n "$BACK_PID" && -n "$FRONT_PID" ]] && service_ready; then
  echo "already running http://127.0.0.1:${FRONT_PORT}"
  exit 0
fi

if [[ ! -s "$TOKEN_FILE" ]]; then
  python3 -c 'import secrets; print(secrets.token_hex(16))' > "$TOKEN_FILE"
fi
TOKEN="$(cat "$TOKEN_FILE")"

if [[ ! -x backend/.venv/bin/python ]]; then
  python3 -m venv backend/.venv
fi
backend/.venv/bin/pip install -q -r backend/requirements.txt
if [[ ! -d frontend/node_modules ]]; then
  (cd frontend && npm install)
fi

if [[ -z "$BACK_PID" ]]; then
  "${CTL[@]}" launch \
    --pidfile "$ROOT/.run/backend.pid" \
    --logfile "$ROOT/.run/backend.log" \
    --cwd "$ROOT" \
    --token "$TOKEN" \
    -- \
    "$ROOT/backend/.venv/bin/uvicorn" app.main:app --app-dir backend --host 127.0.0.1 --port "$BACK_PORT"
fi
if [[ -z "$FRONT_PID" ]]; then
  "${CTL[@]}" launch \
    --pidfile "$ROOT/.run/frontend.pid" \
    --logfile "$ROOT/.run/frontend.log" \
    --cwd "$ROOT/frontend" \
    --token "$TOKEN" \
    -- \
    node "$ROOT/frontend/server/index.mjs" --dev -H "$FRONT_HOST" -p "$FRONT_PORT"
fi

for _ in $(seq 1 80); do
  now_back="$(listener "$BACK_PORT" || true)"
  now_front="$(listener "$FRONT_PORT" || true)"
  if [[ -n "$now_back" ]] && ! ours "$now_back"; then
    refuse_foreign "$BACK_PORT" "$now_back"
  fi
  if [[ -n "$now_front" ]] && ! ours "$now_front"; then
    refuse_foreign "$FRONT_PORT" "$now_front"
  fi
  if service_ready; then
    echo "ready http://127.0.0.1:${FRONT_PORT}"
    if [[ "$LAN" == "1" ]]; then
      echo "手机连接：在电脑上打开上面的地址，点「手机连接」，用手机扫码。口令不会打印在终端里。"
    fi
    exit 0
  fi
  if [[ -f .run/backend.pid ]] && ! kill -0 "$(cat .run/backend.pid)" 2>/dev/null; then
    echo "后端进程已退出，查看 .run/backend.log" >&2
    exit 1
  fi
  if [[ -f .run/frontend.pid ]] && ! kill -0 "$(cat .run/frontend.pid)" 2>/dev/null; then
    echo "前端进程已退出，查看 .run/frontend.log" >&2
    exit 1
  fi
  sleep 0.5
done
echo "启动超时。健康检查要求 /api/health 返回本项目的 service 字段。查看 .run/backend.log 和 .run/frontend.log" >&2
exit 1
