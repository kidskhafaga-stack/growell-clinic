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
  goto :die
)
if not exist ".venv\Scripts\activate.bat" (
  echo [ERROR] No virtual environment yet. Run start.bat once first.
  pause
  goto :die
)
call ".venv\Scripts\activate.bat"

REM --- Tell the watchdog to stand down ------------------------
REM The clinic is deliberately closed for all of what follows, and the
REM watchdog asks every five minutes whether it is answering and
REM restarts it when it is not. The backup alone can outlast that. So
REM without this the watchdog relaunches the program into the middle of
REM the file copy - reading modules that are being overwritten under it.
REM
REM The marker expires by itself, so an update that dies here cannot
REM leave a clinic unwatched for ever; every exit below clears it anyway.
python -m app.update_guard start >nul 2>nul

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
  goto :die
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
  goto :die
)
goto :fetched

:fetch_git
git pull --ff-only
if errorlevel 1 (
  echo.
  echo [ERROR] Could not fetch the update - offline, or this copy has local
  echo         changes. Nothing was changed. Your backup is untouched.
  pause
  goto :die
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
  goto :die
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
  goto :die
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
  goto :die
)

REM --- 7) Write down what this copy now is ---------------------
REM A clone can answer that itself; a downloaded copy cannot, so it is
REM recorded in the instance folder - the one place a file survives being
REM replaced by the next update. Without it, start.bat has nothing to compare
REM against and its notice can never fire.
REM
REM The revision is handed over rather than worked out, because this script is
REM the only thing that knows it for certain: it asked for that commit by
REM name. Left to work it out, a downloaded copy would read the stamp written
REM before this update and write the same thing back - so the stamp never
REM moved, and a clinic that updates by downloading was told there was a newer
REM version at every launch, for ever.
REM
REM Nothing is passed. This script used to work the commit id out for itself
REM before downloading, and the line that did it was the bug that stopped the
REM download working at all - see the note beside the fetch. `record-version`
REM asks the branch when there is no git to ask, which is the same answer by a
REM route that cannot be mangled by a batch file.
flask --app run record-version

echo.
echo ============================================================
echo    Update finished. The backup taken first is in the
echo    backups folder, named "preupgrade".
echo ============================================================
echo.

REM --- 8) Open the clinic again --------------------------------
REM Reachable only from here, and that is the whole condition: every
REM failure above exits with `pause` still in front of it, so a broken
REM update leaves a window somebody has to read rather than a program
REM that quietly reopens on top of it. [5/5] has already loaded the app
REM and asked it for a page, so by this line "it starts" is measured
REM rather than assumed.
REM
REM `start` so this window does not become the clinic: start.bat runs
REM the server in the foreground of whatever window calls it, and
REM holding it here would leave the updater and the clinic sharing one
REM window and one Ctrl-C.
REM
REM And no `pause` on the way out. It was there to tell somebody to go
REM and run start.bat, and there is nothing left to tell them; a window
REM waiting for a keypress it does not need is a window a clinic learns
REM to ignore.
python -m app.update_guard done >nul 2>nul

REM --- Bring the clinic back, the way this machine actually runs it ---
REM A clinic installed as a service is started by the Task Scheduler, and
REM this used to run start.bat regardless: a second, hand-run copy beside
REM the service, both wanting the same port. So the task is asked first,
REM and start.bat is what a machine without one gets.
schtasks /Query /TN "GrowellClinic" >nul 2>nul
if errorlevel 1 (
  echo    Opening GROWELL CLINIC...
  start "" "%~dp0start.bat"
) else (
  echo    Restarting the GROWELL CLINIC service...
  schtasks /End /TN "GrowellClinic" >nul 2>nul
  schtasks /Run /TN "GrowellClinic" >nul 2>nul
)
timeout /t 5 /nobreak >nul

exit /b 0


REM ============================================================
REM   Every way this stops without finishing
REM ============================================================
REM One way out, so the watchdog is handed back on all of them. An update
REM that gave up is over, and the clinic should be watched again from that
REM moment rather than from whenever the marker happens to expire.
:die
python -m app.update_guard done >nul 2>nul
exit /b 1


REM ============================================================
REM   Downloading the update, for a copy that is not a git clone
REM ============================================================
:fetch_zip
echo       This copy is not a git clone, so the files are downloaded instead.

set "PP_TMP=%TEMP%\pediapro-update"
if exist "%PP_TMP%" rmdir /s /q "%PP_TMP%"
mkdir "%PP_TMP%"

REM The branch, by name, and nothing cleverer than that.
REM
REM This asked GitHub for the head commit first and downloaded that commit by
REM name, so the copy could be stamped with exactly what it fetched. The idea
REM was sound and the code was not: the PowerShell call was spread over three
REM lines with `^` continuations **inside** a `for /f` block, where the caret
REM does not mean what it means anywhere else. The command arrived at
REM PowerShell in pieces, PowerShell complained, and the complaint was
REM captured as the commit id — so the download asked for
REM `zip/<an error message>` and GitHub answered 404.
REM
REM Reported from a real clinic, on a public repository, with the branch
REM sitting there: "[2/5] Fetching the new version..." then not found. The new
REM error message did its job and named three causes, and the true cause was
REM a fourth one this script had invented for itself.
REM
REM So it fetches the branch, which is one URL and cannot be mangled. What the
REM pre-lookup bought was a seconds-wide window in which a commit could land
REM between the download and the stamp; `record-version` already closes that
REM well enough by asking the branch itself, and a race that narrow is not
REM worth a line of batch nobody can read.
set "PP_ZIP_REF=refs/heads/%PP_BRANCH%"

REM TLS 1.2, said out loud, and this line is why the download stopped working.
REM
REM Windows PowerShell 5.1 - which is what ships with Windows and what a
REM clinic PC is running - still negotiates TLS 1.0 by default, and GitHub has
REM refused that for years. The failure is "Could not create SSL/TLS secure
REM channel", which arrives as an exception carrying no HTTP response at all,
REM so the 404 test below reads `$null -eq 404`, decides it is not a 404, and
REM the script reports a network fault on a machine whose network is fine.
REM
REM It was here once. It went out with the commit-id lookup it happened to be
REM sitting inside - the lookup was the bug, this line was not, and both were
REM removed together. Twice now this file has lost a correct line because it
REM stood next to a wrong one.
REM
REM And the error itself is printed rather than swallowed. Every failure here
REM was being flattened into two exit codes, so a clinic could report only
REM which of two sentences it saw - which is how a TLS failure spent two
REM rounds being diagnosed as a missing repository.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;" ^
  "$u='https://codeload.github.com/%PP_REPO%/zip/%PP_ZIP_REF%';" ^
  "try { Invoke-WebRequest -Uri $u -OutFile '%PP_TMP%\src.zip' }" ^
  "catch { Write-Host ('      ' + $_.Exception.Message);" ^
  "        if ($_.Exception.Response.StatusCode.value__ -eq 404)" ^
  "        { exit 44 } else { exit 1 } };" ^
  "Expand-Archive -Path '%PP_TMP%\src.zip' -DestinationPath '%PP_TMP%' -Force"

REM 404 is not "offline", and saying it was is what sent somebody hunting for
REM a network fault that did not exist.
REM
REM GitHub answers 404 - not 403 - for a repository the caller may not read,
REM so a private repository and a deleted one look identical from here. The
REM download is anonymous by design: this script carries no token, because a
REM token that can read the source would then be sitting in plain text on
REM every clinic PC that has ever been updated.
REM
REM Which leaves three real causes, and the message names all three rather
REM than guessing at one.
REM No brackets in any of the text below, and that is not a style choice.
REM
REM An unescaped `)` inside a parenthesised block closes the block where it
REM stands. This message used to explain that the download carries no sign-in
REM "(on purpose - a password here would sit on every clinic PC);" and that
REM closing bracket ended the `if` four lines into it: everything after it ran
REM on every outcome, and the half before it ran only on a 404.
REM
REM Which is exactly what a clinic saw. The report showed the *tail* of this
REM message with its first lines missing - so the failure was never a 404 at
REM all, and the script had been printing the wrong diagnosis at full
REM confidence. The message written to stop somebody chasing the wrong fault
REM was itself the wrong fault.
REM
REM `goto` rather than a block, so there is no bracket to escape and nothing
REM to get wrong the next time a sentence needs a comma.
if errorlevel 44 goto :not_found
if errorlevel 1 goto :no_network
goto :got_zip

:not_found
echo.
echo [ERROR] GitHub answered "not found" for this project.
echo.
echo         That is one of three things, and none of them is your internet:
echo           - the repository is private, and this download carries no
echo             sign-in. That is deliberate - a password here would sit on
echo             every clinic PC that has ever been updated.
echo           - the branch was renamed or removed.
echo           - the project was moved.
echo.
echo         Nothing was changed. Your backup is untouched.
echo         Until it is sorted: sign in on github.com, download the ZIP
echo         yourself, and copy it over this folder WITHOUT touching
echo         instance\, uploads\ or clinic.env - then run:
echo             flask --app run upgrade-db
goto :die

:no_network
echo.
echo [ERROR] Could not reach GitHub to download the update - the machine
echo         is offline, or something between here and it is blocking the
echo         connection.
echo.
echo         The exact error is above this line. Nothing was changed and
echo         your backup is untouched.
goto :die

:got_zip

REM The archive unpacks into a single folder named after the repo and branch.
set "PP_SRC="
for /d %%D in ("%PP_TMP%\*") do set "PP_SRC=%%~fD"
if not defined PP_SRC (
  echo [ERROR] The download arrived but was empty. Nothing was changed.
  goto :die
)
if not exist "%PP_SRC%\run.py" (
  echo [ERROR] The download does not look like PediaPro. Nothing was changed.
  goto :die
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
REM /NJS dropped, and that is the whole of this change.
REM
REM Every listing switch was on, so this step printed one sentence and then
REM nothing at all - and the next line a clinic saw was "[4/5] Database
REM upgraded (0 column(s) added)". Those two together are unreadable: "0" is
REM the correct answer for a database that is already current AND the
REM symptom of files that never arrived, and nothing on the screen told them
REM apart. A clinic asked exactly that, and answering it took opening folders
REM and pasting commands to find out whether an update had happened.
REM
REM The job summary is four lines and names how many files were copied. /NFL
REM and /NDL stay: the per-file list on a first-time copy is thousands of
REM lines and would push everything else off the screen, which is its own way
REM of telling somebody nothing.
robocopy "%PP_SRC%" "%~dp0." /E ^
  /XD instance .venv .git uploads __pycache__ backups ^
  /XF clinic.env *.db *.sqlite *.sqlite3 ^
  /NFL /NDL /NJH /NP
REM robocopy reports 0-7 for success (0 = nothing to do, 1 = files copied).
REM Anything from 8 up is a real failure, so this cannot be `if errorlevel 1`.
if errorlevel 8 (
  echo.
  echo [ERROR] Copying the new files failed. Restore the preupgrade backup
  echo         from tools.bat before using the program.
  goto :die
)

rmdir /s /q "%PP_TMP%"
exit /b 0
