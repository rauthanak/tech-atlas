"""Rule 1 check: the stored answers (services/tech_status) equal what the
radar works out live (services/radar_status.statuses), technology by
technology, on a copy of the live data. Runs in the test container only:
copies live into tech_atlas_p2 on the test database server, then compares.

    docker cp status_parity.py tech-radar-atlas-scale-1:/tmp/
    docker exec -w /app -e MONGO_DB=tech_atlas_p2 tech-radar-atlas-scale-1 python /tmp/status_parity.py
"""

import json
import os
import time

from pymongo import MongoClient

assert os.environ["MONGO_DB"] == "tech_atlas_p2" and os.environ["MONGO_URI"] != os.environ["LIVE_URI"]
live = MongoClient(os.environ["LIVE_URI"])["tech_atlas"]
target = MongoClient(os.environ["MONGO_URI"])
target.drop_database("tech_atlas_p2")
for name in live.list_collection_names():
    rows = list(live[name].find())
    for i in range(0, len(rows), 2000):
        target["tech_atlas_p2"][name].insert_many(rows[i:i + 2000])
print("copied live into tech_atlas_p2")

from app.services.db import bootstrap  # noqa: E402
from app.services import radar_status, tech_status  # noqa: E402
from app.services.db.mongo import get_collection  # noqa: E402

bootstrap.ensure_database()
ids = get_collection("technologies").distinct("_id")
t = time.time()
n = tech_status.refresh(ids)
print(f"stored {n} of {len(ids)} in {time.time() - t:.1f} s")
t = time.time()
live_rows = radar_status.statuses(ids)
print(f"worked out live in {time.time() - t:.1f} s")
norm = lambda x: json.loads(json.dumps(x, sort_keys=True, default=str))  # noqa: E731
stored = {r["_id"]: r["row"] for r in get_collection("tech_status").find({}, {"row": 1})}
diff = [i for i in ids if norm(stored.get(i)) != norm(live_rows.get(i))]
print(f"rows that differ: {len(diff)}", diff[:5])
for i in diff[:2]:
    a, b = norm(stored.get(i)), norm(live_rows.get(i))
    print(i, {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)})
