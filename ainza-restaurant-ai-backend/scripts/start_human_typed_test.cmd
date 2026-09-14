@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_human_typed_test.ps1"
exit /b %ERRORLEVEL%
