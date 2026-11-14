#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
LAN="${LAN:-0}"
FRONT_HOST="127.0.0.1"
if [[ "$LAN" == "1" ]]; then
  FRONT_HOST="0.0.0.0"
  echo "警告：前端将监听 0.0.0.0。此服务没有登录认证，不要暴露到公网或做端口转发。"
  echo "后端仍只绑定 127.0.0.1，浏览器通过前端反代访问。"
fi
mkdir -p .run backend/data
if [[ ! -x backend/.venv/bin/python ]]; then
  python3 -m venv backend/.venv
fi
backend/.venv/bin/pip install -q -r backend/requirements.txt
if [[ ! -d frontend/node_modules ]]; then
  (cd frontend && npm install)
fi
if [[ -f .run/backend.pid ]] && kill -0 "$(cat .run/backend.pid)" 2>/dev/null; then
  echo "backend already running"
else
  DEMO_CHUNK_DELAY="${DEMO_CHUNK_DELAY:-0.08}" \
    nohup backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 43124 \
    > .run/backend.log 2>&1 &
  echo $! > .run/backend.pid
fi
if [[ -f .run/frontend.pid ]] && kill -0 "$(cat .run/frontend.pid)" 2>/dev/null; then
  echo "frontend already running"
else
  (
    cd frontend
    nohup npx next dev --turbopack -H "$FRONT_HOST" -p 43123 > "$ROOT/.run/frontend.log" 2>&1 &
    echo $! > "$ROOT/.run/frontend.pid"
  )
fi
for _ in $(seq 1 80); do
  if curl -sf http://127.0.0.1:43124/api/health >/dev/null && curl -sf -o /dev/null http://127.0.0.1:43123; then
    echo "ready http://127.0.0.1:43123"
    exit 0
  fi
  sleep 0.5
done
echo "启动超时，查看 .run/backend.log 和 .run/frontend.log" >&2
exit 1
