@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title Paper Research Multi-Agent System - Docker

where docker >nul 2>nul
if errorlevel 1 (
  echo ERROR: Docker command was not found.
  echo Install and start Docker Desktop, then run this file again.
  goto :error
)
docker info >nul 2>nul
if errorlevel 1 (
  echo ERROR: Docker Desktop is installed but its engine is not running.
  echo Start Docker Desktop and wait until Docker is running.
  goto :error
)

echo Building and starting the application...
docker compose up --build -d
if errorlevel 1 goto :error
echo.
echo The application is running at http://127.0.0.1:7860
start "" "http://127.0.0.1:7860"
pause
exit /b 0

:error
echo.
echo Startup failed. Keep this window open and send the error lines above to the developer.
pause
exit /b 1
