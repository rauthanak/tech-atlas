"""The Points of View list reads rows kept ready with each technology's
answers (services/tech_status): the same rows, filters, order and counts as
working every one out on each load, as the list did before 24 Oct (kept below
as the reference)."""

from typing import Literal

from agent.analyzer import pov as pov_composer
from app.api.scoring_runs import _applied, _override, all_povs
from app.services import editions, evidence, latest_povs
from app.services.db.mongo import get_collection
from app.services.display import display_name
from factories import assessment, page, run, tech
from factories import pov as written
from stacked_fakes import load_seeded


def reference(q: str = "", fabric: str | None = None, priority: str | None = None, newer: bool = False,
             unsent: bool = False, sort: Literal["newest", "priority"] = "newest", skip: int = 0,
             limit: int | None = None) -> dict:
    """Every written Point of View of a switched-on technology, with the
    pages new since it was written and its placements; how many switched-off
    technologies' ones are left out; the technologies waiting for one; how
    many a rewrite covers; and the latest compose-all job — one poll drives
    the whole Points of View list. What waits is read from the answers kept
    ready for each technology (services/tech_status)."""
    from app.services import tech_status
    tech_status.fresh()
    uncomposed = tech_status.waiting_lists()["pov_targets"]
    existing = set(get_collection("technologies").distinct("_id", {"enabled": {"$ne": False}}))
    povs = sorted((p for i, p in latest_povs.latest(None, ("sections.headline", "scoring_run_id", "technology", "version",
                                                            "composed_tz", "assessment_ids")).items() if i in existing),
                  key=lambda p: p["composed_at"], reverse=True)  # newest first
    # pages new since each was written: kept ready with each technology's answers (services/tech_status)
    since = {r["_id"]: r["f"].get("new_since_pov") for r in get_collection("tech_status").find(
        {"_id": {"$in": [p["tech_id"] for p in povs]}}, {"f.new_since_pov": 1})}
    rows = {a["_id"]: a for a in get_collection("assessments").find(
        {"_id": {"$in": [i for p in povs for i in p.get("assessment_ids") or []]}}, {"watch_metrics": 0})}
    applied = _applied(list(rows.values()))
    for p in povs:
        mine = sorted((rows[i] for i in p.get("assessment_ids") or [] if i in rows),
                      key=lambda a: a["fabric_id"])
        read = evidence.reading(mine)
        p["new_since_written"] = since.get(p["tech_id"]) if read else None
        p["assessed_at"] = read["assessed_at"] if read else None  # the assessment it was written from
        p["placements"] = [{"fabric_id": e["fabric_id"], "fabric": e.get("fabric"), "priority": e["effective"]["priority"],
                            "computed_priority": e["effective"]["computed_priority"], "override": _override(e),
                            "horizon": e["effective"]["horizon"]} for e in (applied[a["_id"]] for a in mine)]
        p.pop("assessment_ids", None)
    off = get_collection("technologies").distinct("_id", {"enabled": False})
    common = {"switched_off": len(get_collection("povs").distinct("tech_id", {"tech_id": {"$in": off}})),
              "assessed": tech_status.rewrite_count(), "job": pov_composer.batch_status()}
    if limit is None:  # every one, as before (no filter, newest first)
        seen = editions.views([p["tech_id"] for p in povs])
        for p in povs:
            p["views"] = seen.get(p["tech_id"])
        return {"povs": povs, "uncomposed": uncomposed, **common}
    # a page of the list, filtered and sorted here, with the counts the page's lines and filters show
    shown_edition = editions.latest(full=False)
    published = shown_edition["published_at"] if shown_edition else None
    labels = {t["_id"]: (display_name(t)).lower() for t in get_collection("technologies").find(
        {"_id": {"$in": [p["tech_id"] for p in povs]}}, {"label": 1, "name": 1})}
    needle = q.strip().lower()

    def placed_as(p: dict) -> list[dict]:
        return [pl for pl in p["placements"] if not fabric or pl["fabric_id"] == fabric]

    def keep(p: dict) -> bool:
        if needle and needle not in f"{labels.get(p['tech_id'], '')} {((p.get('sections') or {}).get('headline') or '').lower()}":
            return False
        if fabric and not placed_as(p):
            return False
        if priority and not any((pl["priority"] is None) if priority == "none" else pl["priority"] == priority
                                for pl in placed_as(p)):
            return False
        if newer and not (p["new_since_written"] or 0) > 0:
            return False
        return not (only_unsent and p["composed_at"] <= published)

    unsent_n = sum(1 for p in povs if published and p["composed_at"] > published)
    only_unsent = unsent and unsent_n > 0  # none left: the filter lets go
    matching = [p for p in povs if keep(p)]
    if sort == "priority":  # its best priority across its fabrics, then its name
        matching.sort(key=lambda p: (min((pl["priority"] or "P9") for pl in p["placements"]) if p["placements"] else "P9",
                                     labels.get(p["tech_id"], "")))
    page = matching[skip:skip + limit]
    seen = editions.views([p["tech_id"] for p in page])
    for p in page:
        p["views"] = seen.get(p["tech_id"])
    fabrics = sorted({(pl["fabric_id"], pl.get("fabric") or pl["fabric_id"]) for p in povs for pl in p["placements"]},
                     key=lambda f: f[1])
    return {"povs": page, "total": len(matching), "count": len(povs),
            "behind": sum(1 for p in povs if (p["new_since_written"] or 0) > 0), "unsent": unsent_n,
            "fabrics": [{"id": i, "name": n} for i, n in fabrics], "uncomposed_count": len(uncomposed), **common}


def _world(db):
    load_seeded(db, "fabrics", "scoring_config", "measures", "availability", "domains", "subdomains", "trl_levels",
                "path_steps")
    for i, (t, prio) in enumerate((("edge-ai", "P1"), ("quic", "P3"), ("li-fi", None), ("old", "P2"))):
        tech(db, t, t.replace("-", " "), enabled=t != "old")
        run(db, f"r{i}", 2 + i, techs=(t,), fabrics=("cloud", "network"))
        for fabric in ("cloud", "network"):
            assessment(db, f"r{i}", 2 + i, pages=[page(db, f"{t}-{fabric}", 1, tech=t.replace("-", " "))], tech_id=t,
                       fabric=fabric, priority=prio if fabric == "cloud" else "P4")
        written(db, f"r{i}", 3 + i, tech_id=t, fabrics=("cloud", "network"))
    run(db, "r9", 9, techs=("quic",), fabrics=("cloud",))           # quic assessed again: its PoV is from an older one
    assessment(db, "r9", 9, pages=[page(db, "quic-new", 8, tech="quic")], tech_id="quic", priority="P2")
    page(db, "edge-later", 10, tech="edge ai")                       # new since edge-ai's PoV
    db["povs"].update_one({"tech_id": "li-fi"}, {"$set": {"sections.headline": "Light carries data"}})


def test_the_list_is_what_working_every_one_out_gave(db):
    _world(db)
    asks = [{}, {"sort": "priority"}, {"q": "light"}, {"q": "edge"}, {"fabric": "cloud"}, {"fabric": "network", "priority": "P4"},
            {"priority": "P3"}, {"priority": "none"}, {"newer": True}, {"unsent": True}, {"skip": 1, "limit": 2}]
    for ask in asks:
        args = {"limit": 48, **ask}
        new, ref = all_povs(**args), reference(**args)
        assert [(p["tech_id"], p["placements"], p["new_since_written"], p["assessed_at"]) for p in new["povs"]] == \
            [(p["tech_id"], p["placements"], p["new_since_written"], p["assessed_at"]) for p in ref["povs"]], ask
        for key in ("total", "count", "behind", "unsent", "uncomposed_count", "switched_off", "assessed"):
            assert new[key] == ref[key], (ask, key)
        assert [f["id"] for f in new["fabrics"]] == [f["id"] for f in ref["fabrics"]], ask
    every_new, every_ref = all_povs(limit=None), reference()
    assert [p["tech_id"] for p in every_new["povs"]] == [p["tech_id"] for p in every_ref["povs"]]
