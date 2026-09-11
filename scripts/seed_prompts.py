"""Seed the prompts collection from seeds/prompts.json.

Run from the project root with the venv active:  python scripts/seed_prompts.py
Idempotent — each prompt is upserted by its name.
"""

import json
from pathlib import Path

from pymongo import ReplaceOne

from app.services.db.mongo import get_collection

SEED_FILE = Path(__file__).resolve().parent.parent / "seeds" / "prompts.json"


def main() -> None:
    prompts = json.loads(SEED_FILE.read_text())["prompts"]
    result = get_collection("prompts").bulk_write(
        [ReplaceOne({"_id": p["name"]}, {"_id": p["name"], **p}, upsert=True) for p in prompts]
    )
    print(f"{len(prompts)} prompts seeded ({result.upserted_count} new, {result.modified_count} updated)")


if __name__ == "__main__":
    main()
