"""The Before scoring list's review items: an import's proposed matches
waiting for a person (item 11), and the sub-domains the model proposed while
classifying, waiting to be accepted, merged or renamed."""

from app.services.db.mongo import get_collection
from app.services.imports import replaced_by, waiting as waiting_on


def items() -> list[dict]:
    out = []
    for imp in get_collection("imports").find({"status": {"$in": ["reviewing", "ready"]}}).sort("at", -1):
        waiting = waiting_on(imp)
        if waiting and not replaced_by(imp):  # a newer import of the same file, confirmed, settled them
            out.append({"kind": "import_matches", "count": waiting,
                        "sentence": f"{waiting:,} proposed {'match' if waiting == 1 else 'matches'} from "
                                    f"{imp.get('file')} to accept or reject",
                        "sub": "Nothing from the file is saved until the import is confirmed.",
                        "href": f"/admin/import?id={imp['_id']}"})
    proposed = get_collection("subdomains").count_documents({"status": "new"})
    if proposed:
        out.append({"kind": "subdomains", "count": proposed,
                    "sentence": f"{proposed:,} {'sub-domain' if proposed == 1 else 'sub-domains'} the model proposed, to accept, merge or rename",
                    "sub": "Classify files a technology under one when none of Tata's fits; it stays proposed until a person reviews it.",
                    "href": "/admin/classification/domains"})
    return out
