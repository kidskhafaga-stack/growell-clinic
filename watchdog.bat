@echo off
REM ============================================================
REM   GROWELL CLINIC  -  is it ANSWERING?  (run BY the watchdog task)
REM
REM   Do not double-click this. The Scheduled Task runs it every few minutes.
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM Restarting a crashed program is the easy half, and the Scheduler already
REM does it. The failure a clinic actually meets is the other one: the process
REM is alive, the task says "Running", and every page hangs - a locked
REM database, a thread pool with nothing left. From outside that is
REM indistinguishable from health, which is why this asks the program itself.

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" exit /b 0

if not exist "%~dp0logs" mkdir "%~dp0logs"
set "LOG=%~dp0logs\watchdog.log"

REM /healthz touches the database on purpose - a check that only proves Python
REM is alive would answer happily through exactly the failure it exists to
REM catch. Two tries before acting: one timeout during a backup is not a dead
REM server, and a watchdog that restarts on every hiccup is worse than none.
"%PY%" -m app.health_check
if not errorlevel 1 exit /b 0

echo [%date% %time%] no answer - retrying once >> "%LOG%"
"%PY%" -m app.health_check
if not errorlevel 1 exit /b 0

echo [%date% %time%] still no answer - restarting the clinic service >> "%LOG%"
schtasks /End /TN "GrowellClinic" >nul 2>nul
schtasks /Run /TN "GrowellClinic" >nul 2>nul
echo [%date% %time%] restart requested >> "%LOG%"
exit /b 0
