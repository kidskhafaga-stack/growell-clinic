#!/usr/bin/env bash
# ============================================================
#   GROWELL CLINIC - One-click startup for Linux / macOS
#   Installs everything the app needs, then launches it.
#
#   To change the port: edit clinic.env (PORT=8080), or pass it
#   here:   ./start.sh 8080
#   For maintenance commands (backup, upgrade, import...), run
#   ./tools.sh - or read COMMANDS.md.
# ============================================================
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "   GROWELL CLINIC  |  PediaPro"
echo "============================================================"

# 0) Pull the latest version if online (safe to skip offline / local changes)
if command -v git >/dev/null 2>&1 && [ -d ".git" ]; then
  echo "[0/5] Checking for updates..."
  git pull --ff-only || echo "      (skipped update - offline or local changes; continuing)"
fi

# 1) Ensure Python is available
if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] Python 3 is not installed. Install it from https://www.python.org/downloads/"
  exit 1
fi

# 2) Create the virtual environment on first run
if [ ! -d ".venv" ]; then
  echo "[1/5] Creating virtual environment..."
  python3 -m venv .venv
fi

# 3) Install / update dependencies
echo "[2/5] Installing dependencies..."
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null 2>&1 || true
pip install -r requirements.txt

# 4) Local settings file (port, language) on first run
if [ ! -f "clinic.env" ]; then
  echo "[3/5] Creating clinic.env - edit it to change the port."
  python -c "from app.settings_file import ensure_file; ensure_file()"
fi

# 5) Initialise the database on first run, then ALWAYS upgrade it. The upgrade
#    step is what adds new columns/tables after an update, so it must run on
#    every start - not only when a database already existed.
if [ ! -f "instance/growell.db" ]; then
  echo "[4/5] Initialising database and seeding the clinic catalogues..."
  flask --app run seed
fi
echo "[4/5] Applying any safe database upgrades..."
if ! flask --app run upgrade-db; then
  echo "[ERROR] Database upgrade failed - do NOT use the app before fixing this."
  echo "        Your data is untouched. Run ./tools.sh and choose \"Restore a backup\""
  echo "        if you need to go back."
  exit 1
fi

# 6) Work out the port: the argument wins, then clinic.env, then 5000
APP_PORT="$(python -c "import sys;from app.settings_file import load_env;load_env();from run import chosen_port;print(chosen_port([a for a in sys.argv[1:] if a]))" "${1:-}")"

# 7) Launch the app and open the browser
echo "[5/5] Starting GROWELL CLINIC at http://localhost:${APP_PORT}"
URL="http://localhost:${APP_PORT}"
( sleep 2; (command -v xdg-open >/dev/null && xdg-open "$URL") || (command -v open >/dev/null && open "$URL") || true ) >/dev/null 2>&1 &
python run.py "$APP_PORT"
