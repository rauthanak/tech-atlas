@echo off
rem Double-clickable launcher for start.ps1 (bypasses PowerShell script blocking).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 pause
