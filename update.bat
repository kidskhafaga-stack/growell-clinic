@echo off
REM ============================================================
REM   GROWELL CLINIC | PediaPro  --  Update
REM ============================================================
REM
REM Updating is a decision, not something that happens because somebody
REM double-clicked the program. start.bat used to run "git pull" on every
REM launch: no backup taken first, no schema upgrade after, and it landed in
REM the middle of a working day. If the new code wanted a column the database
REM did not have, the clinic found out with patients in the waiting room.
REM
REM So this file does the whole thing in the order that makes it reversible:
REM
REM   1) take a full backup, and check it is readable
REM   2) fetch the new code
REM   3) install any new dependencies
REM   4) upgrade the database schema
REM   5) check the program actually starts
REM
REM If step 4 or 5 fails, your data is still there and the backup from step 1
REM is named on screen. Nothing here deletes anything.
REM
REM Run it when the clinic is closed, or at least when nobody is mid-visit.
REM ============================================================

cd /d "%~dp0"

echo ============================================================
echo    GROWELL CLINIC  ^|  Update
echo ============================================================
echo.
echo   The clinic should not be in use while this runs.
echo.
pause

REM --- 1) Python and the virtual environment -------------------
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python is not installed or not on PATH.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\activate.bat" (
  echo [ERROR] No virtual environment yet. Run start.bat once first.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"

REM --- 2) Back up BEFORE touching anything ---------------------
REM Everything below is reversible only because this ran first.
echo [1/5] Taking a full backup...
flask --app run backup-now --reason preupgrade
if errorlevel 1 (
  echo.
  echo [ERROR] The backup failed, so the update stopped here.
  echo         Nothing has been changed. Fix the backup first - updating
  echo         without one is the thing this file exists to prevent.
  pause
  exit /b 1
)

REM --- 3) Fetch the new code ----------------------------------
echo.
echo [2/5] Fetching the new version...
where git >nul 2>nul
if errorlevel 1 (
  echo [ERROR] git is not installed, so the code cannot be updated.
  pause
  exit /b 1
)
git pull --ff-only
if errorlevel 1 (
  echo.
  echo [ERROR] Could not fetch the update - offline, or this copy has local
  echo         changes. Nothing was changed. Your backup is untouched.
  pause
  exit /b 1
)

REM --- 4) New dependencies ------------------------------------
echo.
echo [3/5] Installing dependencies...
python -m pip install --upgrade pip >nul 2>nul
pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Dependencies failed to install. Do not use the app yet.
  pause
  exit /b 1
)

REM --- 5) Bring the database's shape up to the new code --------
REM The step whose absence caused the trouble after a restore. Additive and
REM idempotent: on an already-current database it does nothing.
echo.
echo [4/5] Upgrading the database...
flask --app run upgrade-db
if errorlevel 1 (
  echo.
  echo [ERROR] The database upgrade failed. DO NOT use the app.
  echo         Your data has not been deleted. Run tools.bat and choose
  echo         "Restore a backup" to go back to the preupgrade snapshot.
  pause
  exit /b 1
)

REM --- 6) Does it actually start? -----------------------------
REM "The update finished without an error" is not the same as "the program
REM works", and the difference is only visible if somebody checks.
echo.
echo [5/5] Checking the program starts...
python -c "from app import create_app; a=create_app(); c=a.test_client(); r=c.get('/login'); raise SystemExit(0 if r.status_code==200 else 1)"
if errorlevel 1 (
  echo.
  echo [ERROR] The app did not start cleanly after the update.
  echo         Restore the preupgrade backup from tools.bat before using it.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo    Update finished. The backup taken first is in the
echo    backups folder, named "preupgrade".
echo ============================================================
echo.
pause
