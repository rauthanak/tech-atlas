"""As why_no_pages.py, but a name like 'Wi-Fi 7 (802.11be)' is also looked
for as 'Wi-Fi 7' and '802.11be'. Reads only."""
import json, re
from app.services.db.mongo import get_collection as g
rows = json.load(open("/tmp/now2.json"))["rows"]
zero = [r for r in rows if r["in_catalog"] and r["pages"] == 0]
techs = {t["_id"]: t for t in g("technologies").find({"_id": {"$in": [r["id"] for r in zero]}}, {"name": 1, "label": 1, "aliases": 1})}
docs = [" ".join(str(d.get(k) or "") for k in ("title", "summary_text", "extracted_text")).lower()
        for d in g("documents").find({"is_stub": False}, {"title": 1, "summary_text": 1, "extracted_text": 1})]
QUALIFIERS = {"iot", "ai", "blockchain", "robotics", "cloud", "edge", "5g", "6g"}


def forms(name):
    """The name, its main part, and a bracketed short form (DID, NTN, 802.11be)
    but not a bracketed qualifier like (IoT) or (blockchain)."""
    out = {name.lower()}
    m = re.match(r"^(.*?)\s*\((.*?)\)\s*$", name)
    if m:
        out.add(m.group(1).strip().lower())
        short = m.group(2).strip()
        if re.search(r"[A-Z0-9]", short) and " " not in short and short.lower() not in QUALIFIERS:
            out.add(short.lower())
    return {x for x in out if len(x) > 2}
found = {}
for r in zero:
    t = techs[r["id"]]
    names = set().union(*(forms(x) for x in [(t.get("label") or t["name"]), *(t.get("aliases") or [])]))
    pats = [re.compile(r"(?<![\w-])" + re.escape(x) + r"(?![\w-])") for x in names]
    n = sum(any(p.search(d) for p in pats) for d in docs)
    if n:
        found[t["name"]] = n
print("catalog with no pages:", len(zero), "| named on at least one page:", len(found),
      "| on 3+ pages:", sum(v >= 3 for v in found.values()))
print(sorted(found.items(), key=lambda x: -x[1])[:15])
