@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0LocalClip.ps1"
if errorlevel 1 pause
