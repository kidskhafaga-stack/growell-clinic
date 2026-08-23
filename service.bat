@echo off
REM ============================================================
REM   GROWELL CLINIC  -  run as a Windows service
REM
REM   Right-click -> "Run as administrator", then pick an option.
REM
REM   After this, the clinic starts on its own when the server is
REM   switched on - before anybody signs in - and comes back by
REM   itself if it stops or stops answering.
REM
REM   Tested target: Windows Server 2012 R2 (works on Windows 10/11 too).
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
chcp 65001 >nul 2>nul

REM --- Administrator, or nothing works and nothing says why ---
net session >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERROR] Run this as Administrator.
  echo         Right-click service.bat -^> "Run as administrator".
  echo.
  pause
  exit /b 1
)

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo.
  echo [ERROR] The program has not been set up on this machine yet.
  echo         Run start.bat once by hand first - it creates .venv and the
  echo         database - then come back here.
  echo.
  pause
  exit /b 1
)

:menu
echo.
echo ============================================================
echo    GROWELL CLINIC  ^|  Windows service
echo ============================================================
echo.
echo   [1] Install  - start with the server, keep it running
echo   [2] Remove   - stop and unregister
echo   [3] Status   - is it registered, and is it answering?
echo   [4] Start now
echo   [5] Stop now
echo   [6] Open the firewall for the clinic's port (other PCs on the network)
echo   [0] Exit
echo.
set "CHOICE="
set /p CHOICE=Choose:
if "%CHOICE%"=="1" goto install
if "%CHOICE%"=="2" goto remove
if "%CHOICE%"=="3" goto status
if "%CHOICE%"=="4" goto startnow
if "%CHOICE%"=="5" goto stopnow
if "%CHOICE%"=="6" goto firewall
if "%CHOICE%"=="0" exit /b 0
goto menu

:install
echo.
echo Writing the task definitions...
"%PY%" -c "import os;from app.utils.windows_service import write_definitions;[print('  ',p) for p in write_definitions(os.getcwd()).values()]"
if errorlevel 1 goto failed

echo.
echo Registering with the Task Scheduler...
REM Two tasks: one runs the clinic and is restarted if it dies; one asks it
REM every five minutes whether it is actually answering, because a hung
REM program looks exactly like a healthy one from outside.
schtasks /Create /TN "GrowellClinic" /XML "%~dp0GrowellClinic.xml" /F
if errorlevel 1 goto failed
schtasks /Create /TN "GrowellClinicWatchdog" /XML "%~dp0GrowellClinicWatchdog.xml" /F
if errorlevel 1 goto failed

echo.
echo Starting it now...
schtasks /Run /TN "GrowellClinic" >nul 2>nul

echo.
echo ============================================================
echo   Installed. The clinic now starts with the server.
echo.
echo   No sign-in needed - it runs as SYSTEM, from boot.
echo   Log:      logs\service.log
echo   Watchdog: logs\watchdog.log
echo.
echo   NEXT: option [6] opens the firewall so the other PCs in the
echo   clinic can reach it. Skip it if this PC is the only one using it.
echo ============================================================
echo.
pause
goto menu

:remove
echo.
schtasks /End /TN "GrowellClinic" >nul 2>nul
schtasks /Delete /TN "GrowellClinic" /F
schtasks /Delete /TN "GrowellClinicWatchdog" /F
echo.
echo Removed. Your data was not touched.
echo.
pause
goto menu

:status
echo.
schtasks /Query /TN "GrowellClinic" /V /FO LIST 2>nul | findstr /I "TaskName Status Last Next Result"
echo.
echo --- and is it actually answering? ---
"%PY%" -m app.health_check
echo.
pause
goto menu

:startnow
schtasks /Run /TN "GrowellClinic"
echo.
pause
goto menu

:stopnow
schtasks /End /TN "GrowellClinic"
echo.
pause
goto menu

:firewall
echo.
REM The port comes from clinic.env, so the rule always matches what the
REM program is really serving on - a rule for 5000 while the clinic runs on
REM 8080 is a morning spent on "the other computers cannot see it".
for /f "usebackq delims=" %%P in (`"%PY%" -c "from app.settings_file import load_env;load_env();from run import chosen_port;print(chosen_port([]))"`) do set "APP_PORT=%%P"
if "%APP_PORT%"=="" set "APP_PORT=5000"
echo Opening TCP port %APP_PORT% for the local network...
netsh advfirewall firewall delete rule name="GROWELL CLINIC" >nul 2>nul
netsh advfirewall firewall add rule name="GROWELL CLINIC" dir=in action=allow protocol=TCP localport=%APP_PORT% profile=any
echo.
echo Done. Other PCs reach it at  http://<this-server-name>:%APP_PORT%
echo.
pause
goto menu

:failed
echo.
echo [ERROR] That step failed - see the message above. Nothing was left half done:
echo         run option [2] to remove, fix the cause, then install again.
echo.
pause
goto menu
