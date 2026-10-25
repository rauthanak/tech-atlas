"""Small builders for the stored shapes the evidence tests need: pages,
technologies, scoring runs, assessments and Points of View."""


def at(day: int) -> str:
    return f"2026-09-{day:02d}T00:00:00+00:00"


def tech(db, tech_id: str = "edge-ai", name: str = "edge ai", enabled: bool = True) -> None:
    db["technologies"].insert_one({"_id": tech_id, "name": name, "enabled": enabled,
                                   "aliases": [name], "page_count": 0, "source_count": 0})


def page(db, url: str, day: int, tech: str | None = "edge ai", stub_of: str | None = None,
         **extra) -> str:
    """A visit to `url`; `stub_of` makes it an unchanged revisit of that version.
    Marked as storing marks it (services/pages): the page's newest visit, and how many."""
    doc_id = f"{url}@{day}"
    docs = db["documents"]
    docs.update_many({"page_key": url, "scraped_at": {"$lt": at(day)}}, {"$set": {"latest": False}})
    docs.insert_one({"_id": doc_id, "end_url": url, "page_key": url, "title": url, "scraped_at": at(day),
                     "latest": not docs.count_documents({"page_key": url, "scraped_at": {"$gt": at(day)}}),
                     "visits": docs.count_documents({"page_key": url}) + 1,
                     "is_stub": stub_of is not None, "ref_doc_id": stub_of,
                     "technologies_resolved": [tech] if tech else [],
                     "source_id": "s", "run_id": "c", **extra})
    return doc_id


def with_text(db, *docs: dict) -> None:
    """Visits stored the way storing keeps them: each one's `extracted_text`
    apart, in page_texts."""
    for d in docs:
        text = d.pop("extracted_text")
        db["documents"].insert_one({**d, "has_text": True})
        db["page_texts"].insert_one({"_id": d["_id"], "text": text, "page_key": d.get("end_url"),
                                     "run_id": d.get("run_id"), "superseded": False})


def run(db, run_id: str, day: int, status: str = "completed", techs=("edge-ai",),
        gates: dict | None = None, params: dict | None = None, fabrics=("cloud",)) -> None:
    db["scoring_runs"].insert_one({
        "_id": run_id, "status": status, "started_at": at(day), "params": params or {},
        "snapshot": {"fabrics": [{"_id": f, "name": f.title()} for f in fabrics]},
        "technologies": [{"tech_id": t, "name": t} for t in techs], "skipped": [],
        "gates": gates if gates is not None else {t: ["cloud"] for t in techs},
        "progress": {"techs_done": 0, "techs_total": len(techs)}})


def assessment(db, run_id: str, day: int, pages: list[str] | None = None, tech_id: str = "edge-ai",
               fabric: str = "cloud", dossier_from: str | None = None, scores: list | None = None,
               priority: str | None = "P2") -> str:
    """`pages=None` makes an assessment from before page versions were recorded;
    `scores` gives its measures, None for one left unscored."""
    row = {"_id": f"{run_id}:{tech_id}:{fabric}", "scoring_run_id": run_id, "tech_id": tech_id,
           "technology": tech_id, "fabric_id": fabric, "fabric": fabric.title(),
           "created_at": at(day), "doc_count": len(pages or []), "evidence_runs": ["c"],
           "placement": {"priority": priority, "horizon": "H1" if priority else None}, "tora": {}}
    if scores is not None:
        row["measures"] = {f"m{i}": {"code": f"M{i}", "score": s, "unscorable": s is None}
                           for i, s in enumerate(scores, 1)}
    if pages is not None:
        row["dossier_pages"] = pages
    if dossier_from:
        row["dossier_from"] = dossier_from
    db["assessments"].insert_one(row)
    return row["_id"]


def pov(db, run_id: str, day: int, tech_id: str = "edge-ai", fabrics=("cloud",)) -> None:
    db["povs"].insert_one({"_id": f"{run_id}:{tech_id}", "scoring_run_id": run_id, "tech_id": tech_id,
                           "technology": tech_id, "sections": {"headline": "h"}, "version": 1,
                           "assessment_ids": [f"{run_id}:{tech_id}:{f}" for f in fabrics],
                           "composed_at": at(day)})


def as_if_relinked_in_full(db) -> None:
    """The links and counts are what re-linking every page would give: a job
    that re-links only the names it changed (resolver.restamp) missed nothing."""
    from agent.resolver import resolver

    def now():
        return (sorted((d["_id"], d.get("technologies_resolved")) for d in db["documents"].find()),
                sorted((t["_id"], *(t.get(k) or 0 for k in ("doc_count", "page_count", "source_count")))
                       for t in db["technologies"].find()))
    before = now()
    resolver._stamp_documents(resolver._alias_map())
    resolver.recompute_stats()
    assert now() == before
