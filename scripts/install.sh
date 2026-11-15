#!/usr/bin/env bash
# 一键安装并启动。Linux / macOS。不需要管理员，不写密钥，不静默安装系统包。
# 依赖装好后调用 scripts/start.sh，不另起一套进程管理。
# 预演：bash scripts/install.sh --dry-run
#   或 INSTALL_DRY_RUN=1 bash scripts/install.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" || "${1:-}" == "--check" || "${INSTALL_DRY_RUN:-0}" == "1" ]]; then
  DRY_RUN=1
fi

MIN_PYTHON="3.10.0"
MIN_NODE="20.0.0"

version_ge() {
  local IFS=.
  local i x y
  local -a got need
  read -r -a got <<< "${1:-0.0.0}"
  read -r -a need <<< "${2:-0.0.0}"
  for i in 0 1 2; do
    x="${got[$i]:-0}"
    y="${need[$i]:-0}"
    x="${x%%[^0-9]*}"
    y="${y%%[^0-9]*}"
    x="${x:-0}"
    y="${y:-0}"
    if ((10#$x > 10#$y)); then return 0; fi
    if ((10#$x < 10#$y)); then return 1; fi
  done
  return 0
}

dotted_version() {
  local line="${1:-}"
  if [[ "$line" =~ ([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
    echo "${BASH_REMATCH[1]}.${BASH_REMATCH[2]}.${BASH_REMATCH[3]}"
  fi
}

python_version_of() {
  local bin="$1" line
  line="$("$bin" --version 2>&1 || true)"
  dotted_version "$line"
}

node_version_of() {
  local line
  line="$(node --version 2>&1 || true)"
  dotted_version "$line"
}

pick_python() {
  local bin path ver
  for bin in python3 python; do
    path="$(command -v "$bin" 2>/dev/null || true)"
    [[ -n "$path" ]] || continue
    ver="$(python_version_of "$path")"
    if [[ -n "$ver" ]] && version_ge "$ver" "$MIN_PYTHON"; then
      echo "$path"
      return 0
    fi
  done
  return 1
}

python_hint() {
  cat >&2 <<'EOF'
缺少 Python 3.10 或更高版本（建议 3.11+，与 Windows 启动脚本的说明一致）。
Linux：用系统包管理器安装 python3 和 python3-venv（例如 Debian/Ubuntu：sudo 由你自己执行 apt install python3 python3-venv）。
macOS：从 https://www.python.org/downloads/ 安装，或使用你已经在用的版本管理器。
本脚本不会自动安装系统包，也不需要管理员权限。
EOF
}

node_hint() {
  cat >&2 <<'EOF'
缺少 Node.js 20 或更高版本。请从 https://nodejs.org/ 安装，并确认 node 和 npm 都在 PATH 里。
本脚本不会自动安装系统包，也不需要管理员权限。
EOF
}

print_lan_warning() {
  if [[ "${LAN:-0}" == "1" ]]; then
    echo "警告：前端将监听 0.0.0.0。此服务没有登录认证，不要暴露到公网或做端口转发。"
    echo "后端仍只绑定 127.0.0.1，浏览器通过前端反代访问。"
  else
    echo "默认只监听 127.0.0.1。只有在你接受无登录风险时才使用 LAN=1。"
  fi
}

print_instructions() {
  cat <<EOF

应用地址：http://127.0.0.1:43123
后端：http://127.0.0.1:43124

加载扩展（Chrome）：
1. 打开 chrome://extensions
2. 打开右上角「开发者模式」
3. 点「加载已解压的扩展程序」
4. 选择这个目录里的 extension/（发布包解压后也是 extension/）
5. 在房间「设置」里生成本机配对码，粘贴到扩展弹窗完成配对。配对码五分钟内有效，用一次即失效。

或者启动桌面壳原型（不用安装扩展，也不用抄配对码）：
  cd "$ROOT/desktop"
  npm install
  npm start
桌面壳是原型，尚未在真实网站上验证。它只操作可见页面，不读取 Cookie，不绕过登录或验证码。
打开某个站点窗口后，把窗口标题里的绑定键填进房间的网页成员。

停止：bash "$ROOT/scripts/stop.sh"
EOF
  print_lan_warning
}

if ! PYTHON_BIN="$(pick_python)"; then
  python_hint
  exit 1
fi
PY_VER="$(python_version_of "$PYTHON_BIN")"
if ! command -v node >/dev/null 2>&1; then
  node_hint
  exit 1
fi
NODE_VER="$(node_version_of)"
if [[ -z "$NODE_VER" ]] || ! version_ge "$NODE_VER" "$MIN_NODE"; then
  echo "当前 Node.js 是 ${NODE_VER:-未知}，需要 20 或更高版本。" >&2
  node_hint
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "缺少 npm。Node.js 安装不完整。" >&2
  node_hint
  exit 1
fi

echo "Python $($PYTHON_BIN --version 2>&1)（需要 3.10+）"
echo "Node.js $(node --version)（需要 20+）"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "这是预演（--dry-run）：只检查 Python 和 Node，不会创建虚拟环境、不会安装依赖、也不会启动。"
  echo "将创建 backend/.venv 并安装 backend/requirements.txt"
  echo "将在 frontend/ 运行 npm ci"
  echo "将调用 scripts/start.sh（不会另起一套进程管理）"
  print_instructions
  exit 0
fi

if [[ ! -f "$ROOT/frontend/package-lock.json" ]]; then
  echo "找不到 frontend/package-lock.json，无法运行 npm ci。" >&2
  exit 1
fi

VENV_PY="$ROOT/backend/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  if ! "$PYTHON_BIN" -m venv "$ROOT/backend/.venv"; then
    echo "创建 backend/.venv 失败。请确认 Python 带 venv 模块（Debian/Ubuntu 的包名是 python3-venv）。本脚本不会用管理员权限安装它。" >&2
    exit 1
  fi
fi
"$VENV_PY" -m pip install -r "$ROOT/backend/requirements.txt"
(cd "$ROOT/frontend" && npm ci)

print_lan_warning
if ! bash "$ROOT/scripts/start.sh"; then
  echo "启动失败。查看 .run/backend.log 和 .run/frontend.log。停止已记下的进程：bash scripts/stop.sh" >&2
  exit 1
fi
print_instructions
