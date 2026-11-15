# UTF-8。只报告有或没有。不读取密钥、配对码或令牌文件的内容。
$ErrorActionPreference = "Continue"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

function Show-Command([string]$Name) {
  if (Get-Command $Name -ErrorAction SilentlyContinue) {
    Write-Host "$Name：有"
  } else {
    Write-Host "$Name：没有"
  }
}

Show-Command py
Show-Command python
Show-Command node
Show-Command npm

function Show-Present([string]$Label, [string]$Relative) {
  $path = Join-Path $Root $Relative
  if (Test-Path -LiteralPath $path) {
    Write-Host "${Label}：有"
  } else {
    Write-Host "${Label}：没有"
  }
}

Show-Present "backend\.venv" "backend\.venv"
Show-Present "frontend\node_modules" "frontend\node_modules"

function Get-ListenerPid([int]$Port) {
  $pattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
  $line = netstat -ano | Select-String -Pattern $pattern | Select-Object -First 1
  if (-not $line) { return $null }
  return [int]$line.Matches[0].Groups[1].Value
}

foreach ($port in @(43123, 43124)) {
  $holder = Get-ListenerPid $port
  if ($holder) {
    Write-Host "端口 ${port}：被 PID $holder 占用"
  } else {
    Write-Host "端口 ${port}：空闲"
  }
}

try {
  $health = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:43124/api/health").Content
  if ($health -match '"service"\s*:\s*"multi-llm-chat-room"') {
    Write-Host "健康检查：service 是 multi-llm-chat-room"
  } else {
    Write-Host "健康检查：有回应，但 service 不是 multi-llm-chat-room"
  }
} catch {
  Write-Host "健康检查：打不开 http://127.0.0.1:43124/api/health"
}

Show-Present "secrets.json" "backend\data\secrets.json"
Show-Present "backend\data" "backend\data"

Write-Host "诊断结束。没有读取密钥或配对文件的内容。"
