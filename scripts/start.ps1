# Windows 启动。后端只绑定回环地址。没有认证时不要改成 0.0.0.0 后暴露到公网。
# 需要已安装 Python 3.11+ 与 Node.js 22。停止用 scripts/stop.ps1，它只结束本次记下的进程树。
# LAN=1 时前端改为 0.0.0.0，并先打印无登录警告。后端仍然只绑定 127.0.0.1。
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
Require-Tool "node" "请先安装 Node.js 22，并确认 node 与 npm 都在 PATH 里。装好后重新打开终端再运行本脚本。"
Require-Tool "npm" "Node.js 安装不完整：找不到 npm。请重装 Node.js 22。"
if (-not (Get-Command "py" -ErrorAction SilentlyContinue) -and -not (Get-Command "python" -ErrorAction SilentlyContinue)) {
  Write-Error "缺少 Python。请安装 Python 3.11 或更新版本，并勾选 py 启动器或把 python 加入 PATH。"
}
Set-Location (Split-Path -Parent $PSScriptRoot)
$frontHost = "127.0.0.1"
if ($env:LAN -eq "1") {
  $frontHost = "0.0.0.0"
  Write-Host "警告：前端将监听 0.0.0.0。此服务没有登录认证，不要暴露到公网或做端口转发。"
  Write-Host "后端仍只绑定 127.0.0.1，浏览器通过前端反代访问。"
}
Assert-PortFree 43124
Assert-PortFree 43123
New-Item -ItemType Directory -Force -Path ".run","backend\data" | Out-Null
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
$token = [guid]::NewGuid().ToString("N")
Set-Content -Path ".run\instance.token" -Value $token -NoNewline
$env:CHAT_ROOM_RUN = $token
$backend = Start-Process -FilePath "backend\.venv\Scripts\uvicorn.exe" -ArgumentList "app.main:app","--app-dir","backend","--host","127.0.0.1","--port","43124" -WindowStyle Hidden -PassThru -RedirectStandardOutput ".run\backend.log" -RedirectStandardError ".run\backend.err.log"
Set-Content -Path ".run\backend.pid" -Value $backend.Id
Push-Location frontend
$frontend = Start-Process -FilePath "node.exe" -ArgumentList ".\node_modules\next\dist\bin\next","dev","--turbopack","-H",$frontHost,"-p","43123" -WindowStyle Hidden -PassThru -RedirectStandardOutput "..\.run\frontend.log" -RedirectStandardError "..\.run\frontend.err.log"
Pop-Location
Set-Content -Path ".run\frontend.pid" -Value $frontend.Id
Remove-Item Env:CHAT_ROOM_RUN
$deadline = (Get-Date).AddSeconds(40)
do {
  $backPid = Get-ListenerPid 43124
  $frontPid = Get-ListenerPid 43123
  if ($backPid -and $backPid -ne $backend.Id) {
    Write-Error "端口 43124 被 PID $backPid 占用，不是本次启动的后端。不会把它当作已就绪。"
  }
  if ($frontPid -and $frontPid -ne $frontend.Id) {
    # next 会再拉起 next-server，监听者可以是其子进程，不能是启动前就存在的进程。
    $started = @($backend.Id, $frontend.Id)
    if ($started -notcontains $frontPid) {
      $childOk = $false
      $cursor = $frontPid
      for ($i = 0; $i -lt 8; $i++) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$cursor" -ErrorAction SilentlyContinue
        if (-not $proc) { break }
        if ($proc.ParentProcessId -eq $frontend.Id) { $childOk = $true; break }
        $cursor = $proc.ParentProcessId
      }
      if (-not $childOk) {
        Write-Error "端口 43123 被 PID $frontPid 占用，不是本次启动的前端进程树。不会把它的 HTTP 响应当作已就绪。"
      }
    }
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
