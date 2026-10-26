"""CR05 dry-run, read-only, on a COPY of the live data (tech_atlas_test_copy):
how many stored scores would the new rule have emptied, and why. The evidence
text isn't stored with an assessment, so the allowed links are rebuilt from the
pages it read (dossier_pages) and every visit of those pages."""
import sys
from collections import Counter

from pymongo import MongoClient

sys.path.insert(0, "src")
from app.services.pages import link_key  # noqa: E402

import os
db = MongoClient(os.environ.get("COPY_URI", "mongodb://mongo:27017"))["tech_atlas_test_copy"]
assert db.name == "tech_atlas_test_copy"
fabrics = {f["_id"]: f for f in db.fabrics.find()}
scored = emptied = 0
why, examples = Counter(), []
for a in db.assessments.find({}, {"measures": 1, "dossier_pages": 1, "fabric_id": 1, "tech_id": 1}):
    pages = a.get("dossier_pages") or []
    keys = set(db.documents.distinct("page_key", {"_id": {"$in": pages}}))
    urls = db.documents.distinct("end_url", {"$or": [{"_id": {"$in": pages}}, {"page_key": {"$in": list(keys)}}]})
    import re
    tcl = (fabrics.get(a.get("fabric_id")) or {}).get("tcl_today") or ""
    urls += [u.rstrip(".,;)") for u in re.findall(r"https?://\S+", tcl)]
    allowed = {link_key(u) for u in urls if u}
    for mid, r in (a.get("measures") or {}).items():
        if r.get("score") is None or r.get("scope") == "tata":
            continue
        scored += 1
        cited = [u for u in (r.get("evidence_urls") or []) if isinstance(u, str)]
        if not any(link_key(u.strip()) in allowed for u in cited):
            emptied += 1
            why["no cited link among the pages read"] += 1
            if len(examples) < 8:
                examples.append((a["tech_id"], a.get("fabric_id"), mid, cited[:2]))
print(f"stored scores checked: {scored}; would be emptied: {emptied} ({100 * emptied / max(scored, 1):.2f}%)")
print(dict(why))
for e in examples:
    print(e)
