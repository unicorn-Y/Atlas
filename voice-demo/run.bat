@echo off
chcp 65001 >nul
title Atlas Voice Web Demo

echo ===================================================
echo   正在准备 Atlas 语音对话 Web Demo 环境...
echo ===================================================

cd /d "D:\Atlas\voice-demo"

echo 正在唤醒 IndexTTS-2.5 语音引擎 (8792)...
start "" /b "D:\AI-Plan-tools\indextts-env\Scripts\python.exe" "D:\AI-Plan-tools\aiplan_indextts_server.py" --ensure

echo 正在启动主服务 (http://127.0.0.1:8780)...
python voice_server.py

pause
