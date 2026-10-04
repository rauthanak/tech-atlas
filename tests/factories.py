"""Small builders for the stored shapes the evidence tests need: pages,
technologies, scoring runs, assessments and Points of View."""


def at(day: int) -> str:
    return f"2026-09-{day:02d}T00:00:00+00:00"


def tech(db, tech_id: str = "edge-ai", name: str = "edge ai", enabled: bool = True) -> None:
    db["technologies"].insert_one({"_id": tech_id, "name": name, "enabled": enabled,
                                   "aliases": [name], "page_count": 0, "source_count": 0})


def page(db, url: str, day: int, tech: str | None = "edge ai", stub_of: str | None = None,
         **extra) -> str:
    """A visit to `url`; `stub_of` makes it an unchanged revisit of that version."""
    doc_id = f"{url}@{day}"
    db["documents"].insert_one({"_id": doc_id, "end_url": url, "title": url, "scraped_at": at(day),
                                "is_stub": stub_of is not None, "ref_doc_id": stub_of,
                                "technologies_resolved": [tech] if tech else [],
                                "source_id": "s", "run_id": "c", **extra})
    return doc_id


def run(db, run_id: str, day: int, status: str = "completed", techs=("edge-ai",),
        gates: dict | None = None, params: dict | None = None, fabrics=("cloud",)) -> None:
    db["scoring_runs"].insert_one({
        "_id": run_id, "status": status, "started_at": at(day), "params": params or {},
        "snapshot": {"fabrics": [{"_id": f, "name": f.title()} for f in fabrics]},
        "technologies": [{"tech_id": t, "name": t} for t in techs], "skipped": [],
        "gates": gates if gates is not None else {t: ["cloud"] for t in techs},
        "progress": {"techs_done": 0, "techs_total": len(techs)}})


def assessment(db, run_id: str, day: int, pages: list[str] | None = None, tech_id: str = "edge-ai",
               fabric: str = "cloud", dossier_from: str | None = None) -> str:
    """`pages=None` makes an assessment from before page versions were recorded."""
    row = {"_id": f"{run_id}:{tech_id}:{fabric}", "scoring_run_id": run_id, "tech_id": tech_id,
           "technology": tech_id, "fabric_id": fabric, "fabric": fabric.title(),
           "created_at": at(day), "doc_count": len(pages or []), "evidence_runs": ["c"],
           "placement": {"priority": "P2", "horizon": "H1"}, "tora": {}}
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
