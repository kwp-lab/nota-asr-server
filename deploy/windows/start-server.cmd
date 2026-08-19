@echo off
setlocal
chcp 65001 >nul
set "NOTA_RUNTIME_ROOT=%~dp0"
call "%NOTA_RUNTIME_ROOT%nota-asr.cmd" serve --config "%NOTA_RUNTIME_ROOT%config\server.toml"
exit /b %errorlevel%
