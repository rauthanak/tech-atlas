"""New evidence and readiness: one rule, read by every screen and batch.

A page is new evidence for a technology when the version a dossier built now
would read wasn't read by the technology's latest assessment. Linked means
`technologies_resolved` holds the technology's name (set-aside pages never
are); a page's version is its newest visit, where an unchanged revisit (a
stub) counts as the version it repeats. Assessments record the versions they
read (`dossier_pages`), and `dossier_from` when the size guard dropped the
oldest pages: a page whose newest visit is older than that isn't new, since
reassessing would drop it again. Assessments from before page versions were
recorded compare dates instead.

A technology's latest assessment is the newest run in which every fabric its
gate chose was scored, whatever happened to that run afterwards. Each
technology has one state (the first match wins), and the waiting lists are
read off it, so no technology is ever in two of them:
off · assessing · stopped_partway · not_assessed · new_evidence · no_pov · current
"""

from app.services.db.mongo import get_collection

LIVE = ("running", "terminating")
STOPPED = ("failed", "terminated")
PAGE_FIELDS = {"end_url": 1, "title": 1, "source_id": 1, "scraped_at": 1,
               "is_stub": 1, "ref_doc_id": 1}


def runs() -> list[dict]:
    """Every scoring run, newest first, with what the rule needs."""
    out = []
    for run in (get_collection("scoring_runs")
                .find({}, {"status": 1, "started_at": 1, "gates": 1, "progress": 1,
                           "technologies.tech_id": 1, "skipped.tech_id": 1,
                           "snapshot.fabrics._id": 1, "snapshot.fabrics.name": 1})
                .sort("started_at", -1)):
        run["tech_ids"] = {t["tech_id"] for t in run.pop("technologies", [])}
        run["skipped_ids"] = {s["tech_id"] for s in run.pop("skipped", [])}
        out.append(run)
    return out


def version(doc: dict) -> str:
    """The page version a visit shows: a stub repeats the one it references."""
    return doc["ref_doc_id"] if doc.get("is_stub") and doc.get("ref_doc_id") else doc["_id"]


def reading(rows: list[dict]) -> dict | None:
    """What a set of assessment rows read: the page versions (None for rows
    from before they were recorded), the size guard's cutoff, and when."""
    if not rows:
        return None
    recorded = all("dossier_pages" in a for a in rows)
    cutoffs = [a["dossier_from"] for a in rows if a.get("dossier_from")]
    return {"dossier_pages": {p for a in rows for p in a.get("dossier_pages") or []} if recorded else None,
            "dossier_from": max(cutoffs) if cutoffs else None,
            "assessed_at": min(a["created_at"] for a in rows)}


def new_pages(name: str, read: dict | None) -> list[dict]:
    """The technology's pages whose current version `read` (see reading())
    didn't include, newest first, as their newest visits. Without a reading,
    every linked page."""
    docs = get_collection("documents")
    latest, seen = [], set()
    for d in docs.find({"technologies_resolved": name}, PAGE_FIELDS).sort("scraped_at", -1):
        key = d.get("end_url") or d["_id"]
        if key not in seen:  # the newest visit, as the dossier builder picks it
            seen.add(key)
            latest.append(d)
    if read is None:
        return latest
    if read["dossier_pages"] is None:  # older assessment: new if collected after it
        refs = [d["ref_doc_id"] for d in latest if d.get("is_stub") and d.get("ref_doc_id")]
        collected = {r["_id"]: r["scraped_at"]
                     for r in docs.find({"_id": {"$in": refs}}, {"scraped_at": 1})} if refs else {}
        return [d for d in latest if collected.get(version(d), d["scraped_at"]) > read["assessed_at"]]
    cutoff = read["dossier_from"]
    return [d for d in latest
            if version(d) not in read["dossier_pages"] and not (cutoff and d["scraped_at"] < cutoff)]


def page(doc: dict) -> dict:
    """A new page as the API returns it."""
    return {"doc_id": doc["_id"], "title": doc.get("title"), "url": doc.get("end_url"),
            "source_id": doc.get("source_id"), "scraped_at": doc.get("scraped_at")}


def not_assessed_in(run: dict, rows: list[dict]) -> list[str]:
    """The run's fabrics a technology wasn't scored in (`rows`: its
    assessments): before scoring, its gate judged them not relevant."""
    scored = {a["fabric_id"] for a in rows}
    return [f.get("name") or f["_id"] for f in (run.get("snapshot") or {}).get("fabrics") or []
            if f["_id"] not in scored]


def _assessment(run: dict, rows: list[dict]) -> dict:
    rows = sorted(rows, key=lambda a: a["fabric_id"])
    return {"scoring_run_id": run["_id"], "run_status": run["status"],
            "pages_read": max(a.get("doc_count") or 0 for a in rows),
            "evidence_runs": sorted({r for a in rows for r in a.get("evidence_runs") or []})
            if any("evidence_runs" in a for a in rows) else None,  # None: not recorded
            **reading(rows),
            "fabrics": [{"assessment_id": a["_id"], "fabric_id": a["fabric_id"],
                         "fabric": a.get("fabric"),
                         "priority": (a.get("placement") or {}).get("priority"),
                         "horizon": (a.get("placement") or {}).get("horizon"),
                         "placement": a.get("placement"),  # its how-soon / how-big inputs say why one is missing
                         "tora": a.get("tora")} for a in rows],
            "not_assessed_in": not_assessed_in(run, rows)}


def _latest(tech_id: str, all_runs: list[dict], rows: dict[str, list[dict]]):
    """(latest assessment, unfinished): `unfinished` is a newer run still
    assessing the technology or stopped before all its fabrics were scored."""
    unfinished = None
    for run in all_runs:  # newest first
        if tech_id not in run["tech_ids"] or tech_id in run["skipped_ids"]:
            continue  # not in this run, or skipped for lack of evidence
        fabrics = rows.get(run["_id"], [])
        gated = (run.get("gates") or {}).get(tech_id)
        if fabrics and (set(gated) <= {a["fabric_id"] for a in fabrics} if gated is not None
                        else run["status"] == "completed"):
            return _assessment(run, fabrics), unfinished
        if unfinished is None and run["status"] in LIVE + STOPPED:
            unfinished = {"scoring_run_id": run["_id"], "status": run["status"],
                          "started_at": run["started_at"], "progress": run.get("progress") or {}}
    return None, unfinished


def _state(tech: dict, all_runs: list[dict], rows: dict[str, list[dict]], povs: set[str]) -> dict:
    assessment, unfinished = _latest(tech["_id"], all_runs, rows)
    new = new_pages(tech["name"], assessment)
    if not tech.get("enabled", True):
        state = "off"
    elif unfinished and unfinished["status"] in LIVE:
        state = "assessing"
    elif unfinished:
        state = "stopped_partway"
    elif assessment is None:
        state = "not_assessed"
    elif new:
        state = "new_evidence"
    elif f"{assessment['scoring_run_id']}:{tech['_id']}" not in povs:
        state = "no_pov"
    else:
        state = "current"
    return {"tech_id": tech["_id"], "name": tech["name"], "state": state,
            "assessment": assessment, "unfinished": unfinished, "new": new}


def states(tech_ids: list[str] | None = None) -> dict[str, dict]:
    """The state of each technology, by id: these ids, or by default every
    technology still in the register that a scoring run included."""
    all_runs = runs()
    if tech_ids is None:
        tech_ids = sorted(set().union(*(r["tech_ids"] for r in all_runs)))
    rows: dict[str, dict[str, list[dict]]] = {}
    for a in get_collection("assessments").find({"tech_id": {"$in": tech_ids}},
                                                {"measures": 0, "watch_metrics": 0}):
        rows.setdefault(a["tech_id"], {}).setdefault(a["scoring_run_id"], []).append(a)
    povs = set(get_collection("povs").distinct("_id", {"tech_id": {"$in": tech_ids}}))
    return {t["_id"]: _state(t, all_runs, rows.get(t["_id"], {}), povs)
            for t in get_collection("technologies").find({"_id": {"$in": tech_ids}},
                                                         {"name": 1, "enabled": 1})}


def state(tech_id: str) -> dict | None:
    return states([tech_id]).get(tech_id)


def list_states(tech_ids: list[str]) -> dict[str, dict]:
    """State, new-page count and assessment date for any technologies in the
    register: the Technologies list. A technology no scoring run included can
    only be off or not assessed, with every linked page new, so only the
    others need the full state (one page query each)."""
    included = set().union(*(r["tech_ids"] for r in runs()))
    full = states([t for t in tech_ids if t in included])
    out: dict[str, dict] = {}
    for t in get_collection("technologies").find({"_id": {"$in": tech_ids}},
                                                 {"enabled": 1, "page_count": 1}):
        s = full.get(t["_id"])
        out[t["_id"]] = ({"state": s["state"], "new_pages": len(s["new"]),
                          "assessed_at": (s["assessment"] or {}).get("assessed_at")} if s else
                         {"state": "not_assessed" if t.get("enabled", True) else "off",
                          "new_pages": t.get("page_count", 0), "assessed_at": None})
    return out


# ── the waiting lists, each read off the states ─────────────────────

def stopped_runs(all_states: dict[str, dict]) -> list[dict]:
    """Runs that stopped partway, newest first, each with the technologies it left."""
    by_run: dict[str, dict] = {}
    for s in all_states.values():
        if s["state"] == "stopped_partway":
            run = s["unfinished"]
            by_run.setdefault(run["scoring_run_id"], {**run, "tech_ids": []})["tech_ids"].append(s["tech_id"])
    return sorted(by_run.values(), key=lambda r: r["started_at"], reverse=True)


def with_new_evidence(all_states: dict[str, dict]) -> list[dict]:
    return sorted(({"tech_id": s["tech_id"], "name": s["name"], "new_pages": len(s["new"]),
                    "assessed_at": s["assessment"]["assessed_at"]}
                   for s in all_states.values() if s["state"] == "new_evidence"),
                  key=lambda t: (-t["new_pages"], t["name"]))


def _target(s: dict) -> dict:
    return {"scoring_run_id": s["assessment"]["scoring_run_id"], "tech_id": s["tech_id"],
            "technology": s["name"], "assessed_at": s["assessment"]["assessed_at"]}


def pov_targets(all_states: dict[str, dict]) -> list[dict]:
    """Ready for a Point of View: none written from the latest assessment's run."""
    return sorted((_target(s) for s in all_states.values() if s["state"] == "no_pov"),
                  key=lambda t: t["technology"])


def latest_assessments(all_states: dict[str, dict]) -> list[dict]:
    """Every technology with a latest assessment, each with the run to write
    from — what "Rewrite all" covers."""
    return sorted((_target(s) for s in all_states.values() if s["assessment"]),
                  key=lambda t: t["technology"])
