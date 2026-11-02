@echo off
rem Runs start.ps1 whatever the PowerShell execution policy (a fresh Windows blocks .ps1 files)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dpn0.ps1" %*
exit /b %errorlevel%
