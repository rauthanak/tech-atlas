#!/usr/bin/env bash
# ── tech-atlas · DEV ──────────────────────────────────────────────────────
# Creates the venv if missing, installs requirements, prepares the
# database, and starts the API with auto-reload on http://127.0.0.1:8100
# (override with PORT=...)
set -euo pipefail
cd "$(dirname "$0")"

# 1. Virtual env (Python 3.12+)
if [ ! -d .venv ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --seed --python 3.12
  elif command -v python3.12 >/dev/null 2>&1; then
    python3.12 -m venv .venv
  elif command -v python3.13 >/dev/null 2>&1; then
    python3.13 -m venv .venv
  else
    echo "error: need Python 3.12+ — install uv (https://docs.astral.sh/uv/) or python3.12" >&2
    exit 1
  fi
fi

# 2. Activate + install
source .venv/bin/activate
python -m pip install --quiet -r requirements.txt
python -m pip install --quiet -e .

# 3. Headless browser for the crawler (idempotent, fast when present)
python -m playwright install chromium >/dev/null 2>&1 || echo "warning: playwright chromium install failed — JS-heavy sources degrade to plain HTTP"

# 4. .env
[ -f .env ] || cp .env.example .env

# 5. Database: create collections and indexes (the API loads the seeding data at start)
python scripts/create_db.py

# 6. Serve (dev: auto-reload; host/port in main.py, PORT env overrides)
exec python main.py
