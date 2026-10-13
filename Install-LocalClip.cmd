@echo off
rem Double-click to install LocalClip.
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/MarkyADHD/LocalClip/main/install.ps1 | iex"
if errorlevel 1 pause
