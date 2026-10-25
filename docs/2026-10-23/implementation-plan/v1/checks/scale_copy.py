"""A copy of the radar's database at many times its size (10 million pages
and 30× technologies by default; see the sizes below), for the speed check (perf.py). Built from the live database by
cloning its records with new ids, so every shape is real; no model calls. Pages are cloned a whole live set at a
time (24 Oct): each set gets its own addresses and text fingerprints, so every clone is a page of its own (spec §3
of the 24 Oct scale plan would otherwise join them), and live's revisits and new versions stay as they are.
It reads the live database and writes only to the speed check's own server
(the atlas-scale and mongo-scale services, with hard memory caps), never to
the live one.

    docker compose --profile scale up -d mongo-scale atlas-scale
    docker cp scale_copy.py tech-radar-atlas-scale-1:/tmp/
    docker exec -w /app tech-radar-atlas-scale-1 python /tmp/scale_copy.py
    (or as a one-off: docker compose --profile scale run --rm --no-deps -v "$PWD/docs/...:/checks"
     atlas-scale python /checks/scale_copy.py)
"""

import os
import sys
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from pymongo import MongoClient

LIVE, SCALE = "tech_atlas", os.environ.get("SCALE_DB", "tech_atlas_scale")
# the size of the copy; the defaults are the 10-million-page test of 24 Oct (1 million on 23 Oct: 10, 1,000,000, 30, 365)
TECH_COPIES = int(os.environ.get("TECH_COPIES", 30))       # 10,514 technologies → about 315,000
SETS = int(os.environ.get("SETS", 2_000))                  # 5,719 visits, 5,022 pages → 11.4 million visits, 10 million pages
RUN_COPIES = int(os.environ.get("RUN_COPIES", 100))        # 6 collections → 600
SPREAD_DAYS = int(os.environ.get("SPREAD_DAYS", 730))      # pages collected over two years
BATCH = 2_000
assert SCALE != LIVE, "the scale copy never writes to the live database"

LIVE_URI, SCALE_URI = os.environ["LIVE_URI"], os.environ["MONGO_URI"]
assert LIVE_URI != SCALE_URI, "the copy goes to the speed check's own database server, not the live one"
live, scale = MongoClient(LIVE_URI)[LIVE], MongoClient(SCALE_URI)[SCALE]
scale.client.drop_database(SCALE)
t0 = time.time()
# the indexes first, as on a real install: the records are indexed as they go in, so nothing is built afterwards
from app.services.db import bootstrap  # noqa: E402
assert bootstrap.get_db().name == SCALE, "the indexes go to the copy"
bootstrap.ensure_database()
bootstrap.ensure_indexes()


def say(what: str) -> None:
    print(f"{time.time() - t0:7.0f}s  {what}", flush=True)


def tag(value: str, k: int) -> str:
    """The k-th copy of a name or id; copy 0 is the original."""
    return value if k == 0 else f"{value} ~{k}"


def tid(value: str, k: int) -> str:
    return value if k == 0 else f"{value}--{k}"


# configuration and small records: as they are
SMALL = ["seeding", "subdomains", "imports", "trl_levels", "path_steps", "settings", "availability", "recipes",
         "recheck_jobs", "sources", "assumptions", "find_evidence_jobs", "fabrics", "pov_compose_jobs", "measures",
         "resolves", "edition_povs", "editions", "mechanisms", "scoring_config", "pov_views", "prompts",
         "classify_runs", "domains", "signals", "tag_runs"]
for name in SMALL:
    rows = list(live[name].find())
    if rows:
        scale[name].insert_many(rows)
say(f"copied {len(SMALL)} small collections")

# technologies, 10×: names and ids get a copy number
techs = list(live["technologies"].find())
for k in range(TECH_COPIES):
    scale["technologies"].insert_many([{**t, "_id": tid(t["_id"], k), "name": tag(t["name"], k),
                                        "aliases": [tag(a, k) for a in t.get("aliases") or []],  # each copy its own names
                                        **({"label": tag(t["label"], k)} if t.get("label") else {})} for t in techs])
say(f"technologies: {scale['technologies'].estimated_document_count():,}")

# what people decided, assessments and Points of View, per technology copy
for name, key in (("decisions", "tech_id"), ("assessments", "tech_id"), ("povs", "tech_id")):
    rows = list(live[name].find())
    for k in range(TECH_COPIES):
        scale[name].insert_many([{**r, "_id": f"{r['_id']}~{k}" if k else r["_id"], key: tid(r[key], k),
                                  **({"technology": tag(r["technology"], k)} if r.get("technology") else {})}
                                 for r in rows])
    say(f"{name}: {scale[name].estimated_document_count():,}")

# assessment runs list their technologies: each run lists every copy of its own
for r in live["scoring_runs"].find():
    entries = r.get("technologies") or []
    r["technologies"] = [{**e, "tech_id": tid(e["tech_id"], k), "name": tag(e["name"], k)}
                         for k in range(TECH_COPIES) for e in entries]
    scale["scoring_runs"].insert_one(r)
say("scoring runs")

# collections: 30 copies of each, so a page belongs to one of about 180
runs = list(live["runs"].find())
for k in range(RUN_COPIES):
    scale["runs"].insert_many([{**r, "_id": f"{r['_id']}~{k}" if k else r["_id"]} for r in runs])
say(f"runs: {scale['runs'].estimated_document_count():,}")

# pages: whole copies of live's visits, each set with its own addresses, text fingerprints, collections and dates
def address(url: str, n: int) -> str:
    u = urlsplit(url)
    return urlunsplit((u.scheme, u.netloc, f"{u.path.rstrip('/')}/copy-{n}", u.query, u.fragment))


pages = list(live["documents"].find().sort("scraped_at", 1))
for n in range(SETS):
    k, r = n % TECH_COPIES, n % RUN_COPIES
    names = lambda d, key: [tag(x, k) for x in d.get(key) or []]  # noqa: E731
    batch = [{**d, "_id": f"{d['_id']}-{n}", "ref_doc_id": f"{d['ref_doc_id']}-{n}" if d.get("ref_doc_id") else None,
              "end_url": address(d["end_url"], n), "content_hash": f"{d.get('content_hash')}-{n}",
              # spread over SPREAD_DAYS, as Tata's would be: set n is collected n % SPREAD_DAYS days earlier
              "scraped_at": (datetime.fromisoformat(d["scraped_at"]) - timedelta(days=n % SPREAD_DAYS)).isoformat(),
              "run_id": f"{d['run_id']}~{r}" if r else d["run_id"],
              "technologies": names(d, "technologies"), "technologies_resolved": names(d, "technologies_resolved"),
              "mentions": names(d, "mentions")} for d in pages]
    for i in range(0, len(batch), BATCH):
        scale["documents"].insert_many(batch[i:i + BATCH], ordered=False)
    if n % 50 == 0:
        say(f"pages: {(n + 1) * len(pages):,} visits")

# model calls, 10×
calls = list(live["llm_calls"].find())
for k in range(TECH_COPIES):
    scale["llm_calls"].insert_many([{**c, "_id": f"{c['_id']}~{k}" if k else c["_id"]} for c in calls])
say(f"model calls: {scale['llm_calls'].estimated_document_count():,}")

stats = scale.command("dbstats")
say(f"done: {stats['dataSize'] / 1e9:.1f} GB of data, indexed as it went in")
sys.exit(0)
