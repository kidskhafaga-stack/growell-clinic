#!/usr/bin/env bash
# ============================================================
#   GROWELL CLINIC - One-click startup for Linux / macOS
#   Installs everything the app needs, then launches it.
# ============================================================
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "   GROWELL CLINIC"
echo "============================================================"

# 1) Ensure Python is available
if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] Python 3 is not installed. Install it from https://www.python.org/downloads/"
  exit 1
fi

# 2) Create the virtual environment on first run
if [ ! -d ".venv" ]; then
  echo "[1/4] Creating virtual environment..."
  python3 -m venv .venv
fi

# 3) Install / update dependencies
echo "[2/4] Installing dependencies..."
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null 2>&1 || true
pip install -r requirements.txt

# 4) Initialise the database + demo data on first run
if [ ! -f "instance/growell.db" ]; then
  echo "[3/4] Initialising database and seeding demo data..."
  flask --app run seed
else
  echo "[3/4] Database found - skipping initial seed."
fi

# 5) Launch the app and open the browser
echo "[4/4] Starting GROWELL CLINIC at http://localhost:5000"
URL="http://localhost:5000"
( sleep 2; (command -v xdg-open >/dev/null && xdg-open "$URL") || (command -v open >/dev/null && open "$URL") || true ) >/dev/null 2>&1 &
python run.py
