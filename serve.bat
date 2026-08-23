@echo off
REM ============================================================
REM   GROWELL CLINIC  -  the server body (run BY the service)
REM
REM   Do not double-click this. It is what the Scheduled Task runs.
REM   To run the program by hand, use start.bat.
REM   To install/remove the service, use service.bat.
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM Nothing here may wait for a person. This runs as SYSTEM at boot, with no
REM desktop and no console anybody can see: a "pause", a prompt, or a browser
REM window is a server that never finishes starting.

REM --- The venv's own python, by absolute path ---
REM
REM SYSTEM has a different PATH from the person who installed Python, and a
REM per-user Python install is not on it at all. Calling the interpreter
REM inside .venv by full path is what makes the service independent of who
REM happens to be signed in.
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [%date% %time%] .venv is missing - run start.bat once by hand first. >> "%~dp0logs\service.log"
  exit /b 1
)

if not exist "%~dp0logs" mkdir "%~dp0logs"
set "LOG=%~dp0logs\service.log"

REM --- Keep the log from growing forever ---
REM A log nobody rotates is a disk that fills, and a full disk stops a clinic
REM as surely as a crash does. Anything over ~20 MB becomes .old (one
REM generation is enough to see what happened last night).
for %%F in ("%LOG%") do if %%~zF GTR 20000000 (
  move /y "%LOG%" "%~dp0logs\service.old.log" >nul 2>nul
)

echo [%date% %time%] starting >> "%LOG%"

REM --- Match the database shape to this code, exactly as start.bat does ---
REM Additive and idempotent; on an up-to-date database it does nothing. If it
REM fails we stop rather than serve: reading a database whose shape does not
REM match the code is how a clinic gets wrong numbers instead of an error.
"%PY%" -m flask --app run sync-db >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] SCHEMA UPGRADE FAILED - not starting >> "%LOG%"
  exit /b 1
)

REM --- Serve, in the foreground ---
REM The task must stay attached to this process: the Scheduler decides the
REM task has ended when this window exits, and "restart on failure" is only
REM meaningful while it is still holding on to it.
echo [%date% %time%] serving >> "%LOG%"
"%PY%" run.py >> "%LOG%" 2>&1

echo [%date% %time%] stopped with code %errorlevel% >> "%LOG%"
exit /b %errorlevel%
