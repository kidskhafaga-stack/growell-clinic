#!/usr/bin/env bash
# ============================================================
#   GROWELL CLINIC - Maintenance
#   The commands you need after an update, a move to a new PC,
#   or when something needs putting right. Nothing here runs by
#   itself: pick a number.
#
#   أوامر الصيانة - بعد التحديث أو النقل لجهاز جديد أو لما حاجة
#   تحتاج تظبيط. مفيش حاجة بتشتغل لوحدها: اختار رقم.
# ============================================================
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "[ERROR] Run ./start.sh once first - it creates the environment."
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

pause() { echo; read -r -p "Press Enter to continue... "; }

while true; do
  clear
  cat <<'MENU'
============================================================
   GROWELL CLINIC  |  Maintenance / الصيانة
============================================================

  AFTER AN UPDATE / بعد التحديث
    1  Apply database upgrades        (flask upgrade-db)
    2  Refresh the clinic catalogues  (vaccines, services, drugs)

  BACKUP / النسخ الاحتياطي
    3  Take a backup now              (database + photos)
    4  List backups

  DATA / البيانات
    5  Import a drug list             (CSV or JSON)
    6  Load the drug reference again
    7  Load the demo dataset          (for a presentation)
    8  Delete all operational data    (KEEPS users and catalogues)

  ACCOUNTS / الحسابات
    9  Create an administrator

  SETTINGS / الإعدادات
   10  Edit clinic.env (port, language)
   11  Show all available commands

    0  Exit
MENU
  echo
  read -r -p "Choose a number / اختار رقم: " choice
  echo
  case "$choice" in
    1) echo "Applying database upgrades - safe, adds only what is missing."
       flask --app run upgrade-db; pause ;;
    2) echo "Refreshing catalogues. Your own edits are kept."
       flask --app run seed-reference; pause ;;
    3) flask --app run shell -c "from app.utils.backups import create_backup; print('Backup created:', create_backup('manual'))"; pause ;;
    4) flask --app run shell -c "from app.utils.backups import list_backups
for b in list_backups():
    print(f\"{b['name']}  {b['size']//1024} KB  {b['has_files']} files\")"; pause ;;
    5) read -r -p "Path to the CSV/JSON file: " file
       [ -z "$file" ] && continue
       echo; echo "Reading it first WITHOUT saving, so you can see the numbers:"
       flask --app run import-drugs "$file" --dry-run
       echo; read -r -p "Import for real? (y/N): " ok
       [ "$ok" = "y" ] || [ "$ok" = "Y" ] && flask --app run import-drugs "$file"
       pause ;;
    6) flask --app run seed-drugbook; pause ;;
    7) echo "This adds made-up patients and visits, for a demonstration."
       read -r -p "Are you sure? (y/N): " ok
       [ "$ok" = "y" ] || [ "$ok" = "Y" ] && flask --app run seed-demo
       pause ;;
    8) echo "** This deletes patients, visits and invoices. Users, roles and"
       echo "** the catalogues are kept. A backup is taken first."
       read -r -p "Type DELETE to confirm: " ok
       if [ "$ok" = "DELETE" ]; then
         flask --app run shell -c "from app.utils.backups import create_backup; print('Backup first:', create_backup('manual'))"
         flask --app run reset-data
       else
         echo "Cancelled."
       fi
       pause ;;
    9) flask --app run create-admin; pause ;;
    10) [ -f clinic.env ] || python -c "from app.settings_file import ensure_file; ensure_file()"
        "${EDITOR:-nano}" clinic.env
        echo "Restart the program for the change to take effect."; pause ;;
    11) flask --app run --help
        echo; echo "Full reference with explanations: COMMANDS.md"; pause ;;
    0) exit 0 ;;
    *) ;;
  esac
done
