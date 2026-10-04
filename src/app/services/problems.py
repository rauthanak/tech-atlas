"""Problems: what went wrong in the latest work and needs a person. Worked
out on each request; nothing is stored. Returns data, and the portal words
it and offers the fix. A data source with results still to collect isn't a
problem: the next collection carries on where this one stopped. Nor is a
website that reached its page limit: that's coverage, reported apart."""

from agent.analyzer import pov as pov_composer
from agent.scout.tools.adapters import REGISTRY
from agent.supervisor.tools.sources import collectable_query
from app.services.db.mongo import get_collection

USER_STOP = "terminated by user"  # a person stopped it: not a problem


def source_access() -> dict[str, str]:
    return {s["_id"]: s.get("access") for s in get_collection("sources").find({}, {"access": 1})}


def didnt_finish(row: dict, access: dict[str, str]) -> bool:
    """A website that ran out of page budget. A data source with results still
    to collect is on track: the next collection carries on where it stopped."""
    return bool(row.get("incomplete")) and access.get(row["source_id"]) != "query"


def _not_configured() -> list[dict]:
    """Data sources a run would collect whose adapter is missing keys."""
    missing = {name: a.missing_keys() for name, a in REGISTRY.items()}
    return [{"kind": "not_configured", "source_id": s["source_id"], "source_name": s["name"],
             "keys": missing[s["adapter"]]}
            for s in get_collection("sources").find({**collectable_query(), "access": "query"})
            .sort("name", 1) if missing.get(s.get("adapter"))]


def _failed_pages(run: dict | None) -> dict | None:
    """Pages from the latest collection or check again that couldn't be
    analysed, wholly or in part, grouped by reason."""
    scope = [{"run_id": run["_id"]}] if run else []
    job = get_collection("recheck_jobs").find_one(sort=[("started_at", -1)], projection={"started_at": 1})
    if job:
        scope.append({"analysis_error.at": {"$gte": job["started_at"]}})
    if not scope:
        return None
    pages = list(get_collection("documents").find(
        {"is_stub": False, "analysis_error": {"$ne": None}, "$or": scope},
        {"title": 1, "end_url": 1, "source_id": 1, "analysis_error": 1}).sort("analysis_error.at", -1))
    if not pages:
        return None
    reasons: dict[str, dict] = {}
    for p in pages:
        error = p["analysis_error"]
        reasons.setdefault(error["reason"], {"reason": error["reason"], "detail": error.get("detail"),
                                             "pages": 0})["pages"] += 1
    return {"kind": "failed_pages", "count": len(pages),
            "reasons": sorted(reasons.values(), key=lambda r: (-r["pages"], r["reason"])),
            "pages": [{"doc_id": p["_id"], "title": p.get("title"), "url": p.get("end_url"),
                       "source_id": p.get("source_id"), "reason": p["analysis_error"]["reason"],
                       "detail": p["analysis_error"].get("detail")} for p in pages[:50]]}


def _failed_jobs(run: dict | None) -> list[dict]:
    """The latest collection, check, assessment run and Point of View job,
    each if it failed, stopped with an error or was interrupted."""
    def stopped(doc: dict) -> bool:
        return doc["status"] == "failed" or (doc["status"] == "terminated" and doc.get("error") != USER_STOP)

    def interrupted(doc: dict) -> bool:
        return doc["status"] in ("failed", "interrupted")

    latest = [("collection", run, stopped),
              ("check", get_collection("recheck_jobs").find_one(sort=[("started_at", -1)]), interrupted),
              ("assessment", get_collection("scoring_runs").find_one(
                  sort=[("started_at", -1)], projection={"status": 1, "error": 1}), stopped),
              ("pov", pov_composer.batch_status(), interrupted)]
    return [{"kind": "job_failed", "job": job, "id": doc["_id"], "status": doc["status"],
             "error": doc.get("error")} for job, doc, failed in latest if doc and failed(doc)]


def _latest_run() -> dict | None:
    return get_collection("runs").find_one(sort=[("run_start_date_time", -1)],
                                           projection={"sources": 1, "status": 1, "error": 1})


def coverage() -> list[dict]:
    """Websites in the latest collection that reached their page limit. The
    collection kept everything it read; the limit is in Crawl settings."""
    run = _latest_run()
    access = source_access()
    return [{"kind": "didnt_finish", "source_id": row["source_id"], "source_name": row.get("source_name"),
             "run_id": run["_id"], "note": row.get("incomplete_note") or ""}
            for row in (run or {}).get("sources") or [] if didnt_finish(row, access)]


def problems() -> list[dict]:
    run = _latest_run()
    unconfigured = _not_configured()
    skip = {p["source_id"] for p in unconfigured}  # their error says the same
    out: list[dict] = []
    for row in (run or {}).get("sources") or []:
        where = {"source_id": row["source_id"], "source_name": row.get("source_name"), "run_id": run["_id"]}
        note, error = row.get("incomplete_note") or "", row.get("error")
        if "too broad" in note:
            out.append({"kind": "too_broad", **where, "note": note})
        if error and error != "run cancelled" and row["source_id"] not in skip:
            out.append({"kind": "source_error", **where, "error": error})
    failed = _failed_pages(run)
    return out + unconfigured + ([failed] if failed else []) + _failed_jobs(run)
