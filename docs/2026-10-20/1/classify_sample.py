"""The Classify sample (plan 9, item 8): classify 50 technologies — those
whose names match Tata's file exactly and have pages, then others with pages
— and compare domain, commercial availability and TRL with Tata's own labels.

Inside the API container, with Tata's file copied in:
    python classify_sample.py start /tmp/tata.xlsx      # starts the run, prints its id
    python classify_sample.py report /tmp/tata.xlsx RUN  # writes classify-sample.md beside this script
"""

import json
import random
import sys
import urllib.request
from pathlib import Path

import openpyxl

API = "http://localhost:8100/api"
OUT = Path(__file__).with_name("classify-sample.md")


def get(path):
    return json.loads(urllib.request.urlopen(API + path).read())


def post(path, body):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Time-Zone": "America/Chicago"})
    return json.loads(urllib.request.urlopen(req).read())


def tata_rows(xlsx):
    sheet = openpyxl.load_workbook(xlsx, read_only=True)["New Emerging Technologies"]
    rows = list(sheet.iter_rows(values_only=True))
    head = [str(h or "").strip() for h in rows[0]]
    return [dict(zip(head, r)) for r in rows[1:] if r[0]]


def matches(xlsx):
    """Tata's rows whose name is a technology's name or alias, with pages."""
    sys.path.insert(0, "/app/src")
    from app.services.db.mongo import get_collection
    by_name = {}
    for t in get_collection("technologies").find({"page_count": {"$gt": 0}, "enabled": {"$ne": False}},
                                                 {"name": 1, "aliases": 1, "page_count": 1}):
        for n in {t["name"], *t.get("aliases", [])}:
            by_name.setdefault(n.lower().strip(), t)
    out = {}
    for r in tata_rows(xlsx):
        t = by_name.get(str(r["Technology Name"]).lower().strip())
        if t:
            out[t["_id"]] = r
    others = [t["_id"] for t in get_collection("technologies").find(
        {"page_count": {"$gte": 3}, "enabled": {"$ne": False}, "_id": {"$nin": list(out)}}, {"_id": 1})]
    return out, others


def start(xlsx):
    matched, others = matches(xlsx)
    random.seed(20)
    ids = list(matched)[:50] + random.sample(others, max(0, 50 - len(matched)))
    run = post("/classify", {"tech_ids": ids})
    print(json.dumps({"run_id": run["run_id"], "technologies": len(ids), "matched_to_tata": len(matched)}))


DOMAIN = {"AI": "ai", "Cloud": "cloud", "Cybersecurity": "cybersecurity", "Edge Computing": "edge_computing",
          "IoT": "iot", "Networking": "networking", "Quantum": "quantum",
          "Robotics and Autonomous Systems": "robotics", "Blockchain/Web3": "blockchain_web3",
          "Blockchain": "blockchain_web3", "Blockchain/Cybersecurity": "blockchain_web3"}
AVAIL = {"Research": "research", "Pilot": "pilot", "Early Commercial": "early_commercial", "Mature": "mature"}


def report(xlsx, run_id):
    matched, _ = matches(xlsx)
    run = next(r for r in get("/classify/runs")["runs"] if r["_id"] == run_id)
    usage = get(f"/usage?run_id={run_id}")["total"]
    rows, agree = [], {"domain": [0, 0], "availability": [0, 0], "trl": [0, 0], "trl_within_1": [0, 0]}
    for tech_id, r in matched.items():
        t = get(f"/technologies?q={urllib.parse.quote(tech_id.replace('-', ' '))}&limit=50")
        row = next((x for x in t["technologies"] if x["_id"] == tech_id), None)
        if row is None or not row["classification"]["classified_at"]:
            continue
        c = row["classification"]
        ours = {"domain": c["domain"]["id"], "availability": c["availability"]["id"], "trl": c["trl"]["level"]}
        theirs = {"domain": DOMAIN.get(str(r.get("Domain") or "").strip()),
                  "availability": AVAIL.get(str(r.get("Commercial Availability") or "").strip()),
                  "trl": int(r["TRL"]) if str(r.get("TRL") or "").strip().isdigit() else None}
        for k in ("domain", "availability", "trl"):
            if theirs[k] is not None and ours[k] is not None:
                agree[k][1] += 1
                agree[k][0] += int(ours[k] == theirs[k])
        if theirs["trl"] and ours["trl"]:
            agree["trl_within_1"][1] += 1
            agree["trl_within_1"][0] += int(abs(ours["trl"] - theirs["trl"]) <= 1)
        rows.append((row.get("label") or row["name"], theirs, ours, c["evidence"]["verdict"] if c["evidence"] else "—"))
    pct = lambda a: f"{a[0]} of {a[1]} ({round(100 * a[0] / a[1])}%)" if a[1] else "none to compare"
    sent = usage["input_tokens"] + usage["cache_read_tokens"] + usage["cache_write_tokens"]
    lines = [
        "# Classify sample (plan 9, item 8)", "",
        f"Run `{run_id}`: {run['done']} of {run['total']} technologies, status {run['status']}, "
        f"{len(run.get('failed') or [])} with a failed answer, {run.get('retries', 0)} answers asked again alone.", "",
        "## Tokens", "",
        f"- {usage['calls']} calls ({usage['failed']} failed)",
        f"- {sent:,} tokens sent, {usage['cache_read_tokens']:,} of them reused ({round(100 * usage['cache_read_tokens'] / max(sent, 1))}%)",
        f"- {usage['output_tokens']:,} tokens written back",
        f"- per technology: about {sent // max(run['done'], 1):,} sent and {usage['output_tokens'] // max(run['done'], 1):,} written",
        "", "## Agreement with Tata's labels", "",
        f"Technologies matching Tata's file exactly, with pages: {len(rows)}.", "",
        f"- Domain: {pct(agree['domain'])}",
        f"- Commercial availability: {pct(agree['availability'])}",
        f"- TRL, exact: {pct(agree['trl'])}; within one level: {pct(agree['trl_within_1'])}", "",
        "| Technology | Tata: domain · availability · TRL | Classify: domain · availability · TRL | Evidence |",
        "|---|---|---|---|"]
    for name, theirs, ours, ev in sorted(rows):
        fmt = lambda d: f"{d['domain'] or '—'} · {d['availability'] or '—'} · {d['trl'] or '—'}"
        lines.append(f"| {name} | {fmt(theirs)} | {fmt(ours)} | {ev} |")
    OUT.write_text("\n".join(lines) + "\n")
    print(OUT.read_text()[:3000])


if __name__ == "__main__":
    import urllib.parse  # noqa: F401  (used in report)
    {"start": lambda: start(sys.argv[2]), "report": lambda: report(sys.argv[2], sys.argv[3])}[sys.argv[1]]()
