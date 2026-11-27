@echo off
REM One-time setup for Turnitin Report (run once). Needs Python 3.11+ and Node.js installed.
cd /d "%~dp0"
echo === Python environment ===
python -m venv .venv || (echo Python not found. Install from https://www.python.org/downloads/ ^(tick "Add to PATH"^) & pause & exit /b 1)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt || (echo pip install failed & pause & exit /b 1)
.venv\Scripts\python.exe -m playwright install chromium
if not exist data mkdir data
if not exist data\uploads mkdir data\uploads
if not exist data\reports mkdir data\reports
echo === Database ===
.venv\Scripts\python.exe -m alembic upgrade head || (echo Database setup failed & pause & exit /b 1)
echo === Sample corpus (Wikipedia) ===
.venv\Scripts\python.exe -m scripts.index_corpus corpus/wikipedia/sample.jsonl
echo === Website (Next.js) ===
cd frontend
call npm.cmd install || (echo Node.js not found or npm failed. Install from https://nodejs.org & pause & exit /b 1)
cd ..
echo.
echo Setup complete. Now double-click 2-START.bat
pause
