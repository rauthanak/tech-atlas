"""The stacked assessment: one call per technology, then one per fabric.

Measures carry a scope (Setup → Measures):
  technology  judged once for the technology as a whole (market, growth,
              breadth of use, maturity, commercial adoption) — in the
              technology call, then copied into every fabric's assessment
  fabric      judged in each fabric the technology touches (fit, adjacency,
              right to play, deliverability, capability gap) — one fabric call
              per relevant fabric
  tata        entered by Tata Communications (disruption threat, serviceable
              capture): never asked of the model; waiting until entered

The technology call also carries the fabric choice and the metrics to watch,
so a technology costs 1 + its fabrics calls instead of ~30, and its evidence
is sent once and reused by its fabric calls (services/prompts/recipe). A task
missing from a reply, or failing its skill's rules, is asked again alone with
the skill's normal single call, as the per-measure engine always did."""

from concurrent.futures import ThreadPoolExecutor

from agent.analyzer import engine, value
from app.services.db.mongo import get_collection
from app.services.llm.context import carry, with_context
from app.services.llm.llm import LLM
from app.services.prompts import recipe as recipes
from app.services.prompts.recipe import Failure, Task
from app.services.timezone import now_utc

# the fabric blanks of a measure judged for the technology as a whole
WHOLE = {"_id": None, "name": "the technology as a whole, not one fabric",
         "definition": "This measure doesn't depend on the fabric: judge the technology as a whole. "
                       "The same score is used in every fabric it is assessed in.",
         "tcl_today": "Not needed for this measure."}
WAITING_FOR_TATA = "waiting for Tata: this measure is entered by Tata Communications, not scored from pages"


def scope(measure: dict) -> str:
    return measure.get("scope") or "fabric"


def _recipe(run: dict, recipe_id: str) -> dict:
    """The run's frozen recipe, else the live one, else the default order."""
    frozen = next((r for r in (run.get("snapshot") or {}).get("recipes") or [] if r["_id"] == recipe_id), None)
    return frozen or get_collection("recipes").find_one({"_id": recipe_id}) or {"_id": recipe_id, "cache": "evidence"}


# ── each skill's rules for its answer (the same as the single calls') ──

def _relevance_check(fabrics: list[dict]):
    def check(value, task):
        ids = set(value.get("fabrics", [])) if isinstance(value, dict) else set()
        chosen = [f["_id"] for f in fabrics if f["_id"] in ids]
        if not chosen:
            raise ValueError("no known fabric chosen")
        return chosen
    return check


def _measure_check(value, task):
    if not isinstance(value, dict):
        raise ValueError("a measure's answer must be an object")
    return engine.measure_result(value)


def _watch_check(value, task):
    if not isinstance(value, list):
        raise ValueError("metrics to watch must be a list")
    return [m for m in value if isinstance(m, dict) and m.get("metric")]


def _measure_task(m: dict, fabric: dict | None) -> Task:
    values = engine.measure_scoring_values(m, "", fabric or WHOLE, "")
    values = {k: v for k, v in values.items() if k not in ("technology", "evidence")}
    if fabric is not None:  # a fabric call gives the fabric once, for all its measures
        values = {k: v for k, v in values.items() if k not in ("fabric_name", "fabric_definition", "tcl_today")}
    return Task(key=f"measure:{m['_id']}", skill="measure_scoring",
                heading=f"Score one measure: {m.get('name')}", values=values)


def _ask(llm: LLM, built: recipes.Built, run_id: str, validators: dict, defaults: dict, **kw) -> tuple[dict, int]:
    """The stacked call (services/prompts/recipe), every call counted on the
    run; a measure that fails alone too is unscored, saying why."""
    return recipes.ask(llm, built, validators, {"measure_scoring": engine.unscored, **defaults},
                       on_call=lambda: engine._bump(run_id, llm_calls=1), cancelled=lambda: engine.cancelled(run_id), **kw)


# ── the two calls ─────────────────────────────────────────────────────
# Built by these two functions for a run and for the Skills page's preview
# alike, so the preview shows exactly what a run sends.

def _lists() -> dict | None:
    """The classification lists, once seeded: the technology call then also
    judges domain, readiness (TRL) and availability from the full evidence."""
    from agent.classifier.classify import lists
    ls = lists()
    return ls if ls["domains"] and ls["availability"] and ls["trl_levels"] else None


def technology_built(recipe: dict, name: str, dossier: str, measures: list[dict], fabrics: list[dict],
                     ls: dict | None = None) -> recipes.Built:
    from agent.classifier.classify import classification_tasks, list_values
    tasks = [Task("fabric_relevance", "fabric_relevance", "Choose the fabrics to assess",
                  {"fabrics": engine.fabric_list(fabrics)}),
             *(_measure_task(m, None) for m in measures if scope(m) == "technology"),
             Task("watch_metrics", "watch_metrics", "Suggest metrics to watch")]
    if ls is not None:  # when the recipe carries them: domain, readiness (TRL) and availability
        classification = classification_tasks(list_values(ls), with_evidence_and_nascent=False)
        if set(recipe.get("skills") or []) >= {t.skill for t in classification}:
            tasks += classification
    return recipes.build(recipe, tasks, {"technology": name, "evidence": dossier})


def fabric_built(recipe: dict, name: str, dossier: str, measures: list[dict], fabric: dict) -> recipes.Built:
    tasks = [_measure_task(m, fabric) for m in measures if scope(m) == "fabric"]
    if "value_levers" in (recipe.get("skills") or []):
        tasks.append(value.task(fabric, value.mechanisms()))
    return recipes.build(recipe, tasks, {"technology": name, "evidence": dossier, **engine.fabric_values(fabric)})


def technology_call(llm: LLM, run: dict, entry: dict, dossier: str, measures: list[dict],
                    fabrics: list[dict], pages: list[str] | None = None) -> dict:
    """Which fabrics, the technology-level measures, the metrics to watch, and
    (once the lists exist) its domain, TRL and availability. Returns {gates,
    measures, watch_metrics, classification, retries}."""
    from agent.classifier.classify import FIELD_OF, validators as classification_checks
    ls = _lists()
    built = technology_built(_recipe(run, "technology"), entry["name"], dossier, measures, fabrics, ls)
    checks = {"fabric_relevance": _relevance_check(fabrics), "measure_scoring": _measure_check,
              "watch_metrics": _watch_check, **(classification_checks(ls, pages or []) if ls is not None else {})}
    # a gate that fails widens scoring to every fabric, never narrows it; a
    # failed classification answer isn't asked again (Classify has one from the pages)
    out, retries = _ask(llm, built, run["_id"], checks,
                        {"fabric_relevance": lambda why: [f["_id"] for f in fabrics], "watch_metrics": lambda why: []},
                        not_again=FIELD_OF)
    return {"gates": out["fabric_relevance"],
            "measures": {m["_id"]: out[f"measure:{m['_id']}"] for m in measures if scope(m) == "technology"},
            "watch_metrics": out["watch_metrics"],
            "classification": {FIELD_OF[k]: v for k, v in out.items() if k in FIELD_OF and not isinstance(v, Failure)},
            "retries": retries}


def fabric_call(llm: LLM, run: dict, entry: dict, dossier: str, measures: list[dict], fabric: dict,
                pages: list[str] | None = None) -> dict:
    """The fabric-level measures in one fabric, and where the value lands
    there. Returns {measures, value, retries}."""
    with with_context(fabric_id=fabric["_id"]):
        built = fabric_built(_recipe(run, "fabric"), entry["name"], dossier, measures, fabric)
        if not built.tasks:
            return {"measures": {}, "value": None, "retries": 0}
        out, retries = _ask(llm, built, run["_id"],
                            {"measure_scoring": _measure_check,
                             "value_levers": value.check(fabric, value.mechanisms(), pages or [])},
                            {"value_levers": value.failed})  # failed twice: the reason is kept and shown
    return {"measures": {m["_id"]: out[f"measure:{m['_id']}"] for m in measures if scope(m) == "fabric"},
            "value": out.get("value_levers"), "retries": retries}


def tata_results(measures: list[dict]) -> dict:
    """Measures Tata enters: not asked; waiting until entered (Gate 2 applies entries)."""
    return {m["_id"]: {"score": None, "unscorable": True, "missing": WAITING_FOR_TATA, "justification": None,
                       "evidence_urls": [], "counter_case": None, "waiting_for_tata": True}
            for m in measures if scope(m) == "tata"}


# ── one technology ───────────────────────────────────────────────────

def assess(run_id: str, tech_id: str, llm: LLM, executor: ThreadPoolExecutor) -> str:
    loaded = engine._load(run_id, tech_id, signals_first=True)
    if isinstance(loaded, str):
        return loaded
    run, entry, built = loaded
    measures, fabrics, dossier = run["snapshot"]["measures"], run["snapshot"]["fabrics"], built["text"]

    # the technology call's answers are kept on the run, so a resume never re-asks them
    done = (run.get("tech_calls") or {}).get(tech_id)
    if done is None:
        done = technology_call(llm, run, entry, dossier, measures, fabrics, built["pages"])
        get_collection("scoring_runs").update_one({"_id": run_id}, {"$set": {f"gates.{tech_id}": done["gates"],
                                                                             f"tech_calls.{tech_id}": done}})
        if done.get("classification"):
            at = now_utc()
            get_collection("technologies").update_one({"_id": tech_id}, {"$set": {
                "assessed_classification": {f: {**v, "source": "assessment", "at": at, "run_id": run_id}
                                            for f, v in done["classification"].items()}}})
    wanted = [f for f in fabrics if f["_id"] in done["gates"]]
    owed = [f for f in wanted if not get_collection("assessments").find_one(
        {"_id": f"{run_id}:{tech_id}:{f['_id']}"}, {"_id": 1})]
    futures = {f["_id"]: executor.submit(carry(fabric_call), llm, run, entry, dossier, measures, f, built["pages"])
               for f in owed if not engine.cancelled(run_id)}
    tech_scored = {mid: {**r, "scope": "technology"} for mid, r in done["measures"].items()}
    waiting = {mid: {**r, "scope": "tata"} for mid, r in tata_results(measures).items()}
    assessed = []
    for f in owed:
        if f["_id"] not in futures:
            continue
        fab = futures[f["_id"]].result()
        results = {**tech_scored, **{mid: {**r, "scope": "fabric"} for mid, r in fab["measures"].items()}, **waiting}
        get_collection("assessments").insert_one(engine.assessment_doc(
            run, entry, f, built, results, watch_metrics=done["watch_metrics"],
            **(value.fields(fab["value"]) if fab.get("value") else {}), engine="stacked",
            calls={"technology_call": 1, "fabric_call": 1, "retries": done["retries"] + fab["retries"]}))
        assessed.append(f.get("name"))
    engine.mark_progress(run_id)
    return f"{entry['name']}: assessed in {', '.join(assessed) or 'no new fabrics'}"
