"""The radar against Tata's catalog: what the radar found that the catalog
doesn't have, and what the catalog has that the radar barely sees, with why.
Reads only the database (no model calls); writes JSON for make_comparison.py.

    docker cp compare_catalog.py tech-radar-atlas-1:/tmp/ && docker exec tech-radar-atlas-1 python /tmp/compare_catalog.py <label> > out.json
"""

import json
import sys
from collections import defaultdict

from app.services import classify_effective, decisions, radar_status
from app.services.db.mongo import get_collection as g

ENOUGH = 3  # pages: below this the radar barely sees a technology

label = sys.argv[1] if len(sys.argv) > 1 else "baseline"
sources = {s["_id"]: s for s in g("sources").find()}
on = sorted(s["name"] for s in sources.values() if s.get("enabled"))

# per technology: the pages, the sources they came from, the first date seen
pages: dict[str, set] = defaultdict(set)
by_source: dict[str, set] = defaultdict(set)
first: dict[str, str] = {}
for d in g("documents").find({}, {"technologies_resolved": 1, "source_id": 1, "published_date": 1, "scraped_at": 1, "end_url": 1}):
    when = str(d.get("published_date") or d.get("scraped_at") or "")[:10]
    for t in d.get("technologies_resolved") or []:
        pages[t].add(d.get("end_url") or d["_id"])
        by_source[t].add(d.get("source_id"))
        if when and (t not in first or when < first[t]):
            first[t] = when

techs = list(g("technologies").find({"enabled": True}))
choices = decisions.active([t["_id"] for t in techs], ["catalog"])
everyone = decisions.active([t["_id"] for t in techs])
mine: dict[str, list] = defaultdict(list)
for d in everyone:
    mine[d["tech_id"]].append(d)
names = classify_effective.names()
st = radar_status.statuses([t["_id"] for t in techs])
rows = []
for t in techs:
    name = t["name"]
    cls = classify_effective.effective(t, mine.get(t["_id"], []), names)
    rows.append({
        "id": t["_id"], "technology": t.get("label") or name,
        "in_catalog": decisions.in_catalog(t, decisions.pick(choices, "catalog", tech_id=t["_id"]))["in"],
        "catalog_name": ((t.get("imported") or {}).get("row") or {}).get("name"),
        "domain": (cls.get("domain") or {}).get("name"),
        "availability": (cls.get("availability") or {}).get("name"),
        "trl": (cls.get("trl") or {}).get("level"),
        "pages": len(pages.get(name, ())),
        "sources": sorted(sources.get(s, {}).get("name", s) for s in by_source.get(name, ()) if s),
        "status": st.get(t["_id"], {}).get("status"), "status_reason": st.get(t["_id"], {}).get("reason"),
    })
print(json.dumps({"label": label, "sources_on": on, "enough": ENOUGH, "rows": rows}, default=str))
