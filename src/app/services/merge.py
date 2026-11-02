"""Merging whole technologies into one: a person's Merge (api/technologies)."""

from app.services import decisions, jobs, tech_status
from app.services.db.mongo import get_collection
from app.services.timezone import now_utc


def merge(tech_id: str, absorbed: list[dict]) -> dict:
    """Merge the `absorbed` technologies (their records) into `tech_id`. The
    target's name survives; every alias of the absorbed moves over, and so
    do the choices people made on them (where the target has its own choice
    on the same thing, the target's is kept and the merge says so) and
    catalog membership; the absorbed are deleted, and their pages restamp
    in the background. History stays where it was: assessments, Points of View and
    editions keep the absorbed ids. Names to look for are kept from all.
    Returns what moved (`_carry_over`)."""
    from agent.resolver import restamp
    techs = get_collection("technologies")
    target = techs.find_one({"_id": tech_id})
    merged = _carry_over(tech_id, absorbed)  # before the delete, so running it again after a stop is safe
    aliases = sorted({a for o in absorbed for a in o.get("aliases", [])}
                     | {o["name"] for o in absorbed})
    look_for: list[str] = []  # the target's first, each name once whatever its capitals
    for n in (n for t in (target, *absorbed) for n in t.get("look_for") or []):
        if n.lower() not in {x.lower() for x in look_for}:
            look_for.append(n)
    techs.update_one({"_id": tech_id},
                     {"$addToSet": {"aliases": {"$each": aliases}},
                      "$set": {"updated_at": now_utc(), **({"look_for": look_for} if look_for else {})}})
    techs.delete_many({"_id": {"$in": [o["_id"] for o in absorbed]}})
    names = techs.find_one({"_id": tech_id}, {"aliases": 1})["aliases"]  # the pages that name it or what it took in
    jobs.later(restamp, names)
    tech_status.touch([tech_id, *(o["_id"] for o in absorbed)], now=True)  # the absorbed lose their rows
    return merged


def _same_thing(d: dict) -> tuple:
    return d["kind"], d.get("fabric_id"), d.get("measure_id"), d.get("field"), d.get("key")


def _carry_over(tech_id: str, absorbed: list[dict]) -> dict:
    """The absorbed technologies' choices in force move to the target, one
    technology after another, unless the target already has one on the same
    thing: then the target's is kept and the other is replaced. Catalog
    membership moves when the target has none. What moved, in plain words."""
    from app.api.decisions import described
    coll, techs = get_collection("decisions"), get_collection("technologies")
    moved, conflicts, carried = 0, [], False
    for o in absorbed:
        theirs = {_same_thing(d): d for d in decisions.active([tech_id])}
        mine = decisions.active([o["_id"]])
        clash = [d for d in mine if _same_thing(d) in theirs]
        if clash:
            coll.update_many({"_id": {"$in": [d["_id"] for d in clash]}},
                             {"$set": {"active": False, "replaced_at": now_utc()}})
        coll.update_many({"_id": {"$in": [d["_id"] for d in mine]}}, {"$set": {"tech_id": tech_id, "merged_from": o["_id"]}})
        moved += len(mine) - len(clash)
        for d in clash:
            if d.get("value") == theirs[_same_thing(d)].get("value"):
                continue  # both made the same choice: nothing was lost, so nothing to report
            kept, dropped = described([theirs[_same_thing(d)], d])
            conflicts.append({"kept": kept["what"], "dropped": dropped["what"], "from": o.get("label") or o["name"]})
        target = techs.find_one({"_id": tech_id}, {"imported": 1, "origin": 1}) or {}
        catalog = {f: o[f] for f in ("imported", "origin") if o.get(f) and not target.get(f)}
        if catalog:
            techs.update_one({"_id": tech_id}, {"$set": catalog})
            carried = True
    assessed = set(get_collection("assessments").distinct("tech_id", {"tech_id": {"$in": [o["_id"] for o in absorbed]}}))
    with_pov = set(get_collection("povs").distinct("tech_id", {"tech_id": {"$in": [o["_id"] for o in absorbed]}}))
    pages = get_collection("documents").count_documents({"technologies_resolved": {"$in": [o["name"] for o in absorbed]}})
    return {"absorbed": [{"id": o["_id"], "name": o.get("label") or o["name"], "assessed": o["_id"] in assessed, "pov": o["_id"] in with_pov}
                         for o in absorbed],
            "choices_moved": moved, "catalog_carried": carried, "conflicts": conflicts,
            "assess_again": bool(assessed or pages)}  # their pages are the kept one's now, and no assessment has read them
