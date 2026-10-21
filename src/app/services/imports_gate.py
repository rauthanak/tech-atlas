"""The Before scoring list's import items: proposed matches waiting for a
person (filled in with imports, item 11)."""

from app.services.db.mongo import get_collection


def items() -> list[dict]:
    out = []
    for imp in get_collection("imports").find({"status": {"$in": ["reviewing", "ready"]}}).sort("at", -1):
        waiting = [i for i in imp.get("items") or [] if i.get("group") == "proposed" and i.get("decision") is None]
        if waiting:
            out.append({"kind": "import_matches", "count": len(waiting),
                        "sentence": f"{len(waiting)} proposed {'match' if len(waiting) == 1 else 'matches'} from "
                                    f"{imp.get('file')} to accept or reject",
                        "sub": "Nothing from the file is saved until the import is confirmed.",
                        "href": f"/admin/import?id={imp['_id']}"})
    return out
