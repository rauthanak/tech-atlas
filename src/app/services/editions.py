"""Editions: what leaders see on Frontier (B17). Publishing freezes every
placement and Point of View as they stand, with the assumptions in force and
the evidence behind them, dated in the publisher's zone. Frontier shows the
latest edition, never live data. Publishing changes nothing else: admins
keep re-running, tuning and rewriting, and leaders see the edition until the
next publish.

  editions       one per publish: its name (optional), when and in which
                 zone, the edition before it, the placements and what isn't
                 placed (every fabric, as live() gives them; a placement whose
                 priority moved since the edition before says from what, and
                 why), the grid's cut-points, the near band, the assumptions
                 in force and the evidence counts
  edition_povs   one per edition and technology: its Point of View as the
                 page showed it then, with what a leader recorded per fabric

live() is what a publish freezes: the effective placements (people's
overrides applied), how soon and how big, the Disruption threat (Frontier's
Defence lens), the stage, the path step, what a leader recorded and its
state, and the latest Point of View. Switched-off technologies are left out."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services import busy, classify_effective, decisions, evidence, finance, gates
from app.services.db.mongo import get_collection
from app.services.settings_store import radar_settings
from app.services.timezone import now_utc

THREAT = "disruption-threat"  # the only defence-oriented measure: the Defence lens's height
SUMMARY = {"placed": 0, "held": 0}  # an edition without its placements


class Refused(ValueError):
    """A publish that can't happen now; the message says why, in plain words."""


def _threat(a: dict) -> tuple[float | None, str | None]:
    """The Disruption threat score, or why there's none."""
    m = (a.get("measures") or {}).get(THREAT) or {}
    if m.get("score") is not None:
        return m["score"], None
    if m.get("state") == "gap_accepted":
        return None, "Disruption threat left out: a person accepted the gap"
    return None, "Disruption threat not entered by Tata yet"


def live() -> dict:
    """Every placement and what isn't placed yet, now, in every fabric."""
    states = evidence.states()
    applied = gates.latest_applied(all_states=states)
    techs = {t["_id"]: t for t in get_collection("technologies").find(
        {"_id": {"$in": list(applied)}},
        {"name": 1, "label": 1, "enabled": 1, "classification": 1, "assessed_classification": 1})}
    povs = {p["tech_id"]: p for p in get_collection("povs").find(
        {"tech_id": {"$in": list(applied)}}, {"tech_id": 1, "scoring_run_id": 1, "composed_at": 1, "composed_tz": 1,
                                              "sections.headline": 1}).sort("composed_at", 1)}
    path = finance.steps()
    decs = decisions.active(list(applied), ["path_step", "move", "nascent", "commitment", "bottlenecks"])
    lists = classify_effective.names()
    stages = {tid: classify_effective.effective(t, decs, lists)["availability"] for tid, t in techs.items()}
    fabrics = {f["_id"]: f.get("name") for f in get_collection("fabrics").find()}
    placed, held = [], []
    for tech_id, rows in applied.items():
        t = techs.get(tech_id) or {}
        if t.get("enabled") is False:
            continue  # switched off: never shown to leaders
        for a in rows:
            p, e = a["placement"], a["effective"]
            step_d = decisions.pick(decs, "path_step", tech_id=tech_id, fabric_id=a["fabric_id"])
            pv = povs.get(tech_id)
            st = stages.get(tech_id) or {}
            threat, threat_missing = _threat(a)
            leader = decisions.leader_state(decs, tech_id, a["fabric_id"])
            leader.pop("decision")
            item = {"tech_id": tech_id, "name": t.get("label") or t.get("name") or tech_id, "fabric_id": a["fabric_id"],
                    "stage": {"id": st.get("id"), "name": st.get("name"), "emerging": bool(st.get("emerging")),
                              "known": not (lists["availability"].get(st.get("id")) or {}).get("catch_all", True)},
                    "fabric": fabrics.get(a["fabric_id"], a["fabric"]), "priority": e["priority"],
                    "computed_priority": e["computed_priority"], "override": bool(e["override"]),
                    "override_reason": (e["override"] or {}).get("reason"), "horizon": e["horizon"],
                    "how_soon": (p.get("timeline") or {}).get("score"), "how_big": (p.get("potential") or {}).get("score"),
                    "soon_scored": [(p.get("timeline") or {}).get("scored"), (p.get("timeline") or {}).get("of")],
                    "big_scored": [(p.get("potential") or {}).get("scored"), (p.get("potential") or {}).get("of")],
                    "threat": threat, "threat_missing": threat_missing, "leader": leader,
                    "path_step": path.get(step_d["value"], {}).get("name") if step_d else None,
                    "pov": {"scoring_run_id": pv["scoring_run_id"], "composed_at": pv["composed_at"],
                            "composed_tz": pv.get("composed_tz"), "headline": (pv.get("sections") or {}).get("headline")}
                    if pv else None}
            if e["priority"] and item["how_soon"] is not None and item["how_big"] is not None:
                placed.append(item)
            else:
                missing = [w for w, k in (("how soon", "how_soon"), ("how big", "how_big")) if item[k] is None]
                held.append({**item, "reason": f"{' and '.join(missing).capitalize()} couldn't be scored from the evidence"
                             if missing else "No priority yet"})
    placed.sort(key=lambda r: (r["priority"], -(r["how_big"] or 0)))
    held.sort(key=lambda r: r["name"])
    grid = get_collection("scoring_config").find_one({"_id": "priority_grid"}, {"timeline_cutpoints": 1, "potential_cutpoints": 1}) or {}
    return {"placed": placed, "held": held, "fabrics": [{"id": k, "name": v} for k, v in fabrics.items()],
            "stages": [{"id": a["_id"], "name": a["name"], "emerging": bool(a.get("emerging")), "known": not a.get("catch_all")}
                       for a in sorted(lists["availability"].values(), key=lambda a: a.get("order", 99))],
            "cutpoints": {"how_soon": grid.get("timeline_cutpoints", [4, 7]), "how_big": grid.get("potential_cutpoints", [4, 7])}}


def assumptions() -> list[dict]:
    """The assumptions in force (Setup › Assumptions), in their order."""
    rows = get_collection("assumptions").find({}, {"name": 1, "date": 1, "order": 1})
    return [{"statement": r["name"], "date": r.get("date")}
            for r in sorted(rows, key=lambda r: (r.get("order", 50), r.get("date") or "", r["name"]))]


def evidence_counts() -> dict:
    """How much reading stands behind the screen (B23), for every collection
    so far: sources on, pages read, findings by signal type, technologies."""
    from app.api.signals import tally  # the Briefing's own count, so the numbers agree
    found = tally({})
    return {"sources_on": get_collection("sources").count_documents({"enabled": True}),
            "pages_read": get_collection("documents").count_documents({"is_stub": False}),
            "signals_found": found["findings"],
            "technologies": get_collection("technologies").count_documents({"enabled": {"$ne": False}}),
            "by_signal_type": [{"signal_id": t["signal_id"], "name": t["name"], "count": t["count"]} for t in found["types"]]}


def label(e: dict) -> str:
    """An edition's name, else the day it was published, in the publisher's zone: "21 Oct 2026"."""
    if e.get("name"):
        return e["name"]
    at = datetime.fromisoformat(e["published_at"]).astimezone(ZoneInfo(e.get("tz") or "UTC"))
    return f"{at.day} {at:%b %Y}"


def summary(e: dict) -> dict:
    """An edition without its placements: what the lists and headers show."""
    return {k: e.get(k) for k in ("_id", "name", "published_at", "tz", "previous", "counts")} | {"label": label(e)}


def latest(full: bool = True) -> dict | None:
    return get_collection("editions").find_one(sort=[("published_at", -1)], projection=None if full else SUMMARY)


def listed(limit: int = 20) -> list[dict]:
    return [summary(e) for e in get_collection("editions").find({}, SUMMARY).sort("published_at", -1).limit(limit)]


def _mark_moves(placed: list[dict], before: dict | None) -> int:
    """Each placement whose priority differs from the edition before's gets
    `moved`: from what, and why (a person's override reason, the override
    undone, or new scores). Returns how many moved."""
    if not before:
        return 0
    was = {(p["tech_id"], p["fabric_id"]): p for p in before["placed"]}
    n = 0
    for p in placed:
        b = was.get((p["tech_id"], p["fabric_id"]))
        if b and b["priority"] != p["priority"]:
            p["moved"] = ({"from": b["priority"], "by_person": True,
                           "reason": p["override_reason"] or "set by a person; no reason recorded"} if p["override"]
                          else {"from": b["priority"], "by_person": False,
                                "reason": "a person's override was undone" if b.get("override") else "new scores"})
            n += 1
    return n


def publish(name: str | None, tz: str) -> dict:
    """Freeze what leaders see now; raises Refused when it can't, saying why."""
    from fastapi import HTTPException

    from agent.analyzer import pov as pov_composer
    from app.api.scoring_runs import get_pov  # the Point of View exactly as its page shows it
    from app.api.technologies import technology_assessment  # where the value lands, as its fold shows it

    if why := busy.reason("scoring"):
        raise Refused(f"{why} Publish when it finishes, so leaders don't see it halfway.")
    job = pov_composer.batch_status()
    if job and job.get("status") == "running":
        raise Refused(f"Points of View are being written now ({job.get('done', 0)} of {job.get('total', 0)}). "
                      "Publish when that finishes, so leaders don't see some old and some new.")
    now = live()
    if not now["placed"] and not now["held"]:
        raise Refused("Nothing to publish yet: no technology is assessed.")
    before = latest()
    moved = _mark_moves(now["placed"], before)
    edition_id = uuid.uuid4().hex[:12]
    leaders: dict[str, dict] = {}
    for r in now["placed"] + now["held"]:
        leaders.setdefault(r["tech_id"], {})[r["fabric_id"]] = r["leader"]
    runs = {r["tech_id"]: r["pov"]["scoring_run_id"] for r in now["placed"] + now["held"] if r["pov"]}
    frozen = []
    for tech_id, run_id in runs.items():
        try:
            pv = get_pov(run_id, tech_id)
        except HTTPException:  # removed since live() read it: the edition says it has none
            continue
        for f in pv.get("fabrics") or []:
            f["leader"] = leaders[tech_id].get(f["fabric_id"])
        # the value fold, frozen too, so leaders see the edition's levers, path and finance, not today's
        pv["value"] = [technology_assessment(tech_id, fid) for fid in (pv.get("latest_assessment") or {}).get("fabric_ids", [])]
        frozen.append({"_id": f"{edition_id}:{tech_id}", "edition_id": edition_id, "tech_id": tech_id, "pov": pv})
    if frozen:  # the Points of View first: Frontier never finds an edition without them
        get_collection("edition_povs").insert_many(frozen)
    doc = {"_id": edition_id, "name": (name or "").strip() or None, "published_at": now_utc(), "tz": tz,
           "previous": {k: before.get(k) for k in ("_id", "name", "published_at", "tz")} | {"label": label(before)}
           if before else None,
           **now, "near_band": float(radar_settings().get("frontier_near_band", 0.5)),
           "assumptions": assumptions(), "evidence": evidence_counts(),
           "counts": {"placements": len(now["placed"]), "held": len(now["held"]), "povs": len(frozen), "moved": moved,
                      "technologies": len({r["tech_id"] for r in now["placed"] + now["held"]})}}
    get_collection("editions").insert_one(doc)
    return summary(doc)


def frozen_pov(tech_id: str) -> tuple[dict | None, dict | None]:
    """(the latest edition's summary, its Point of View of this technology)."""
    e = latest(full=False)
    if e is None:
        return None, None
    doc = get_collection("edition_povs").find_one({"_id": f"{e['_id']}:{tech_id}"})
    return summary(e), doc["pov"] if doc else None
