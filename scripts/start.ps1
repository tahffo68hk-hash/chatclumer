# Windows 可选启动。后端只绑定回环地址。没有认证时不要改成 0.0.0.0 后暴露到公网。
# 需要已安装 Python 3.11+ 与 Node.js 22。
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path "backend\.venv\Scripts\python.exe")) {
  py -3 -m venv backend\.venv
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
