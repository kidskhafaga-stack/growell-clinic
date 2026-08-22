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
REM
REM Two ways in, because a clinic PC has one of two kinds of copy.
REM
REM A copy made with "git clone" is updated with "git pull". A copy that was
REM downloaded as a ZIP from GitHub is not a repository at all, so no amount
REM of installing git will make "git pull" work in it - and that is the copy
REM most clinics have, because downloading the ZIP is what the GitHub page
REM offers you. This file used to stop there and say "git is not installed",
REM which was the wrong diagnosis and left the only real update path being to
REM replace the files by hand: no backup, no dependency install, no schema
REM upgrade, and no catalogue refresh.
REM
REM So: pull when this is a clone, download when it is not.
REM
REM Either way the steps around it are the same, and they are the point - the
REM backup above already ran, and the schema upgrade below still will.
echo.
echo [2/5] Fetching the new version...

set "PP_REPO=kidskhafaga-stack/growell-clinic"
set "PP_BRANCH=main"

set "PP_MODE=zip"
where git >nul 2>nul
if not errorlevel 1 if exist ".git" set "PP_MODE=git"

if "%PP_MODE%"=="git" goto :fetch_git

REM Called rather than written inline. A variable set inside a parenthesised
REM block is expanded when the block is *parsed*, not when it runs, so the
REM folder name found below would have arrived at robocopy empty - and
REM robocopy with an empty source is not an error, it is a copy of nothing
REM followed by an update that silently did not happen.
call :fetch_zip
if errorlevel 1 (
  pause
  exit /b 1
)
goto :fetched

:fetch_git
git pull --ff-only
if errorlevel 1 (
  echo.
  echo [ERROR] Could not fetch the update - offline, or this copy has local
  echo         changes. Nothing was changed. Your backup is untouched.
  pause
  exit /b 1
)

:fetched

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

exit /b 0


REM ============================================================
REM   Downloading the update, for a copy that is not a git clone
REM ============================================================
:fetch_zip
echo       This copy is not a git clone, so the files are downloaded instead.

set "PP_TMP=%TEMP%\pediapro-update"
if exist "%PP_TMP%" rmdir /s /q "%PP_TMP%"
mkdir "%PP_TMP%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$u='https://codeload.github.com/%PP_REPO%/zip/refs/heads/%PP_BRANCH%';" ^
  "Invoke-WebRequest -Uri $u -OutFile '%PP_TMP%\src.zip';" ^
  "Expand-Archive -Path '%PP_TMP%\src.zip' -DestinationPath '%PP_TMP%' -Force"
if errorlevel 1 (
  echo.
  echo [ERROR] Could not download the update - offline, or GitHub is not
  echo         reachable. Nothing was changed. Your backup is untouched.
  exit /b 1
)

REM The archive unpacks into a single folder named after the repo and branch.
set "PP_SRC="
for /d %%D in ("%PP_TMP%\*") do set "PP_SRC=%%~fD"
if not defined PP_SRC (
  echo [ERROR] The download arrived but was empty. Nothing was changed.
  exit /b 1
)
if not exist "%PP_SRC%\run.py" (
  echo [ERROR] The download does not look like PediaPro. Nothing was changed.
  exit /b 1
)

REM Copy the program over the top, and nothing else.
REM
REM The exclusions are the clinic's own data and they are not optional:
REM `instance` is the database and every backup, `uploads` is every
REM photograph, signature and scanned document, and `clinic.env` is this
REM machine's port and language. Copying without them is an update; copying
REM over them is a clinic losing its records to a routine maintenance task.
REM
REM They are belt and braces - none of those are in the archive, because none
REM of them are in the repository - and they stay because the day one of them
REM is added by accident is the day this matters.
REM
REM /E adds and overwrites and never deletes. A file dropped from the project
REM is left behind rather than risking a mistyped exclusion taking something
REM real with it, and a stale file costs far less than a lost record.
robocopy "%PP_SRC%" "%~dp0." /E ^
  /XD instance .venv .git uploads __pycache__ backups ^
  /XF clinic.env *.db *.sqlite *.sqlite3 ^
  /NFL /NDL /NJH /NJS /NP
REM robocopy reports 0-7 for success (0 = nothing to do, 1 = files copied).
REM Anything from 8 up is a real failure, so this cannot be `if errorlevel 1`.
if errorlevel 8 (
  echo.
  echo [ERROR] Copying the new files failed. Restore the preupgrade backup
  echo         from tools.bat before using the program.
  exit /b 1
)

rmdir /s /q "%PP_TMP%"
exit /b 0
