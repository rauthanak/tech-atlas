#!/bin/sh
# Seed the database (idempotent, same steps as start.sh), then serve.
set -e
python scripts/create_db.py
python scripts/seed_sources.py
python scripts/seed_prompts.py
python scripts/seed_scoring.py
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8100}"
