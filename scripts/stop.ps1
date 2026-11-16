# 只结束 scripts/start.ps1 记下的进程树。不按端口结束其他服务。
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
function Stop-Tree([int]$ProcessId) {
  if ($ProcessId -le 1) { return }
  $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue)
  foreach ($child in $children) {
    Stop-Tree ([int]$child.ProcessId)
  }
  Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}
foreach ($name in @("backend", "frontend")) {
  $pidFile = ".run\$name.pid"
  if (Test-Path $pidFile) {
    $owned = [int](Get-Content $pidFile | Select-Object -First 1)
    if ($owned -gt 1) { Stop-Tree $owned }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
  }
}
function Get-ListenerPid([int]$Port) {
  $pattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
  $line = netstat -ano | Select-String -Pattern $pattern | Select-Object -First 1
  if (-not $line) { return $null }
  return [int]$line.Matches[0].Groups[1].Value
}
$busy = $false
foreach ($port in @(43123, 43124)) {
  $holder = Get-ListenerPid $port
  if ($holder) {
    $busy = $true
    Write-Error "端口 $port 仍由 PID $holder 占用。停止脚本没有结束该进程。" -ErrorAction Continue
  }
}
if ($busy) { exit 1 }
Write-Host "stopped"
