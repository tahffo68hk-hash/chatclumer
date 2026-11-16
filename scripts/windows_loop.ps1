# 在带空格和非 ASCII 字符的临时目录里真正安装、启动、复查、停止。
# 只删除这个临时副本。不读取、不打印密钥或配对材料。
$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$Source = Split-Path -Parent $PSScriptRoot
$spaceName = "Chat Cluster " + [char]0x6D4B + [char]0x8BD5
$projectName = -join @([char]0x6211, [char]0x7684, [char]0x9879, [char]0x76EE)
$dest = Join-Path (Join-Path $env:TEMP $spaceName) $projectName

function Get-ListenerPid([int]$Port) {
  $pattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
  $line = netstat -ano | Select-String -Pattern $pattern | Select-Object -First 1
  if (-not $line) { return $null }
  return [int]$line.Matches[0].Groups[1].Value
}

function Assert-RoomHealth {
  $back = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://127.0.0.1:43124/api/health").Content
  $front = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://127.0.0.1:43123/backend/api/health").Content
  if ($back -notmatch '"service":"multi-llm-chat-room"' -or $front -notmatch '"service":"multi-llm-chat-room"') {
    throw "health response is not this project"
  }
  Write-Host "health ok"
}

function Assert-PortsFree {
  foreach ($port in @(43123, 43124)) {
    $holder = Get-ListenerPid $port
    if ($holder) { throw "port $port still held by PID $holder" }
  }
  Write-Host "ports free"
}

function Invoke-Step([string]$File) {
  & powershell -NoProfile -ExecutionPolicy Bypass -File $File
  return $LASTEXITCODE
}

if (Test-Path -LiteralPath $dest) {
  Remove-Item -LiteralPath $dest -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$xd = @(
  (Join-Path $Source ".git"),
  (Join-Path $Source ".run"),
  (Join-Path $Source "frontend\node_modules"),
  (Join-Path $Source "frontend\.next"),
  (Join-Path $Source "backend\.venv"),
  (Join-Path $Source "backend\data")
) | Where-Object { Test-Path -LiteralPath $_ }
$robo = @($Source, $dest, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS")
if ($xd.Count -gt 0) {
  $robo += "/XD"
  $robo += $xd
}
& robocopy @robo | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed: $LASTEXITCODE" }
Write-Host "copied onto a path that contains a space and non-ascii characters"

try {
  $code = Invoke-Step (Join-Path $dest "scripts\install.ps1")
  if ($code -ne 0) { throw "install exited $code" }
  Assert-RoomHealth
  $code = Invoke-Step (Join-Path $dest "scripts\start.ps1")
  if ($code -eq 0) { throw "second start should refuse busy ports" }
  Assert-RoomHealth
  $code = Invoke-Step (Join-Path $dest "scripts\stop.ps1")
  if ($code -ne 0) { throw "stop exited $code" }
  Start-Sleep -Seconds 2
  Assert-PortsFree
  $code = Invoke-Step (Join-Path $dest "scripts\start.ps1")
  if ($code -ne 0) { throw "start after stop exited $code" }
  Assert-RoomHealth
  $code = Invoke-Step (Join-Path $dest "scripts\stop.ps1")
  if ($code -ne 0) { throw "final stop exited $code" }
  Start-Sleep -Seconds 2
  Assert-PortsFree
  Write-Host "windows loop ok"
} catch {
  Write-Host $_.Exception.Message
  $stop = Join-Path $dest "scripts\stop.ps1"
  if (Test-Path -LiteralPath $stop) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $stop
  }
  throw
} finally {
  if (Test-Path -LiteralPath $dest) {
    Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
  }
}
