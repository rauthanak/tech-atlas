#!/bin/sh
# Prepare the database (idempotent, same steps as start.sh), then serve.
# The API loads the seeding data itself at start when it is new.
set -e
python scripts/create_db.py
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8100}"
