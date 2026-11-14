# Windows 可选启动。后端只绑定回环地址。没有认证时不要改成 0.0.0.0 后暴露到公网。
# 需要已安装 Python 3.11+ 与 Node.js 22。
$ErrorActionPreference = "Stop"
function Require-Tool([string]$Name, [string]$Hint) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    Write-Error "缺少 $Name。$Hint"
  }
}
Require-Tool "node" "请先安装 Node.js 22，并确认 node 与 npm 都在 PATH 里。装好后重新打开终端再运行本脚本。"
Require-Tool "npm" "Node.js 安装不完整：找不到 npm。请重装 Node.js 22。"
if (-not (Get-Command "py" -ErrorAction SilentlyContinue) -and -not (Get-Command "python" -ErrorAction SilentlyContinue)) {
  Write-Error "缺少 Python。请安装 Python 3.11 或更新版本，并勾选 py 启动器或把 python 加入 PATH。"
}
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path "backend\.venv\Scripts\python.exe")) {
  if (Get-Command "py" -ErrorAction SilentlyContinue) {
    py -3 -m venv backend\.venv
  } else {
    python -m venv backend\.venv
  }
}
backend\.venv\Scripts\pip install -r backend\requirements.txt
if (-not (Test-Path "frontend\node_modules")) {
  Push-Location frontend
  npm install
  Pop-Location
}
Start-Process -FilePath "backend\.venv\Scripts\uvicorn.exe" -ArgumentList "app.main:app","--app-dir","backend","--host","127.0.0.1","--port","43124" -WindowStyle Hidden
Push-Location frontend
Start-Process -FilePath "npx.cmd" -ArgumentList "next","dev","--turbopack","-H","127.0.0.1","-p","43123" -WindowStyle Hidden
Pop-Location
Write-Host "启动后打开 http://127.0.0.1:43123"
