@echo off
setlocal
chcp 65001 >nul
set "NOTA_RUNTIME_ROOT=%~dp0"
"%NOTA_RUNTIME_ROOT%runtime\python\python.exe" -m nota_asr_server.cli %*
exit /b %errorlevel%
