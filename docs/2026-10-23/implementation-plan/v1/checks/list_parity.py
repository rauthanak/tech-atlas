"""Rule 1 check: the Technologies list read from the stored answers gives
exactly what the old list (worked out live) gave, for each view, filter,
search and page, on the copy tech_atlas_p2 (status_parity.py makes it).

    docker cp list_parity.py old_technologies.py tech-radar-atlas-scale-1:/tmp/
    docker exec -w /app -e MONGO_DB=tech_atlas_p2 tech-radar-atlas-scale-1 python /tmp/list_parity.py
"""

import importlib.util
import json
import os
import time

assert os.environ["MONGO_DB"] == "tech_atlas_p2"
from app.api import technologies as new  # noqa: E402
from app.services import radar_status, tech_status  # noqa: E402
from app.services.db.mongo import get_collection  # noqa: E402

spec = importlib.util.spec_from_file_location("old_technologies", "/tmp/old_technologies.py")
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)

tech_status.refresh(get_collection("technologies").distinct("_id"))
norm = lambda x: json.loads(json.dumps(x, default=str))  # dict order never matters; list order does  # noqa: E731
KEYS = ("technologies", "total", "view_counts", "status_counts", "facets", "state_counts", "no_priority_counts",
        "over_floor", "summary", "catalog", "cited_pages")
CASES = [{}, {"skip": 100}, {"q": "ai"}, {"q": "quantum", "view": "tracked"}, {"status": "ready", "catalog": "yes"},
         {"state": "new_evidence"}, {"availability": "pilot"}, {"domain": "ai"}, {"domain": "ai", "subdomain": "ai--ai_agents"},
         {"trl_min": 5, "trl_max": 8}, {"evidence_verdict": "thin"}, {"fabric": "cloud"}, {"catalog": "no", "view": "emerging"},
         *[{"view": v} for v in radar_status.VIEWS], {"view": "not_assessed", "ids_only": True},
         {"view": "emerging", "ids_only": True}]
bad = 0
for case in CASES:
    args = {"limit": 50, **case}
    t = time.time(); a = old.list_technologies(**args); ta = time.time() - t
    t = time.time(); b = new.list_technologies(**args); tb = time.time() - t
    keys = ("ids", "total") if case.get("ids_only") else KEYS
    differ = [k for k in keys if norm(a.get(k)) != norm(b.get(k))]
    bad += bool(differ)
    print(f"{'ok  ' if not differ else 'DIFF'} {case}  old {ta:.2f}s new {tb:.2f}s" + (f"  differ: {differ}" if differ else ""))
    for k in differ[:2]:
        x, y = norm(a.get(k)), norm(b.get(k))
        print("   old:", str(x)[:300]); print("   new:", str(y)[:300])
print("all equal" if not bad else f"{bad} cases differ")
