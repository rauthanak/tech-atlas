"""Where each skill is used: the pipeline's steps, each with its skills and
the calls ("recipes") that stack several skills into one, and what each used
in the step's last full run (from llm_calls).

A step's last full run is the newest run of the step's own kind with at least
half the calls of that kind's largest recorded run, so a small test run, or a
find-evidence job that reads a page, doesn't stand in for a collection. A
stacked call's tokens belong to the call, not to any one skill in it; a skill
counts only the calls that asked it alone."""

from fastapi import APIRouter

from app.services.db.mongo import get_collection

router = APIRouter()

# (step, its name, the run kind its calls are recorded under)
STAGES = [("collect", "Collect", "collection"), ("organise", "Organize", "resolve"),
          ("classify", "Classify", "classify"), ("assess", "Assess", "scoring"), ("pov", "Point of View", "pov")]

USED = {"calls": {"$sum": 1},
        "tokens_in": {"$sum": {"$add": ["$input_tokens", "$cache_read_tokens", "$cache_write_tokens"]}},
        "tokens_out": {"$sum": "$output_tokens"}, "reused": {"$sum": "$cache_read_tokens"}}


def full_run(kind: str) -> dict | None:
    """The last full run of this kind: {run_id, at, calls}; None before any."""
    runs = list(get_collection("llm_calls").aggregate([
        {"$match": {"run_kind": kind, "run_id": {"$ne": None}}},
        {"$group": {"_id": "$run_id", "at": {"$min": "$at"}, "calls": {"$sum": 1}}}]))
    if not runs:
        return None
    biggest = max(r["calls"] for r in runs)
    run = max((r for r in runs if r["calls"] * 2 >= biggest), key=lambda r: r["at"])
    return {"run_id": run["_id"], "at": run["at"], "calls": run["calls"]}


def used(run: dict | None, kind: str, match: dict) -> dict | None:
    """Calls and tokens (in, reused, out) of the calls matching `match` in
    that run; None when it made none."""
    if run is None:
        return None
    rows = list(get_collection("llm_calls").aggregate([
        {"$match": {**match, "run_id": run["run_id"], "run_kind": kind}},
        {"$group": {"_id": None, **USED}}]))
    return {k: rows[0][k] for k in USED} if rows else None


@router.get("/skills/map")
def skills_map() -> dict:
    recipes = list(get_collection("recipes").find())
    names = {r["_id"]: r.get("name") or r["_id"] for r in recipes}
    stages = []
    for stage_id, name, kind in STAGES:
        run = full_run(kind)
        skills = [{"name": p["_id"], "title": p.get("title") or p["_id"], "agent": bool(p.get("agent")),
                   "enabled": p.get("enabled", True), "description": p.get("description"),
                   "recipes": [{"recipe_id": r["_id"], "name": names[r["_id"]]}
                               for r in recipes if p["_id"] in r.get("skills", [])],
                   "alone": used(run, kind, {"skills": p["_id"], "recipe": None})}
                  for p in get_collection("prompts").find({"stage": stage_id}).sort("order", 1)]
        # a stacked call, and each of its skills asked alone in the same run
        # (when the call's reply left that task out)
        stages.append({"id": stage_id, "name": name, "run": run, "skills": skills,
                       "recipes": [{"recipe_id": r["_id"], "name": names[r["_id"]], "skills": r.get("skills", []),
                                    "used": used(run, kind, {"recipe": r["_id"]}),
                                    "alone": {s: u for s in r.get("skills", [])
                                              if (u := used(run, kind, {"skills": s, "recipe": None}))}}
                                   for r in recipes if r.get("stage") == stage_id]})
    unplaced = [p["_id"] for p in get_collection("prompts").find(
        {"stage": {"$nin": [s for s, _, _ in STAGES]}}, {"_id": 1})]
    return {"stages": stages, "unplaced": unplaced}
