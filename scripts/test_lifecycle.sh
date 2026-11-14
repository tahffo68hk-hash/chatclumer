#!/usr/bin/env bash
# 验证启动/停止：孙子进程随标记一起退出，其他端口上的服务不被误杀，
# 占用本项目端口时立即失败，真实 start→stop→start→stop 会释放 43123 和 43124。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
CTL=(python3 "$ROOT/scripts/roomctl.py")
PASS=0

listener() { "${CTL[@]}" listener "$1" || true; }

assert_free() {
  local port="$1"
  local pid
  pid="$(listener "$port")"
  if [[ -n "$pid" ]]; then
    echo "端口 $port 仍被 PID $pid 监听" >&2
    exit 1
  fi
}

echo "1. 孙子进程占用端口，stop 只清理带标记的进程树"
HOLD_PORT=43991
FOREIGN_PORT=43990
TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
mkdir -p .run
cat > .run/hold.sh << EOF
#!/bin/bash
python3 -m http.server ${HOLD_PORT} --bind 127.0.0.1 >/tmp/room-hold.log 2>&1 &
sleep 300 &
wait
EOF
chmod +x .run/hold.sh
python3 -m http.server "$FOREIGN_PORT" --bind 127.0.0.1 >/tmp/room-foreign.log 2>&1 &
FOREIGN_PID=$!
for _ in $(seq 1 30); do
  [[ -n "$(listener "$FOREIGN_PORT")" ]] && break
  sleep 0.1
done
"${CTL[@]}" launch --pidfile "$ROOT/.run/hold.pid" --logfile "$ROOT/.run/hold.log" --cwd "$ROOT" --token "$TOKEN" -- bash "$ROOT/.run/hold.sh"
for _ in $(seq 1 30); do
  [[ -n "$(listener "$HOLD_PORT")" ]] && break
  sleep 0.1
done
HOLD_PID="$(listener "$HOLD_PORT")"
[[ -n "$HOLD_PID" ]]
"${CTL[@]}" has-marker "$HOLD_PID" "$TOKEN"
if "${CTL[@]}" has-marker "$FOREIGN_PID" "$TOKEN"; then
  echo "无关进程不应带有启动标记" >&2
  exit 1
fi
"${CTL[@]}" stop --token "$TOKEN" --port "$HOLD_PORT"
assert_free "$HOLD_PORT"
if ! kill -0 "$FOREIGN_PID" 2>/dev/null; then
  echo "停止误杀了其他端口上的进程" >&2
  exit 1
fi
kill "$FOREIGN_PID" 2>/dev/null || true
wait "$FOREIGN_PID" 2>/dev/null || true
PASS=$((PASS + 1))

echo "2. 本项目端口被其他服务占用时，start 立即失败且不误杀"
python3 -m http.server 43123 --bind 127.0.0.1 >/tmp/room-block.log 2>&1 &
BLOCK_PID=$!
for _ in $(seq 1 30); do
  [[ -n "$(listener 43123)" ]] && break
  sleep 0.1
done
set +e
START_OUT="$(bash "$ROOT/scripts/start.sh" 2>&1)"
START_CODE=$?
set -e
if [[ "$START_CODE" -eq 0 || "$START_OUT" == *ready* ]]; then
  echo "占用端口时 start 不应就绪: $START_OUT" >&2
  kill "$BLOCK_PID" 2>/dev/null || true
  exit 1
fi
if [[ "$START_OUT" != *"其他进程"* || "$START_OUT" != *"43123"* ]]; then
  echo "缺少明确的端口占用说明: $START_OUT" >&2
  kill "$BLOCK_PID" 2>/dev/null || true
  exit 1
fi
if ! kill -0 "$BLOCK_PID" 2>/dev/null; then
  echo "start 误杀了占用端口的其他服务" >&2
  exit 1
fi
# 它的 200 不能被当成项目就绪
CODE_BODY="$(curl -sf -o /dev/null -w '%{http_code}' http://127.0.0.1:43123/ || true)"
[[ "$CODE_BODY" == "200" ]]
kill "$BLOCK_PID" 2>/dev/null || true
wait "$BLOCK_PID" 2>/dev/null || true
assert_free 43123
PASS=$((PASS + 1))

echo "3. 静态核对 Windows 脚本：先查端口，按 service 字段就绪，停止只走进程树"
grep -q "其他进程占用" "$ROOT/scripts/start.ps1"
grep -q 'multi-llm-chat-room' "$ROOT/scripts/start.ps1"
grep -q "Stop-Tree" "$ROOT/scripts/stop.ps1"
grep -q "没有结束该进程" "$ROOT/scripts/stop.ps1"
if grep -q "taskkill" "$ROOT/scripts/stop.ps1"; then
  echo "stop.ps1 不应按映像名结束进程" >&2
  exit 1
fi
PASS=$((PASS + 1))

cycle() {
  local label="$1"
  bash "$ROOT/scripts/start.sh"
  local back front
  back="$(curl -sf --max-time 2 http://127.0.0.1:43124/api/health)"
  front="$(curl -sf --max-time 2 http://127.0.0.1:43123/backend/api/health)"
  [[ "$back" == *'"service":"multi-llm-chat-room"'* ]]
  [[ "$front" == *'"service":"multi-llm-chat-room"'* ]]
  local front_pid token
  front_pid="$(listener 43123)"
  token="$(cat "$ROOT/.run/instance.token")"
  "${CTL[@]}" owns "$front_pid" "$token"
  bash "$ROOT/scripts/stop.sh"
  assert_free 43123
  assert_free 43124
  echo "$label 端口已释放"
}

echo "4. start → stop → start → stop"
cycle "第一次"
cycle "第二次"
PASS=$((PASS + 1))

echo "lifecycle ok ($PASS)"
