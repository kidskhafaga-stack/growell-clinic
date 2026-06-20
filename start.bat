@echo off
REM ============================================================
REM   GROWELL CLINIC - One-click startup for Windows
REM   Installs everything the app needs, then launches it.
REM ============================================================
setlocal
cd /d "%~dp0"

echo ============================================================
echo    GROWELL CLINIC
echo ============================================================
echo.

REM --- 1) Ensure Python is available ---
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python is not installed or not on PATH.
  echo Please install Python 3.10+ from https://www.python.org/downloads/
  echo Make sure to tick "Add Python to PATH" during installation.
  pause
  exit /b 1
)

REM --- 2) Create the virtual environment on first run ---
if not exist ".venv\Scripts\activate.bat" (
  echo [1/4] Creating virtual environment...
  python -m venv .venv
)

REM --- 3) Install / update dependencies ---
echo [2/4] Installing dependencies...
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul 2>nul
pip install -r requirements.txt

REM --- 4) Initialise the database + demo data on first run ---
if not exist "instance\growell.db" (
  echo [3/4] Initialising database and seeding demo data...
  flask --app run seed
) else (
  echo [3/4] Database found - applying any safe upgrades...
  flask --app run upgrade-db
)

REM --- 5) Launch the app and open the browser ---
echo [4/4] Starting GROWELL CLINIC at http://localhost:5000
echo Close this window to stop the server.
start "" "http://localhost:5000"
python run.py

pause
