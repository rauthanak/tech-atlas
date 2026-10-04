#!/usr/bin/env bash
# ── tech-atlas · PROD ─────────────────────────────────────────────────────
# Same setup as start.sh, then serves without auto-reload.
# Defaults: HOST=0.0.0.0 PORT=8100
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --seed --python 3.12
  elif command -v python3.12 >/dev/null 2>&1; then
    python3.12 -m venv .venv
  else
    echo "error: need Python 3.12+ — install uv or python3.12" >&2
    exit 1
  fi
fi

source .venv/bin/activate
python -m pip install --quiet -r requirements.txt
python -m pip install --quiet -e .
[ -f .env ] || cp .env.example .env

python -m playwright install chromium >/dev/null 2>&1 || echo "warning: playwright chromium install failed — JS-heavy sources degrade to plain HTTP"

python scripts/create_db.py

exec uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8100}"
