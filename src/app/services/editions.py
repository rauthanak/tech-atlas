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

from app.services import busy, classify_effective, decisions, finance, gates, latest_povs, tech_status
from app.services.db.mongo import get_collection
from app.services.settings_store import radar_settings
from app.services.timezone import now_utc
from app.services.display import display_name

THREAT = "disruption-threat"  # the only defence-oriented measure: the Defence lens's height
SUMMARY = {"placed": 0, "held": 0}  # an edition without its placements
ROWS = "edition_rows"  # each placement of an edition its own record (from 24 Oct), so no edition outgrows a record
SEPARATE = "separate"  # an edition's `rows`: its placements are in ROWS, not inside it


def rows(e: dict, kind: str, fabric: str | None = None, tech_id: str | None = None) -> list[dict]:
    """An edition's placed or held rows, in its order, of one fabric or
    technology when given. Editions published before 24 Oct hold theirs inside."""
    if e.get("rows") == SEPARATE:
        q = {"edition_id": e["_id"], "kind": kind, **({"fabric_id": fabric} if fabric else {}),
             **({"tech_id": tech_id} if tech_id else {})}
        return list(get_collection(ROWS).find(q, {"_id": 0, "edition_id": 0, "kind": 0, "n": 0}).sort("n", 1))
    inline = e[kind] if kind in e else (get_collection("editions").find_one({"_id": e["_id"]}, {kind: 1}) or {}).get(kind) or []
    return [r for r in inline if (not fabric or r["fabric_id"] == fabric) and (not tech_id or r["tech_id"] == tech_id)]


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
    applied = gates.applied(tech_status.latest_assessments())  # from the answers kept ready: no page is read
    techs = {t["_id"]: t for t in get_collection("technologies").find(
        {"_id": {"$in": list(applied)}},
        {"name": 1, "label": 1, "enabled": 1, "classification": 1, "assessed_classification": 1})}
    povs = latest_povs.latest(list(applied), ("scoring_run_id", "composed_tz", "sections.headline"))
    path = finance.steps()
    decs = decisions.active(list(applied), ["path_step", "move", "nascent", "commitment", "bottlenecks"])
    lists = classify_effective.names()
    grouped = decisions.by_tech(decs)
    effective = {tid: classify_effective.effective(t, grouped.get(tid, []), lists) for tid, t in techs.items()}
    stages = {tid: eff["availability"] for tid, eff in effective.items()}
    fabrics = {f["_id"]: f.get("name") for f in get_collection("fabrics").find()}
    placed, held = [], []
    for tech_id, rows in applied.items():
        t = techs.get(tech_id) or {}
        if t.get("enabled") is False:
            continue  # switched off: never shown to leaders
        for a in rows:
            p, e = a["placement"], a["effective"]
            mine = grouped.get(tech_id, [])
            step_d = decisions.pick(mine, "path_step", tech_id=tech_id, fabric_id=a["fabric_id"])
            pv = povs.get(tech_id)
            st = stages.get(tech_id) or {}
            threat, threat_missing = _threat(a)
            leader = decisions.leader_state(mine, tech_id, a["fabric_id"])
            leader.pop("decision")
            item = {"tech_id": tech_id, "name": display_name(t, tech_id), "fabric_id": a["fabric_id"],
                    "stage": {"id": st.get("id"), "name": st.get("name"), "emerging": bool(st.get("emerging")),
                              "known": not (lists["availability"].get(st.get("id")) or {}).get("catch_all", True)},
                    "fabric": fabrics.get(a["fabric_id"], a["fabric"]), "priority": e["priority"],
                    "computed_priority": e["computed_priority"], "override": bool(e["override"]),
                    "override_reason": (e["override"] or {}).get("reason"), "horizon": e["horizon"],
                    "how_soon": (p.get("timeline") or {}).get("score"), "how_big": (p.get("potential") or {}).get("score"),
                    "soon_scored": [(p.get("timeline") or {}).get("scored"), (p.get("timeline") or {}).get("of")],
                    "big_scored": [(p.get("potential") or {}).get("scored"), (p.get("potential") or {}).get("of")],
                    "threat": threat, "threat_missing": threat_missing, "leader": leader,
                    # how far to trust it: the evidence word, and the pages its assessment read (for why it moved)
                    "evidence": ((effective.get(tech_id) or {}).get("evidence") or {}).get("verdict"),
                    "pages": a.get("doc_count"),
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
    from app.api.signals import ready_counts  # the Briefing's own count, kept a day at a time, so the numbers agree
    found = ready_counts(None, now_utc())
    return {"sources_on": get_collection("sources").count_documents({"enabled": True}),
            "pages_read": get_collection("documents").count_documents({"is_stub": False}),
            "signals_found": found["findings"],
            "technologies": get_collection("technologies").count_documents({"enabled": {"$ne": False}}),
            "by_signal_type": [{"signal_id": t["signal_id"], "name": t["name"], "count": t["count"]} for t in found["types"]]}


def label(e: dict) -> str:
    """An edition's name, else the day it was published, in the publisher's zone, written the
    way every screen writes a day: "Oct 21, 2026"."""
    if e.get("name"):
        return e["name"]
    at = datetime.fromisoformat(e["published_at"]).astimezone(ZoneInfo(e.get("tz") or "UTC"))
    return f"{at:%b} {at.day}, {at.year}"


def summary(e: dict) -> dict:
    """An edition without its placements: what the lists and headers show."""
    prev = e.get("previous")  # its label as every screen writes a day now, not as stored when this one was published
    return {k: e.get(k) for k in ("_id", "name", "published_at", "tz", "counts")} | {
        "label": label(e), "previous": prev | {"label": label(prev)} if prev else None}


def latest(full: bool = True) -> dict | None:
    return get_collection("editions").find_one(sort=[("published_at", -1)], projection=None if full else SUMMARY)


def listed(limit: int = 20) -> list[dict]:
    return [summary(e) for e in get_collection("editions").find({}, SUMMARY).sort("published_at", -1).limit(limit)]


def _num(x: float) -> str:
    return f"{x:g}"


def move_why(before: dict, now: dict) -> str | None:
    """What moved a priority, from the two editions' own scores: "how big 5 → 7
    after 40 new pages". None when neither score changed (the edges or the
    grid did)."""
    parts = [f"{word} {_num(before[k])} → {_num(now[k])}" for word, k in (("how soon", "how_soon"), ("how big", "how_big"))
             if before.get(k) is not None and now.get(k) is not None and before[k] != now[k]]
    if not parts:
        return None
    new = (now.get("pages") or 0) - (before.get("pages") or 0) if before.get("pages") is not None else 0
    return " and ".join(parts) + (f" after {new:,} new page{'s' if new != 1 else ''}" if new > 0 else "")


def with_why(e: dict, fabric: str | None = None) -> list[dict]:
    """An edition's placements, each move with its `why`; an edition published
    before moves carried one gets it from the edition before, as it stood."""
    placed = rows(e, "placed", fabric)
    if not any(p.get("moved") and "why" not in p["moved"] and not p["moved"]["by_person"] for p in placed):
        return placed
    before = get_collection("editions").find_one({"_id": (e.get("previous") or {}).get("_id")}, SUMMARY)
    was = {(b["tech_id"], b["fabric_id"]): b for b in (rows(before, "placed", fabric) if before else [])}
    out = []
    for p in placed:
        b = was.get((p["tech_id"], p["fabric_id"]))
        if p.get("moved") and not p["moved"]["by_person"] and "why" not in p["moved"] and b:
            p = {**p, "moved": {**p["moved"], "why": move_why(b, p)}}
        out.append(p)
    return out


def _mark_moves(placed: list[dict], before: dict | None) -> int:
    """Each placement whose priority differs from the edition before's gets
    `moved`: from what, and why (a person's override reason, the override
    undone, or new scores). Returns how many moved."""
    if not before:
        return 0
    was = {(p["tech_id"], p["fabric_id"]): p for p in rows(before, "placed")}
    n = 0
    for p in placed:
        b = was.get((p["tech_id"], p["fabric_id"]))
        if b and b["priority"] != p["priority"]:
            p["moved"] = ({"from": b["priority"], "by_person": True,
                           "reason": p["override_reason"] or "set by a person; no reason recorded"} if p["override"]
                          else {"from": b["priority"], "by_person": False,
                                "reason": "a person's override was undone" if b.get("override") else "new scores",
                                "why": move_why(b, p)})
            n += 1
    return n


SINCE_S = 60  # since() works out every placement: polled answers reuse it this long
_since: dict = {}


def forget_since() -> None:
    """An action may have moved a placement: the next since() works it out afresh."""
    _since.pop("at", None)


def since() -> dict | None:
    """What leaders would see differently if the edition were published now:
    priorities moved, placements new or gone, and Points of View written
    since it; and what a publish now would send (`now`). None before the
    first edition. Worked out at most once a minute, and after any action."""
    import time
    if _since.get("at", 0) > time.time() - SINCE_S:
        return _since["value"]
    _since.update(at=time.time(), value=_since_now())
    return _since["value"]


def _since_now() -> dict | None:
    before = latest()
    if not before:
        return None
    now = live()
    was = {(p["tech_id"], p["fabric_id"]): p["priority"] for p in rows(before, "placed")}
    is_ = {(p["tech_id"], p["fabric_id"]): p["priority"] for p in now["placed"]}
    every = now["placed"] + now["held"]
    return {"edition": label(before), "published_at": before["published_at"], "tz": before.get("tz"),
            "moved": sum(1 for k, v in is_.items() if k in was and was[k] != v),
            "placed_new": len(is_.keys() - was.keys()), "placed_gone": len(was.keys() - is_.keys()),
            "povs_written": len({r["tech_id"] for r in every if r["pov"] and r["pov"]["composed_at"] > before["published_at"]}),
            "now": {"placements": len(now["placed"]), "held": len(now["held"]),
                    "povs": len({r["tech_id"] for r in every if r["pov"]})}}


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
           **{k: v for k, v in now.items() if k not in ("placed", "held")}, "rows": SEPARATE,
           "near_band": float(radar_settings().get("frontier_near_band", 0.5)),
           "assumptions": assumptions(), "evidence": evidence_counts(),
           "counts": {"placements": len(now["placed"]), "held": len(now["held"]), "povs": len(frozen), "moved": moved,
                      "technologies": len({r["tech_id"] for r in now["placed"] + now["held"]})}}
    # the placements first, each its own record: Frontier never finds an edition without them
    placements = [{"_id": f"{edition_id}:{r['tech_id']}:{r['fabric_id']}", "edition_id": edition_id, "kind": kind, "n": n, **r}
                  for kind in ("placed", "held") for n, r in enumerate(now[kind])]
    for i in range(0, len(placements), 1000):
        get_collection(ROWS).insert_many(placements[i:i + 1000])
    get_collection("editions").insert_one(doc)
    return summary(doc)


def pov_in_latest(tech_id: str) -> dict:
    """Which version of a technology's Point of View leaders see: the latest
    edition's summary (None before the first) and when the version it holds
    was written, in the writer's zone (None when it holds none)."""
    e = latest(full=False)
    doc = e and get_collection("edition_povs").find_one({"_id": f"{e['_id']}:{tech_id}"},
                                                         {"pov.composed_at": 1, "pov.composed_tz": 1})
    pov = doc["pov"] if doc else {}
    return {"edition": summary(e) if e else None, "composed_at": pov.get("composed_at"), "composed_tz": pov.get("composed_tz"),
            "views": views([tech_id]).get(tech_id)}


VIEW_KINDS = ("opened", "printed")


def record_view(tech_id: str, kind: str) -> None:
    """A leader opened a Point of View on the leaders' address, or printed it
    (Print / Save as PDF). No sign-in yet, so it says how often, not who."""
    e = latest(full=False)
    get_collection("pov_views").insert_one({"_id": uuid.uuid4().hex, "tech_id": tech_id, "kind": kind,
                                            "edition_id": e["_id"] if e else None, "at": now_utc()})


def views(tech_ids: list[str] | None = None) -> dict[str, dict]:
    """Per technology: how many times leaders opened and printed its Point
    of View, and when they last opened it."""
    match = {"tech_id": {"$in": tech_ids}} if tech_ids is not None else {}
    out: dict[str, dict] = {}
    for r in get_collection("pov_views").aggregate([
            {"$match": match},
            {"$group": {"_id": {"t": "$tech_id", "k": "$kind"}, "n": {"$sum": 1}, "last": {"$max": "$at"}}}]):
        v = out.setdefault(r["_id"]["t"], {"opened": 0, "printed": 0, "last_opened": None})
        v[r["_id"]["k"]] = r["n"]
        if r["_id"]["k"] == "opened":
            v["last_opened"] = r["last"]
    return out


def frozen_pov(tech_id: str) -> tuple[dict | None, dict | None]:
    """(the latest edition's summary, its Point of View of this technology).
    Each fabric carries its place as the edition holds it (`placement`: how
    soon, how big and its band), so the page can say why the priority."""
    e = latest(full=False)
    if e is None:
        return None, None
    doc = get_collection("edition_povs").find_one({"_id": f"{e['_id']}:{tech_id}"})
    if not doc:
        return summary(e), None
    pov = doc["pov"]
    big_cuts = (e.get("cutpoints") or {}).get("how_big", [4, 7])
    from agent.analyzer.placement import POTENTIAL_BANDS, _band
    mine = {r["fabric_id"]: r for kind in ("placed", "held") for r in rows(e, kind, tech_id=tech_id)}
    for f in pov.get("fabrics") or []:
        r = mine.get(f["fabric_id"])
        if r:
            f["placement"] = {"how_soon": r.get("how_soon"), "how_big": r.get("how_big"),
                              "big_band": _band(r.get("how_big"), big_cuts, POTENTIAL_BANDS)}
    return summary(e), pov
