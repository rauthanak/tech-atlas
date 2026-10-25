"""Why catalog technologies have no pages: is the name absent from every
collected page, or present but not linked to the technology? Reads only."""
import json, re
from collections import Counter
from app.services.db.mongo import get_collection as g

rows = json.load(open("/tmp/now2.json"))["rows"]
zero = [r for r in rows if r["in_catalog"] and r["pages"] == 0]
techs = {t["_id"]: t for t in g("technologies").find({"_id": {"$in": [r["id"] for r in zero]}}, {"name": 1, "aliases": 1, "imported": 1})}
docs = [" ".join(str(d.get(k) or "") for k in ("title", "summary_text", "extracted_text")).lower()
        for d in g("documents").find({"is_stub": False}, {"title": 1, "summary_text": 1, "extracted_text": 1})]
print("pages searched", len(docs))
hits, words = [], Counter()
for r in zero:
    t = techs[r["id"]]
    names = {t["name"].lower(), *[a.lower() for a in t.get("aliases") or []]}
    n = sum(any(re.search(r"\b" + re.escape(x) + r"\b", d) for x in names) for d in docs)
    words[len(t["name"].split())] += 1
    if n:
        hits.append((t["name"], n))
print("named verbatim on at least one page but not linked:", len(hits))
print(sorted(hits, key=lambda h: -h[1])[:25])
print("name length in words:", sorted(words.items()))
print("domains:", Counter(r["domain"] for r in zero).most_common())
import random; random.seed(1)
print("sample of the rest:", [techs[r["id"]]["name"] for r in random.sample([r for r in zero if techs[r["id"]]["name"] not in {h for h,_ in hits}], 25)])
