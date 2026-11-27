@echo off
REM Starts the API (port 8000) and the website (port 3000), then opens the browser.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo Run 1-SETUP.bat first & pause & exit /b 1)
start "Turnitin Report - API" cmd /k ".venv\Scripts\python.exe -m uvicorn api.main:app --port 8000"
start "Turnitin Report - Website" cmd /k "cd frontend && npm.cmd run dev"
echo Waiting for the website to start...
timeout /t 15 /nobreak >nul
start http://localhost:3000
echo Site: http://localhost:3000   (close the two black windows to stop it)
