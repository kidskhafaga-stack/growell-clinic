@echo off
REM ============================================================
REM   GROWELL CLINIC - Maintenance
REM   The commands you need after an update, a move to a new PC,
REM   or when something needs putting right. Nothing here runs
REM   by itself: pick a number.
REM
REM   أوامر الصيانة - بعد التحديث أو النقل لجهاز جديد أو لما
REM   حاجة تحتاج تظبيط. مفيش حاجة بتشتغل لوحدها: اختار رقم.
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
  echo [ERROR] Run start.bat once first - it creates the environment.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"

:menu
cls
echo ============================================================
echo    GROWELL CLINIC  ^|  Maintenance / الصيانة
echo ============================================================
echo.
echo   AFTER AN UPDATE / بعد التحديث
echo     1  Apply database upgrades        (flask upgrade-db)
echo     2  Refresh the clinic catalogues  (vaccines, services, drugs)
echo.
echo   BACKUP / النسخ الاحتياطي
echo     3  Take a backup now              (database + photos)
echo     4  List backups
echo.
echo   DATA / البيانات
echo     5  Import a drug list             (CSV or JSON)
echo     6  Load the drug reference again
echo     7  Load the demo dataset          (for a presentation)
echo     8  Delete all operational data    (KEEPS users and catalogues)
echo.
echo   ACCOUNTS / الحسابات
echo     9  Create an administrator
echo.
echo   SETTINGS / الإعدادات
echo    10  Open clinic.env (port, language)
echo    11  Show all available commands
echo.
echo     0  Exit
echo.
set "choice="
set /p "choice=Choose a number / اختار رقم: "

if "%choice%"=="1"  goto upgrade
if "%choice%"=="2"  goto reference
if "%choice%"=="3"  goto backup
if "%choice%"=="4"  goto listbackups
if "%choice%"=="5"  goto importdrugs
if "%choice%"=="6"  goto drugbook
if "%choice%"=="7"  goto demo
if "%choice%"=="8"  goto resetdata
if "%choice%"=="9"  goto admin
if "%choice%"=="10" goto settings
if "%choice%"=="11" goto commands
if "%choice%"=="0"  goto end
goto menu

:upgrade
echo.
echo Applying database upgrades... this is safe and adds only what is missing.
flask --app run upgrade-db
goto done

:reference
echo.
echo Refreshing catalogues (vaccines, services, drugs, store items)...
echo Your own edits are kept - this only fills in what is missing.
flask --app run seed-reference
goto done

:backup
echo.
flask --app run shell -c "from app.utils.backups import create_backup; print('Backup created:', create_backup('manual'))"
goto done

:listbackups
echo.
flask --app run shell -c "from app.utils.backups import list_backups; [print(f\"{b['name']}  {b['size']//1024} KB  {b['has_files']} files\") for b in list_backups()]"
goto done

:importdrugs
echo.
set "file="
set /p "file=Path to the CSV/JSON file: "
if "%file%"=="" goto menu
echo.
echo Reading it first WITHOUT saving, so you can see the numbers:
flask --app run import-drugs "%file%" --dry-run
echo.
set "ok="
set /p "ok=Import for real? (y/N): "
if /i "%ok%"=="y" flask --app run import-drugs "%file%"
goto done

:drugbook
echo.
flask --app run seed-drugbook
goto done

:demo
echo.
echo This adds made-up patients and visits, for a demonstration.
set "ok="
set /p "ok=Are you sure? (y/N): "
if /i "%ok%"=="y" flask --app run seed-demo
goto done

:resetdata
echo.
echo ** This deletes patients, visits and invoices. Users, roles and the
echo ** catalogues are kept. A backup is taken first.
set "ok="
set /p "ok=Type DELETE to confirm: "
if /i "%ok%"=="DELETE" (
  flask --app run shell -c "from app.utils.backups import create_backup; print('Backup first:', create_backup('manual'))"
  flask --app run reset-data
) else (
  echo Cancelled.
)
goto done

:admin
echo.
flask --app run create-admin
goto done

:settings
echo.
if not exist "clinic.env" python -c "from app.settings_file import ensure_file; ensure_file()"
notepad clinic.env
echo Restart the program for the change to take effect.
goto done

:commands
echo.
flask --app run --help
echo.
echo Full reference with explanations: COMMANDS.md
goto done

:done
echo.
pause
goto menu

:end
endlocal
