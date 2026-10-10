@echo off
rem Atlas 参考项目动态：一流 Agent 项目（Codex、Claude Code、ZCode……）最近改了什么。
rem   atlas-watch.cmd              立即跑一次，跑完打开报告
rem   atlas-watch.cmd --install    装成每天 09:00 自动跑的 Windows 计划任务（Atlas 没开也会跑）
rem   atlas-watch.cmd --uninstall  删掉计划任务
rem Atlas 开着时本身每 24 小时也会自动跑；报告在 data\upstream\watch\latest.md
setlocal
set "ROOT=%~dp0.."
set "PY=%ROOT%\core\.venv\Scripts\python.exe"
set "PYTHONIOENCODING=utf-8"

if /i "%~1"=="--install" (
  schtasks /Create /TN "Atlas 参考项目动态" /TR "\"%~f0\" --quiet" /SC DAILY /ST 09:00 /F
  goto :eof
)
if /i "%~1"=="--uninstall" (
  schtasks /Delete /TN "Atlas 参考项目动态" /F
  goto :eof
)

pushd "%ROOT%\core"
"%PY%" -m atlas.upstream watch
set "RC=%ERRORLEVEL%"
popd
if /i not "%~1"=="--quiet" if "%RC%"=="0" start "" "%ROOT%\data\upstream\watch\latest.md"
exit /b %RC%
