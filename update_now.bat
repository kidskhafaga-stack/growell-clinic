@echo off
REM ============================================================
REM   GROWELL CLINIC - the hand-off
REM ============================================================
REM
REM Started BY the program, and it waits for the program to die before it
REM touches a single file. That order is the whole point.
REM
REM `start.bat` used to run `git pull` on every launch, which made opening the
REM clinic an unplanned update - no snapshot in front of it, no schema upgrade
REM behind it, landing in the middle of a working day - and it cost a clinic a
REM morning. Replacing the files a running Python process is executing is that
REM same failure with a button on it: half the modules on disk are the new
REM version and half of what is in memory is the old one, and nobody finds out
REM until a request lands on the seam.
REM
REM So the program does not update itself. It asks this script to, and then it
REM closes. By the time anything here writes, there is no clinic running.
REM
REM Argument 1: the process id to wait for. Without it, nothing happens - an
REM update with no idea what it is waiting for is exactly what must not run.

setlocal
set "PP_PID=%~1"
if "%PP_PID%"=="" (
  echo [ERROR] No process id was given. Nothing has been changed.
  echo         Close the program and run update.bat instead.
  pause
  exit /b 1
)

title GROWELL CLINIC - updating
echo.
echo ============================================================
echo    Waiting for the clinic to close...
echo ============================================================
echo.

REM Bounded. If the program will not close - a hung request, a dialog nobody
REM answered - this stops rather than waiting for ever, and stops *without*
REM updating. A partial update onto a live process is the one outcome worth
REM refusing outright.
set /a PP_LEFT=120
:wait
tasklist /FI "PID eq %PP_PID%" 2>nul | find "%PP_PID%" >nul
if errorlevel 1 goto :closed
set /a PP_LEFT-=1
if %PP_LEFT% LEQ 0 (
  echo.
  echo [ERROR] The program is still running after two minutes.
  echo         NOTHING has been changed. Close it yourself and run
  echo         update.bat when you are ready.
  pause
  exit /b 1
)
timeout /t 1 /nobreak >nul
goto :wait

:closed
REM A moment for Windows to let go of the files the process had open. Without
REM it the copy can fail on a database or a log the dying process still holds.
timeout /t 3 /nobreak >nul

echo.
echo    The clinic is closed. Starting the update.
echo.
call "%~dp0update.bat"

REM update.bat takes its own backup, replaces the files, upgrades the database
REM and checks the program still starts. It reports its own errors and it does
REM not come back here having half-finished quietly.
endlocal
