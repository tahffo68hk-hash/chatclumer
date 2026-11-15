@echo off
chcp 65001 >nul
cd /d "%~dp0"
set LAN=1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
if errorlevel 1 (
  echo 启动失败。请先双击「停止 ChatCluster.bat」，再试一次。
  pause
  exit /b 1
)
