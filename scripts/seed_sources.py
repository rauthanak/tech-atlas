"""Seed the sources collection from seeds/sources.json.

Run from the project root with the venv active:  python scripts/seed_sources.py
Idempotent — each source is upserted by its id. The admin-controlled `enabled`
flag is preserved on existing sources (set only when a source is first inserted),
so portal/db toggles survive restarts.
"""

import json
from pathlib import Path

from pymongo import UpdateOne

from app.services.db.mongo import get_collection

SEED_FILE = Path(__file__).resolve().parent.parent / "seeds" / "sources.json"


def main() -> None:
    sources = json.loads(SEED_FILE.read_text())["sources"]
    ops = []
    for s in sources:
        fields = {k: v for k, v in s.items() if k != "enabled"}
        ops.append(UpdateOne(
            {"_id": s["source_id"]},
            {"$set": fields, "$setOnInsert": {"enabled": s.get("enabled", True)}},
            upsert=True,
        ))
    result = get_collection("sources").bulk_write(ops)
    print(f"{len(sources)} sources seeded ({result.upserted_count} new, {result.modified_count} updated)")


if __name__ == "__main__":
    main()
