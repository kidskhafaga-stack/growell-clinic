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

REM --- 0) Updates are NOT applied here, on purpose ---
REM
REM This used to run "git pull --ff-only" on every launch, which made every
REM start of the program an unplanned update: no snapshot taken first, no
REM schema upgrade after, and landing in the middle of a working day. If the
REM new code needed a column the database did not have yet, the clinic found
REM out with patients in the waiting room.
REM
REM Updating is now a decision somebody makes, with a backup before it and a
REM schema upgrade after it:
REM
REM     update.bat
REM

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

REM --- 5) Initialise on first run, then match the database shape to the code ---
REM
REM Every launch needs the database's SHAPE to match the code about to read it,
REM so this runs every time. It is additive and idempotent: on an up-to-date
REM database it does nothing.
REM
REM It used to run the full "upgrade-db", which also re-ran every seeder and
REM took a PRE-UPGRADE BACKUP on every single start. That archive holds the
REM database and every uploaded file, and nothing trimmed those copies until
REM the next scheduled backup came round - so opening the program five times
REM in a morning wrote five full copies of the clinic's photos. Disks fill
REM quietly, and a full disk is what stops a clinic.
REM
REM The heavy version (seeding, backfills, a snapshot before it) belongs to
REM update.bat, where somebody decided to update.
if not exist "instance\growell.db" (
  echo [4/5] Initialising database and seeding the clinic catalogues...
  flask --app run seed
  if errorlevel 1 (
    echo [ERROR] Database initialisation failed - see the message above.
    pause
    exit /b 1
  )
)
echo [4/5] Matching the database shape to this version...
flask --app run sync-db
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
