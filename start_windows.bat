@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title Paper Research Multi-Agent System

echo [1/4] Checking Python...
set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
  echo ERROR: Python was not found.
  echo Install Python 3.11 or newer and select "Add Python to PATH".
  goto :error
)
%PYTHON_CMD% -c "import sys; raise SystemExit(0 if sys.version_info ^>= (3, 11) else 1)"
if errorlevel 1 (
  echo ERROR: Python 3.11 or newer is required.
  %PYTHON_CMD% --version
  goto :error
)

echo [2/4] Preparing virtual environment...
if not exist ".venv\Scripts\python.exe" (
  %PYTHON_CMD% -m venv ".venv"
  if errorlevel 1 goto :error
)

echo [3/4] Installing project dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -e ".[ui]"
if errorlevel 1 goto :error

if not exist "data" mkdir "data"
set "GRADIO_SERVER_NAME=127.0.0.1"
set "GRADIO_SERVER_PORT=7860"

echo [4/4] Starting web application...
echo Open http://127.0.0.1:7860 in your browser.
".venv\Scripts\python.exe" -m paper_agents.ui.app
if errorlevel 1 goto :error
goto :eof

:error
echo.
echo Startup failed. Keep this window open and send the error lines above to the developer.
pause
exit /b 1
