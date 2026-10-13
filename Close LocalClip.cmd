@echo off
echo Stopping LocalClip...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Close LocalClip.ps1"
echo LocalClip is closed.
timeout /t 3 >nul
