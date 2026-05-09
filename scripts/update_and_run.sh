#!/usr/bin/env bash
set -euo pipefail

echo "[EUT] Syncing repository..."
git fetch --all --prune
git pull --rebase --autostash

echo "[EUT] Checking important details..."
python -m pytest -q

if [ ! -d .venv ]; then
  python -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt >/dev/null

echo "[EUT] Launching cockpit..."
python main.py
