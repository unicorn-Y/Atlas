@echo off
chcp 65001 >nul
title Atlas Backend (8765)
cd /d "%~dp0core"

rem Atlas 目前没有独立 venv，依赖 Hermes venv 里的 litellm / fastapi / langgraph
set "PY=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo ============================================================
echo  Atlas Backend
echo    gateway : http://127.0.0.1:8045/v1   (antigravity local)
echo    model   : gemini-3.8-flash-high
echo    listen  : http://127.0.0.1:8765
echo ============================================================
echo.
echo [check] 反重力网关 8045 是否在线...
curl -s -m 3 http://127.0.0.1:8045/v1/models >nul 2>&1
if errorlevel 1 (
  echo   [WARN] 8045 无响应，模型调用会失败 —— 请先启动反重力网关
) else (
  echo   [OK] 8045 在线
)
echo.
"%PY%" -m uvicorn atlas.server:app --host 127.0.0.1 --port 8765
pause
