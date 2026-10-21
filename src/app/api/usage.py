"""What the model calls cost, from llm_calls (services/llm/usage): one run's
(or several runs') calls and tokens by skill, and every recent run that
called the model, one row per run and kind, with what it was."""

from fastapi import APIRouter

from app.services.db.mongo import get_collection

router = APIRouter()

SUMS = {"calls": {"$sum": 1}, "failed": {"$sum": {"$cond": ["$ok", 0, 1]}},
        "input_tokens": {"$sum": "$input_tokens"}, "output_tokens": {"$sum": "$output_tokens"},
        "cache_read_tokens": {"$sum": "$cache_read_tokens"}, "cache_write_tokens": {"$sum": "$cache_write_tokens"}}
FIELDS = list(SUMS)

# where each kind of run keeps its own record, and what of it the history shows
JOBS = {"collection": ("runs", ("status",)),
        "scoring": ("scoring_runs", ("status",)),
        "resolve": ("resolves", ("status",)),
        "classify": ("classify_runs", ("status", "tz", "total", "unchanged", "trigger")),
        "find_evidence": ("find_evidence_jobs", ("status", "tz", "gap", "summary")),
        "import": ("imports", ("status", "tz", "file")),
        "recheck": ("recheck_jobs", ("status", "total")),
        "pov": ("pov_compose_jobs", ("status", "tz", "total"))}
NOT_SKILLS = {"web_search": "Web search"}  # calls made with no skill of their own


def _label(row: dict) -> str:
    """A call's code name: its recipe when it stacked several skills, else its skill."""
    return row.get("recipe") or ", ".join(row.get("skills") or []) or "other"


def _namer():
    """A call's name on screen: its recipe's name, else its skills' titles."""
    recipes = {r["_id"]: r.get("name") or r["_id"] for r in get_collection("recipes").find({}, {"name": 1})}
    titles = {**NOT_SKILLS, **{p["_id"]: p.get("title") or p["_id"]
                               for p in get_collection("prompts").find({}, {"title": 1})}}
    return lambda row: (recipes.get(row["recipe"], row["recipe"]) if row.get("recipe")
                        else " + ".join(titles.get(s, s) for s in row.get("skills") or []) or "Other")


def _total(rows: list[dict]) -> dict:
    return {f: sum(r[f] for r in rows) for f in FIELDS}


def recorded_since() -> str | None:
    """When token recording began: runs started before it have no tokens, or only some."""
    first = get_collection("llm_calls").find_one({}, {"at": 1}, sort=[("at", 1)])
    return first["at"] if first else None


@router.get("/usage")
def usage(run_id: str, kind: str | None = None) -> dict:
    """One run's model calls by skill (or recipe), with the run's total. Several
    run ids, joined by commas, are added together (a collection and the
    organize that ended it). `kind` keeps one kind of run only (an assessment
    run's own calls, not the Points of View once written under its id)."""
    names = _namer()
    merged: dict[str, dict] = {}
    for g in get_collection("llm_calls").aggregate([
            {"$match": {"run_id": {"$in": run_id.split(",")}, **({"run_kind": kind} if kind else {})}},
            {"$group": {"_id": {"recipe": "$recipe", "skills": "$skills"}, **SUMS}}]):
        key = _label(g["_id"])
        m = merged.setdefault(key, {"skill": key, "name": names(g["_id"]), **{f: 0 for f in FIELDS}})
        for f in FIELDS:
            m[f] += g[f]
    # most tokens first: sent, reused, stored for reuse and written back
    by_skill = sorted(merged.values(), key=lambda r: -(r["input_tokens"] + r["output_tokens"]
                                                       + r["cache_read_tokens"] + r["cache_write_tokens"]))
    return {"run_id": run_id, "kind": kind, "by_skill": by_skill, "total": _total(by_skill),
            "recorded_since": recorded_since()}


def _parents(ids: list[str]) -> dict[str, dict]:
    """The runs that belong to another: the organize that ended a collection
    or a check of stored pages, and the page reading of a find-evidence job."""
    out: dict[str, dict] = {}
    for run in get_collection("runs").find(
            {"$or": [{"resolve_id": {"$in": ids}}, {"_id": {"$in": ids}, "params.kind": "find_evidence"}]},
            {"resolve_id": 1, "params": 1}):
        if (run.get("params") or {}).get("kind") == "find_evidence":
            out[run["_id"]] = {"kind": "find_evidence", "id": run["params"].get("job_id")}
        if run.get("resolve_id") in ids:
            out[run["resolve_id"]] = {"kind": "collection", "id": run["_id"]}
    for job in get_collection("recheck_jobs").find({"resolve_id": {"$in": ids}}, {"resolve_id": 1}):
        out[job["resolve_id"]] = {"kind": "recheck", "id": job["_id"]}
    return out


def _about(rows: list[dict]) -> dict[tuple, dict]:
    """What each run's own record says, by (run id, kind). Points of View
    written under an assessment run's id say which run."""
    out: dict[tuple, dict] = {}
    for kind, (coll, fields) in JOBS.items():
        ids = [r["run_id"] for r in rows if r["run_kind"] == kind]
        if not ids:
            continue
        for doc in get_collection(coll).find({"_id": {"$in": ids}}, dict.fromkeys(fields, 1)):
            out[(doc.pop("_id"), kind)] = doc
        if kind == "pov":
            for run in get_collection("scoring_runs").find(
                    {"_id": {"$in": [i for i in ids if (i, kind) not in out]}}, {"started_at": 1}):
                out[(run["_id"], kind)] = {"assessment": {"id": run["_id"], "started_at": run["started_at"]}}
        if kind == "find_evidence":
            techs = {t["_id"]: t.get("label") or t.get("name") for t in get_collection("technologies").find(
                {"_id": {"$in": [d["gap"]["tech_id"] for (_, k), d in out.items()
                                 if k == kind and (d.get("gap") or {}).get("tech_id")]}}, {"name": 1, "label": 1})}
            for (_, k), d in out.items():
                if k == kind and d.get("gap"):
                    d["technology"] = techs.get(d["gap"].get("tech_id"))
    return out


@router.get("/usage/recent")
def recent(limit: int = 10) -> dict:
    """The latest runs that called the model, newest first, one row per run and
    kind (a Point of View written under an assessment run's id is its own row),
    with their tokens; `part_of` when the run belongs to another (_parents);
    `about`, what its own record says. `recorded_since`: when token recording
    began."""
    runs = [{"run_id": g["_id"]["run_id"], "run_kind": g["_id"].get("run_kind"),
             **{k: g[k] for k in ("first_at", "last_at", *FIELDS)}}
            for g in get_collection("llm_calls").aggregate([
                {"$match": {"run_id": {"$ne": None}}},
                {"$group": {"_id": {"run_id": "$run_id", "run_kind": "$run_kind"},
                            "first_at": {"$min": "$at"}, "last_at": {"$max": "$at"}, **SUMS}},
                {"$sort": {"last_at": -1}}, {"$limit": max(1, min(limit, 500))}])]
    parents = _parents([r["run_id"] for r in runs])
    about = _about(runs)
    for r in runs:
        r["part_of"] = parents.get(r["run_id"])
        r["about"] = about.get((r["run_id"], r["run_kind"]))
    return {"runs": runs, "recorded_since": recorded_since()}
