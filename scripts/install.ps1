# 一键安装并启动。Windows。不需要管理员，不写密钥，不静默安装系统包。
# 依赖装好后调用 scripts/start.ps1，不另起一套进程管理。
# 预演：powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install.ps1 -DryRun
param(
  [switch]$DryRun
)
$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$MinPython = [version]"3.10.0"
$MinNode = [version]"20.0.0"

function ConvertTo-DottedVersion([string]$Text) {
  if ($Text -match "(\d+)\.(\d+)\.(\d+)") {
    return [version]("$($Matches[1]).$($Matches[2]).$($Matches[3])")
  }
  return $null
}

function Test-VersionAtLeast([version]$Actual, [version]$Minimum) {
  if (-not $Actual) { return $false }
  return $Actual -ge $Minimum
}

function Get-PythonCandidate {
  $found = @()
  if (Get-Command py -ErrorAction SilentlyContinue) {
    $found += @{ Exe = "py"; Prefix = @("-3") }
  }
  if (Get-Command python -ErrorAction SilentlyContinue) {
    $found += @{ Exe = "python"; Prefix = @() }
  }
  if (Get-Command python3 -ErrorAction SilentlyContinue) {
    $found += @{ Exe = "python3"; Prefix = @() }
  }
  foreach ($item in $found) {
    try {
      $raw = & $item.Exe @($item.Prefix + @("-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"))
      $ver = ConvertTo-DottedVersion (($raw | Select-Object -First 1) -as [string])
      if (Test-VersionAtLeast $ver $MinPython) {
        return @{ Exe = $item.Exe; Prefix = $item.Prefix; Version = $ver }
      }
    } catch {}
  }
  return $null
}

function Write-PythonHint {
  Write-Error "缺少 Python 3.10 或更高版本（建议 3.11+）。请安装 Python，并勾选 py 启动器或把 python 加入 PATH。本脚本不会自动安装系统包，也不需要管理员权限。"
}

function Write-NodeHint {
  Write-Error "缺少 Node.js 20 或更高版本。请从 https://nodejs.org/ 安装，并确认 node 和 npm 都在 PATH 里。本脚本不会自动安装系统包，也不需要管理员权限。"
}

function Write-LanWarning {
  if ($env:LAN -eq "1") {
    Write-Host "警告：前端将监听 0.0.0.0（手机模式）。局域网里的设备必须先扫电脑上「手机连接」的二维码配对，未配对一律拒绝。不要暴露到公网或做端口转发。"
    Write-Host "后端仍只绑定 127.0.0.1，浏览器通过前端反代访问。"
  } else {
    Write-Host "默认只监听 127.0.0.1。要用手机访问时用 LAN=1 启动（需扫码配对，只建议在自己家的 Wi-Fi 或 Tailscale 里用）。"
  }
}

function Write-Instructions {
  Write-Host ""
  Write-Host "应用地址：http://127.0.0.1:43123"
  Write-Host "后端：http://127.0.0.1:43124"
  Write-Host ""
  Write-Host "加载扩展（Chrome）："
  Write-Host "1. 打开 chrome://extensions"
  Write-Host "2. 打开右上角「开发者模式」"
  Write-Host "3. 点「加载已解压的扩展程序」"
  Write-Host "4. 选择这个目录里的 extension\（发布包解压后也是 extension\）"
  Write-Host "5. 在房间「设置」里生成本机配对码，粘贴到扩展弹窗完成配对。配对码五分钟内有效，用一次即失效。"
  Write-Host "6. 在扩展弹窗里按成员名字选择网页成员，再绑定当前标签页。不要复制成员 ID。"
  Write-Host ""
  Write-Host "日常使用：双击「启动 ChatCluster.bat」打开，双击「停止 ChatCluster.bat」停下。手机访问请双击「手机访问.bat」。"
  Write-Host "桌面壳是未核实的原型，不是默认入口。它只操作可见页面，不读取 Cookie，不绕过登录或验证码。"
  Write-Host "诊断：powershell -NoProfile -ExecutionPolicy Bypass -File scripts\doctor.ps1"
  Write-Host "诊断不会打印密钥或配对文件的内容。"
  Write-LanWarning
}

function Test-RoomReady {
  try {
    $back = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:43124/api/health").Content
    $front = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:43123/backend/api/health").Content
    return ($back -match '"service":"multi-llm-chat-room"' -and $front -match '"service":"multi-llm-chat-room"')
  } catch {
    return $false
  }
}

$python = Get-PythonCandidate
if (-not $python) { Write-PythonHint }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Write-NodeHint }
$nodeVer = ConvertTo-DottedVersion ((& node -v) | Select-Object -First 1)
if (-not (Test-VersionAtLeast $nodeVer $MinNode)) {
  Write-Error "当前 Node.js 是 $nodeVer，需要 20 或更高版本。请从 https://nodejs.org/ 安装。本脚本不会自动安装。"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  Write-Error "缺少 npm。Node.js 安装不完整。请重装 Node.js 20 或更高版本。"
}

Write-Host "Python $($python.Version)（需要 3.10+）"
Write-Host "Node.js $nodeVer（需要 20+）"

if ($DryRun) {
  Write-Host "这是预演（-DryRun）：只检查 Python 和 Node，不会创建虚拟环境、不会安装依赖、也不会启动。"
  Write-Host "将创建 backend\.venv 并安装 backend\requirements.txt"
  Write-Host "将在 frontend\ 运行 npm ci"
  Write-Host "将调用 scripts\start.ps1（不会另起一套进程管理）"
  Write-Instructions
  exit 0
}

if (-not (Test-Path "frontend\package-lock.json")) {
  Write-Error "找不到 frontend\package-lock.json，无法运行 npm ci。"
}

$venvPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  & $python.Exe @($python.Prefix + @("-m", "venv", "backend\.venv"))
  if (-not (Test-Path $venvPython)) {
    Write-Error "创建 backend\.venv 失败。请确认 Python 带 venv 模块。本脚本不会用管理员权限安装它。"
  }
}
& $venvPython -m pip install -r "backend\requirements.txt"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Push-Location frontend
try {
  npm ci
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
  Pop-Location
}

Write-LanWarning
if (Test-RoomReady) {
  Write-Host "已经在运行 http://127.0.0.1:43123"
} else {
  & (Join-Path $PSScriptRoot "start.ps1")
  if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
Write-Instructions
