# Windows 启动。后端只绑定回环地址。没有认证时不要改成 0.0.0.0 后暴露到公网。
# 需要已安装 Python 3.10+ 与 Node.js 20+。停止用 scripts/stop.ps1，它只结束本次记下的进程树。
# LAN=1 时前端改为 0.0.0.0（手机模式，非本机请求必须扫码配对）。后端仍然只绑定 127.0.0.1。
$ErrorActionPreference = "Stop"
function Require-Tool([string]$Name, [string]$Hint) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    Write-Error "缺少 $Name。$Hint"
  }
}
function Get-ListenerPid([int]$Port) {
  $pattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
  $line = netstat -ano | Select-String -Pattern $pattern | Select-Object -First 1
  if (-not $line) { return $null }
  return [int]$line.Matches[0].Groups[1].Value
}
function Assert-PortFree([int]$Port) {
  $pidOnPort = Get-ListenerPid $Port
  if ($pidOnPort) {
    Write-Error "端口 $Port 已被其他进程占用（PID $pidOnPort）。本次没有启动，也不会把该进程的 HTTP 响应当作本项目就绪。"
  }
}
Require-Tool "node" "请先安装 Node.js 20 或更高版本，并确认 node 与 npm 都在 PATH 里。本脚本不会安装系统软件。装好后重新打开终端再运行本脚本。"
Require-Tool "npm" "Node.js 安装不完整：找不到 npm。本脚本不会安装系统软件。请重装 Node.js 20 或更高版本。"
if (-not (Get-Command "py" -ErrorAction SilentlyContinue) -and -not (Get-Command "python" -ErrorAction SilentlyContinue)) {
  Write-Error "缺少 Python。请安装 Python 3.10 或更高版本，并勾选 py 启动器或把 python 加入 PATH。本脚本不会安装系统软件。"
}
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$frontHost = "127.0.0.1"
if ($env:LAN -eq "1") {
  $frontHost = "0.0.0.0"
  Write-Host "警告：前端将监听 0.0.0.0（手机模式）。局域网里的设备必须先扫电脑上「手机连接」的二维码配对，未配对一律拒绝。不要暴露到公网或做端口转发。"
  Write-Host "后端仍只绑定 127.0.0.1，浏览器通过前端反代访问。"
}
Assert-PortFree 43124
Assert-PortFree 43123
$runDir = Join-Path $Root ".run"
$backendDir = Join-Path $Root "backend"
$frontDir = Join-Path $Root "frontend"
New-Item -ItemType Directory -Force -Path $runDir,(Join-Path $Root "backend\data") | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $Root "backend\.venv\Scripts\python.exe"))) {
  if (Get-Command "py" -ErrorAction SilentlyContinue) {
    py -3 -m venv (Join-Path $Root "backend\.venv")
  } else {
    python -m venv (Join-Path $Root "backend\.venv")
  }
}
& (Join-Path $Root "backend\.venv\Scripts\pip.exe") install -r (Join-Path $Root "backend\requirements.txt")
if (-not (Test-Path -LiteralPath (Join-Path $frontDir "node_modules"))) {
  Push-Location -LiteralPath $frontDir
  npm install
  Pop-Location
}
$uvicorn = Join-Path $Root "backend\.venv\Scripts\uvicorn.exe"
if (-not (Test-Path -LiteralPath $uvicorn)) {
  Write-Error "找不到 $uvicorn。请先运行 scripts\install.ps1。本次不会启动。"
}
$token = [guid]::NewGuid().ToString("N")
Set-Content -Path (Join-Path $runDir "instance.token") -Value $token -NoNewline
$env:CHAT_ROOM_RUN = $token
$serverJs = Join-Path $frontDir "server\index.mjs"
function Test-InTree([int]$ProcessId, [int]$RootId) {
  $cursor = $ProcessId
  for ($i = 0; $i -lt 8; $i++) {
    if ($cursor -eq $RootId) { return $true }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$cursor" -ErrorAction SilentlyContinue
    if (-not $proc) { return $false }
    $cursor = [int]$proc.ParentProcessId
  }
  return $false
}

# Start-Process 把 -ArgumentList 拼成一条命令行且不加引号，路径里有空格时要自己加。
function Quote-Arg([string]$Value) {
  if ($Value -match '[\s"]') { return '"' + ($Value -replace '"', '\"') + '"' }
  return $Value
}

$backend = Start-Process -FilePath $uvicorn -ArgumentList "app.main:app","--app-dir",(Quote-Arg $backendDir),"--host","127.0.0.1","--port","43124" -WorkingDirectory $Root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runDir "backend.log") -RedirectStandardError (Join-Path $runDir "backend.err.log")
Set-Content -Path (Join-Path $runDir "backend.pid") -Value $backend.Id
$frontend = Start-Process -FilePath (Get-Command node).Source -ArgumentList (Quote-Arg $serverJs),"--dev","-H",$frontHost,"-p","43123" -WorkingDirectory $frontDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runDir "frontend.log") -RedirectStandardError (Join-Path $runDir "frontend.err.log")
Set-Content -Path (Join-Path $runDir "frontend.pid") -Value $frontend.Id
Remove-Item Env:CHAT_ROOM_RUN
$deadline = (Get-Date).AddSeconds(150)
do {
  $backPid = Get-ListenerPid 43124
  $frontPid = Get-ListenerPid 43123
  # uvicorn.exe 和 node 都可能再拉起子进程（python.exe、next-server），监听者可以是本次启动进程的子孙，
  # 但不能是启动前就存在的其他进程。
  if ($backPid -and -not (Test-InTree $backPid $backend.Id)) {
    Write-Error "端口 43124 被 PID $backPid 占用，不是本次启动的后端进程树。不会把它当作已就绪。"
  }
  if ($frontPid -and -not (Test-InTree $frontPid $frontend.Id)) {
    Write-Error "端口 43123 被 PID $frontPid 占用，不是本次启动的前端进程树。不会把它的 HTTP 响应当作已就绪。"
  }
  try {
    $back = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:43124/api/health").Content
    $front = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:43123/backend/api/health").Content
    if ($back -match '"service":"multi-llm-chat-room"' -and $front -match '"service":"multi-llm-chat-room"') {
      Write-Host "ready http://127.0.0.1:43123"
      exit 0
    }
  } catch {}
  Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)
Write-Error "启动超时。健康检查要求 /api/health 返回本项目的 service 字段。查看 .run\backend.log 和 .run\frontend.log"
