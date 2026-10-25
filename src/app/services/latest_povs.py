"""Each technology's newest Point of View: what the Technologies list, a
technology's page, the Points of View list and publishing all read; and its
row in the Points of View list (list_rows), kept ready with the technology's
answers (services/tech_status)."""

from app.services.db.mongo import get_collection


def latest(tech_ids: list[str] | None, fields: tuple[str, ...]) -> dict[str, dict]:
    """By technology id, its newest Point of View with these fields (dotted
    paths kept as nested), plus `_id` and `tech_id`; every technology's
    when `tech_ids` is None."""
    rows = get_collection("povs").aggregate([
        *([{"$match": {"tech_id": {"$in": tech_ids}}}] if tech_ids is not None else []),
        {"$sort": {"tech_id": 1, "composed_at": -1}},
        {"$project": {"tech_id": 1, "composed_at": 1, **dict.fromkeys(fields, 1)}},
        {"$group": {"_id": "$tech_id", "pov": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$pov"}}], allowDiskUse=True)
    return {p["tech_id"]: p for p in rows}


def list_rows(tech_ids: list[str], new_since: dict[str, int | None]) -> dict[str, dict]:
    """Each of these technologies' newest Point of View as the Points of View
    list shows it: its headline and run, the assessment it was written from,
    the pages new since (`new_since`, worked out with the technology's state)
    and each fabric's placement as people left it."""
    from app.services import effective, evidence
    povs = latest(tech_ids, ("sections.headline", "scoring_run_id", "technology", "version", "composed_tz",
                             "assessment_ids"))
    rows = {a["_id"]: a for a in get_collection("assessments").find(
        {"_id": {"$in": [i for p in povs.values() for i in p.get("assessment_ids") or []]}}, {"watch_metrics": 0})}
    applied = effective.applied_rows(list(rows.values()))
    for tech_id, p in povs.items():
        mine = sorted((rows[i] for i in p.pop("assessment_ids", None) or [] if i in rows), key=lambda a: a["fabric_id"])
        read = evidence.reading(mine)
        p["new_since_written"] = new_since.get(tech_id) if read else None
        p["assessed_at"] = read["assessed_at"] if read else None  # the assessment it was written from
        p["placements"] = [{"fabric_id": e["fabric_id"], "fabric": e.get("fabric"), "priority": e["effective"]["priority"],
                            "computed_priority": e["effective"]["computed_priority"],
                            "override": effective.override_view(e), "horizon": e["effective"]["horizon"]}
                           for e in (applied[a["_id"]] for a in mine)]
    return povs
