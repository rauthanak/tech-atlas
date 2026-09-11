"""Seed the scoring configuration: fabrics, measures, scoring_config.

Run from the project root with the venv active:  python scripts/seed_scoring.py

Unlike the sources/prompts seeders, this INSERTS MISSING ENTRIES ONLY — it
never overwrites an existing document, because these collections are edited
by the admin in the portal and those edits must survive restarts and reseeds.
Pass --replace to force the seed values back in (discards admin edits).
"""

import json
import sys
from pathlib import Path

from pymongo import ReplaceOne, UpdateOne

from app.services.db.mongo import get_collection

SEEDS = Path(__file__).resolve().parent.parent / "seeds"
COLLECTIONS = {"fabrics": "fabric_id", "measures": "measure_id", "scoring_config": "name"}


def main() -> None:
    replace = "--replace" in sys.argv
    for collection, id_field in COLLECTIONS.items():
        docs = json.loads((SEEDS / f"{collection}.json").read_text())[collection]
        if replace:
            ops = [ReplaceOne({"_id": d[id_field]}, {"_id": d[id_field], **d}, upsert=True)
                   for d in docs]
        else:
            ops = [UpdateOne({"_id": d[id_field]},
                             {"$setOnInsert": {"_id": d[id_field], **d}}, upsert=True)
                   for d in docs]
        result = get_collection(collection).bulk_write(ops)
        kept = len(docs) - result.upserted_count - (result.modified_count if replace else 0)
        print(f"{collection}: {result.upserted_count} inserted, "
              + (f"{result.modified_count} replaced" if replace else f"{kept} existing kept"))


if __name__ == "__main__":
    main()
