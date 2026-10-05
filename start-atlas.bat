@echo off
setlocal
chcp 65001 >nul
title Atlas Desktop
cd /d "%~dp0"

where node >nul 2>&1
if errorlevel 1 (
  echo Atlas requires Node.js 22.12 or newer to launch from source. Install Node.js, then try again.
  goto :failed
)

where py >nul 2>&1
if errorlevel 1 (
  echo Atlas requires Python 3.14 to launch from source. Install Python 3.14, then try again.
  goto :failed
)

if not exist "core\.venv\Scripts\python.exe" (
  echo [setup] Creating the Atlas Python environment...
  py -3.14 -m venv "core\.venv"
  if errorlevel 1 goto :failed
  "core\.venv\Scripts\python.exe" core\scripts\setup_hermes.py
  if errorlevel 1 goto :failed
  "core\.venv\Scripts\python.exe" -m pip install -e "core"
  if errorlevel 1 goto :failed
) else (
  rem Keep the Hermes checkout at the commit pinned in core\pyproject.toml.
  "core\.venv\Scripts\python.exe" core\scripts\setup_hermes.py
  if errorlevel 1 goto :failed
)

if not exist "node_modules\.package-lock.json" (
  echo [setup] Installing Atlas desktop dependencies...
  call npm ci
  if errorlevel 1 goto :failed
)

set "ATLAS_PYTHON=%CD%\core\.venv\Scripts\python.exe"
echo [start] Opening Atlas Desktop. First startup may take a little longer.
call npm run dev
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo Atlas did not start. Review the message above, then try again.
pause
exit /b 1
