@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3.11 -m venv .venv
  if errorlevel 1 goto :error
)
.venv\Scripts\python.exe -m pip install -e .[ui]
if errorlevel 1 goto :error
set GRADIO_SERVER_NAME=127.0.0.1
set GRADIO_SERVER_PORT=7860
.venv\Scripts\paper-agents-ui.exe
goto :eof
:error
echo.
echo 启动失败。请确认已从 python.org 安装 Python 3.11 或更高版本。
pause
