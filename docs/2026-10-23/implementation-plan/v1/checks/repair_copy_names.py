"""On the 10-million-page copy made on 24 Oct (scale_copy.py before its fix): each cloned technology kept the
original's other names, so 30 technologies claimed each name. Gives copy k its own names ("agentic ai ~k"), as
scale_copy.py now does. Writes only to the copy's database.

    docker cp repair_copy_names.py tech-radar-atlas-scale-1:/tmp/ && docker exec tech-radar-atlas-scale-1 python /tmp/repair_copy_names.py
"""
import re
import time

from pymongo import UpdateOne

from app.services.db.mongo import get_collection, get_db

assert get_db().name == "tech_atlas_scale", "the copy only"
t0, techs, writes = time.time(), get_collection("technologies"), []
for t in techs.find({"_id": {"$regex": r"--\d+$"}}, {"aliases": 1}):
    k = re.search(r"--(\d+)$", t["_id"]).group(1)
    own = sorted({a if a.endswith(f" ~{k}") else f"{a} ~{k}" for a in t.get("aliases") or []})
    writes.append(UpdateOne({"_id": t["_id"]}, {"$set": {"aliases": own}}))
    if len(writes) == 2000:
        techs.bulk_write(writes)
        writes = []
if writes:
    techs.bulk_write(writes)
print(f"names repaired in {time.time() - t0:.0f}s")
