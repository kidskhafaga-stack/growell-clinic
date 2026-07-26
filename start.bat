@echo off
REM ============================================================
REM   GROWELL CLINIC - One-click startup for Windows
REM   Installs everything the app needs, then launches it.
REM
REM   To change the port: edit clinic.env (PORT=8080), or run
REM   this file with the port after it:   start.bat 8080
REM   For maintenance commands (backup, upgrade, import...),
REM   run tools.bat - or read COMMANDS.md.
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo    GROWELL CLINIC  ^|  PediaPro
echo ============================================================
echo.

REM --- 0) Pull the latest version if online (safe to skip offline) ---
where git >nul 2>nul
if not errorlevel 1 (
  if exist ".git" (
    echo [0/5] Checking for updates...
    git pull --ff-only
    if errorlevel 1 echo      ^(skipped update - offline or local changes; continuing^)
  )
)

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
  echo [1/5] Creating virtual environment...
  python -m venv .venv
)

REM --- 3) Install / update dependencies ---
echo [2/5] Installing dependencies...
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul 2>nul
pip install -r requirements.txt

REM --- 4) Local settings file (port, language) on first run ---
if not exist "clinic.env" (
  echo [3/5] Creating clinic.env - open it in Notepad to change the port.
  python -c "from app.settings_file import ensure_file; ensure_file()"
)

REM --- 5) Initialise the database on first run, then ALWAYS upgrade it ---
REM The upgrade step is what adds new columns/tables after an update, so it
REM must run on every start - not only when a database already existed.
if not exist "instance\growell.db" (
  echo [4/5] Initialising database and seeding the clinic catalogues...
  flask --app run seed
  if errorlevel 1 (
    echo [ERROR] Database initialisation failed - see the message above.
    pause
    exit /b 1
  )
)
echo [4/5] Applying any safe database upgrades...
flask --app run upgrade-db
if errorlevel 1 (
  echo [ERROR] Database upgrade failed - do NOT use the app before fixing this.
  echo         Your data is untouched. Run tools.bat and choose "Restore a backup"
  echo         if you need to go back.
  pause
  exit /b 1
)

REM --- 6) Work out the port: the argument wins, then clinic.env, then 5000 ---
set "PORT_ARG=%~1"
for /f "usebackq delims=" %%P in (`python -c "import sys;from app.settings_file import load_env;load_env();from run import chosen_port;print(chosen_port([a for a in sys.argv[1:] if a]))" "%PORT_ARG%"`) do set "APP_PORT=%%P"
if "%APP_PORT%"=="" set "APP_PORT=5000"

REM --- 7) Launch the app and open the browser ---
echo [5/5] Starting GROWELL CLINIC at http://localhost:%APP_PORT%
echo Close this window to stop the server.
start "" "http://localhost:%APP_PORT%"
python run.py %APP_PORT%

pause
