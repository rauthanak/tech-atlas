"""End-to-end timing on the scale copy (10 million pages, 24 Oct): the
background processes, driven through the API as a person would, each timed,
with the stand-in model (MODEL_PROVIDER=standin on atlas-scale and
worker-scale), so the radar's own work is measured at no model cost. The
model's own time is then added from the live radar's average per call.

    python3 e2e_scale.py [step ...]      (from this Mac; plain Python 3.9, nothing to install)
    steps: start upkeep collection assessment povs publish import rename recheck recount
           (all by default, in that order; `start` expects the copy's API and worker stopped)

Writes e2e-scale-results.json beside it (each step's timings, merged with earlier runs).
Never touches the live radar: it talks to the copy's API on 127.0.0.1:8199 only.
It signs in first (since 25 Oct), as RADAR_CHECK_EMAIL / RADAR_CHECK_PASSWORD from
the environment: an admin account on the copy, never stored here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid

API = "http://127.0.0.1:8199/api"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "e2e-scale-results.json")
CATALOG = os.path.join(HERE, "../../../../../../review-comments/10-20-2026/Emerging-technologies October 2026.xlsx")
# the live model's average time per call (ms), from its llm_calls on 24 Oct: added to the stand-in's timings
LIVE_MS = {"article_summary": 4847, "link_selection": 2239, "classify": 2116, "technology": 22917, "fabric": 38037,
           "pov": 57619, "technology_names": 9967, "name_check": 857, "technology_resolve": 15000}


_session: list[str] = []


def cookie() -> str:
    """The copy's sign-in cookie, made once."""
    if not _session:
        body = json.dumps({"email": os.environ["RADAR_CHECK_EMAIL"], "password": os.environ["RADAR_CHECK_PASSWORD"]})
        req = urllib.request.Request(API + "/auth/sign-in", data=body.encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            _session.append(r.headers["Set-Cookie"].split(";", 1)[0])
    return _session[0]


def call(method: str, path: str, body=None, timeout: int = 600):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", "Cookie": cookie()})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def timed(method: str, path: str, body=None, timeout: int = 600):
    t = time.time()
    out = call(method, path, body, timeout)
    return out, round(time.time() - t, 2)


def inside(code: str) -> str:
    """Python run inside the copy's API container (for what the API has no address for)."""
    return subprocess.run(["docker", "exec", "tech-radar-atlas-scale-1", "python", "-c", code],
                          capture_output=True, text=True, check=True).stdout.strip()


def wait(check, every: float = 10, limit: float = 6 * 3600):
    t = time.time()
    while time.time() - t < limit:
        got = check()
        if got:
            return got, round(time.time() - t, 1)
        time.sleep(every)
    raise TimeoutError("still going after the time limit")


def calls_of(run_id: str) -> dict:
    """The stand-in's calls a run made, by recipe or skill."""
    return json.loads(inside(
        "import json\nfrom app.services.db.mongo import get_collection as g\n"
        f"print(json.dumps({{(r['_id']['r'] or r['_id']['s']): r['n'] for r in g('llm_calls').aggregate(["
        f"{{'$match': {{'run_id': {run_id!r}}}}}, {{'$group': {{'_id': {{'r': '$recipe', 's': {{'$arrayElemAt': ['$skills', 0]}}}},"
        f" 'n': {{'$sum': 1}}}}}}])}}))"))


def with_model(calls: dict, concurrency: int) -> float:
    """Seconds the real model would add to these calls, run `concurrency` at a time."""
    return round(sum(n * LIVE_MS.get(k, 5000) for k, n in calls.items()) / 1000 / concurrency, 1)


def step_collection() -> dict:
    run, start_s = timed("POST", "/runs", {"max_pages_per_source": 15})
    run_id = run["id"]
    done, total_s = wait(lambda: (lambda r: r if r["status"] not in ("running", "terminating") else None)(
        call("GET", f"/runs/{run_id}")), every=20)
    stages = done.get("stage_history") or []
    took = {}
    for a, b in zip(stages, stages[1:] + [{"at": done.get("run_end_date_time")}]):
        if a.get("at") and b.get("at"):
            took[a["stage"]] = round((time_of(b["at"]) - time_of(a["at"])), 1)
    calls = calls_of(run_id)
    for part in (done.get("resolve_id"),):
        if part:
            calls.update({f"organize:{k}": v for k, v in calls_of(part).items()})
    return {"run_id": run_id, "status": done["status"], "answered_start_s": start_s, "total_s": total_s,
            "stages_s": took, "pages": (done.get("totals") or {}).get("documents"),
            "new_pages": (done.get("totals") or {}).get("new_documents"), "sources": (done.get("totals") or {}).get("sources"),
            "stand_in_calls": calls, "model_would_add_s": with_model(calls, 5)}


def time_of(at: str) -> float:
    from datetime import datetime
    return datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp()


def step_assessment() -> dict:
    # 50 switched-on technologies with the most pages (from the database: the list shows only those worked out so far)
    ids = json.loads(inside("import json\nfrom app.services.db.mongo import get_collection as g\n"
                            "print(json.dumps([t['_id'] for t in g('technologies').find({'enabled': {'$ne': False}}, "
                            "{'_id': 1}).sort('page_count', -1).limit(50)]))"))
    started, start_s = timed("POST", "/scoring/runs", {"technologies": ids})
    run_id = started["scoring_run_id"]
    done, total_s = wait(lambda: (lambda r: r if r["status"] not in ("running", "terminating") else None)(
        call("GET", f"/scoring/runs/{run_id}")), every=10)
    calls = calls_of(run_id)
    return {"run_id": run_id, "technologies": len(ids), "status": done["status"], "answered_start_s": start_s,
            "total_s": total_s, "per_technology_s": round(total_s / max(1, len(ids)), 2), "assessments": done.get("assessed"),
            "stand_in_calls": calls, "model_would_add_s": with_model(calls, 6)}


def step_povs() -> dict:
    run_id = load().get("assessment", {}).get("run_id")
    job = inside(
        "from agent.analyzer import pov\nfrom app.services.db.mongo import get_collection as g\n"
        f"t=[{{'scoring_run_id': {run_id!r}, 'tech_id': x}} for x in g('assessments').distinct('tech_id', {{'scoring_run_id': {run_id!r}}})]\n"
        "print(pov.start_compose_all(t))")
    done, total_s = wait(lambda: (lambda j: j if j and j["status"] != "running" else None)(
        call("GET", "/scoring/povs?limit=1")["job"]), every=5)
    calls = calls_of(job)
    return {"job_id": job, "written": done.get("done"), "failed": len(done.get("failed") or []), "total_s": total_s,
            "per_pov_s": round(total_s / max(1, done.get("done") or 1), 2), "stand_in_calls": calls,
            "model_would_add_s": with_model(calls, 6)}


def relinked(since: str) -> dict:
    """Wait for the page re-links an edit queued (services/jobs.later) since then; their time in the worker."""
    code = ("import json\nfrom app.services.db.mongo import get_collection as g\n"
            f"j=list(g('jobs').find({{'again': True, 'queued_at': {{'$gte': {since!r}}}}}, {{'status':1,'queued_at':1,'started_at':1,'finished_at':1}}))\n"
            "print(json.dumps(j))")
    jobs_, waited = wait(lambda: (lambda j: j if j and all(x['status'] in ('done', 'failed') for x in j) else None)(
        json.loads(inside(code))), every=10, limit=3 * 3600)
    return {"jobs": len(jobs_), "failed": sum(1 for x in jobs_ if x["status"] == "failed"),
            "in_worker_s": round(sum(time_of(x["finished_at"]) - time_of(x["started_at"]) for x in jobs_), 1),
            "waited_s": waited}


def now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def step_publish() -> dict:
    out, s = timed("POST", "/editions", {"name": f"scale test {uuid.uuid4().hex[:4]}"}, 3600)
    return {"publish_s": s, "counts": out["edition"]["counts"]}


def step_import() -> dict:
    boundary = uuid.uuid4().hex
    content = open(CATALOG, "rb").read()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"catalog.xlsx\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(API + "/imports", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Cookie": cookie()})
    t = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        imp = json.loads(r.read())
    upload_s = round(time.time() - t, 2)
    since = now_iso()
    imp, match_s = timed("POST", f"/imports/{imp['_id']}/match")
    rows = [i["row"] for i in imp["items"] if i["group"] == "proposed"]
    accept_s = 0.0
    if rows:
        _, accept_s = timed("PUT", f"/imports/{imp['_id']}/items", {"rows": rows, "decision": "accept"})
    out, confirm_s = timed("POST", f"/imports/{imp['_id']}/confirm")
    return {"rows": len(imp["items"]), "upload_and_check_s": upload_s, "match_s": match_s, "accept_s": accept_s,
            "confirm_s": confirm_s, "result": out, "relink": relinked(since)}


def step_rename() -> dict:
    tech = call("GET", "/technologies?limit=1")["technologies"][0]
    name = tech.get("label") or tech["name"]
    since = now_iso()
    _, s1 = timed("PUT", f"/technologies/{tech['_id']}", {"name": f"{name} renamed", "enabled": True})
    first = relinked(since)
    since = now_iso()
    _, s2 = timed("PUT", f"/technologies/{tech['_id']}", {"name": name, "enabled": True})
    return {"technology": name, "pages": tech.get("page_count"), "rename_s": s1, "relink": first,
            "rename_back_s": s2, "relink_back": relinked(since)}


def step_recheck() -> dict:
    signals, list_s = timed("GET", "/signals")
    row = next(r for r in signals["signals"] if r["mode"] == "never_miss")
    body = {k: row[k] for k in ("name", "look_for", "mode")}
    since = now_iso()
    _, switch_s = timed("PUT", f"/signals/{row['_id']}", {**body, "enabled": not row["enabled"]})
    rerank = relinked(since)
    started, start_s = timed("POST", "/signals/recheck")
    sample = 600
    time.sleep(sample)
    job = call("GET", "/signals")["recheck"]
    rate = job["done"] / sample
    call("PUT", f"/signals/{row['_id']}", {**body, "enabled": row["enabled"]})  # back as it was
    subprocess.run(["docker", "compose", "--profile", "scale", "restart", "worker-scale"], check=True,
                   cwd=os.path.join(HERE, "../../../../.."), capture_output=True)  # ends the check (it would run for hours)
    return {"checkable_pages": signals["checkable_pages"], "signal_list_s": list_s, "switch_s": switch_s, "rerank": rerank,
            "start_s": start_s, "pages_in_sample": job["done"], "sample_s": sample, "pages_per_s": round(rate, 1),
            "all_pages_would_take_h": round(started["total"] / max(rate, 0.01) / 3600, 1),
            "model_would_add_h": round(started["total"] * LIVE_MS["article_summary"] / 1000 / 5 / 3600, 1)}


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", "--profile", "scale", *args], check=True, capture_output=True,
                   cwd=os.path.join(HERE, "../../../../.."))


def logs(service: str, word: str) -> list[str]:
    out = subprocess.run(["docker", "compose", "--profile", "scale", "logs", "--no-log-prefix", service],
                         cwd=os.path.join(HERE, "../../../../.."), capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if word in line]


def answers() -> bool:
    try:
        call("GET", "/health", timeout=5)
        return True
    except Exception:
        return False


def step_start() -> dict:
    """API and worker started on the copy: the time to the API's first answer (the once-only upgrade of the
    page records runs first, 24 Oct), then the worker's index builds in the background."""
    t = time.time()
    compose("up", "-d", "atlas-scale", "worker-scale")
    _, api_s = wait(lambda: answers(), every=5, limit=12 * 3600)
    missing = ("import json\nfrom app.services.db import bootstrap\nfrom app.services.db.mongo import get_db\ndb=get_db()\n"
               "have={c: [list(map(list, i['key'])) for i in db[c].index_information().values()] for c in db.list_collection_names()}\n"
               "print(sum(1 for ix in bootstrap.declared_indexes() if [list(k) for k in ix['keys']] not in have.get(ix['collection'], [])))")
    _, more_s = wait(lambda: inside(missing) == "0", every=30, limit=12 * 3600)
    upgraded = logs("atlas-scale", "upgraded")
    return {"api_first_answer_s": api_s, "upgrade_log": upgraded[-1] if upgraded else None,
            "indexes_built_after_s": round(time.time() - t, 1), "after_api_answered_s": more_s,
            "index_builds": logs("worker-scale", "built in")}


def behind() -> tuple[int, int]:
    got = inside("from app.services import briefing_days, tech_status\nfrom app.services.timezone import now_utc\n"
                 "print(tech_status.pending(), briefing_days.ready(None, now_utc())[1])")
    a, b = got.split()
    return int(a), int(b)


def step_upkeep() -> dict:
    """The start-up upkeep: every technology's stored answers, and every Briefing day, worked out."""
    first = behind()
    _, s = wait(lambda: behind() == (0, 0), every=60, limit=24 * 3600)
    return {"waiting_at_start": {"technologies": first[0], "briefing_days": first[1]}, "total_s": s}


def step_recount() -> dict:
    """A full recount of the stored answers, as a settings change starts it (tech_status.touch_all)."""
    inside("from app.services import tech_status\ntech_status.touch_all()")
    n = behind()[0]
    _, s = wait(lambda: behind()[0] == 0, every=60, limit=24 * 3600)
    return {"technologies": n, "total_s": s, "per_s": round(n / max(s, 1), 1)}


def step_classify() -> dict:
    """Who waits for Classify (read from the answers kept ready), then 200 of them judged."""
    t = time.time()
    n = int(inside("from agent.classifier import classify\nprint(len(classify.pending()))"))
    pending_s = round(time.time() - t, 1)
    ids = json.loads(inside("import json\nfrom agent.classifier import classify\nprint(json.dumps(classify.pending()[:200]))"))
    started, start_s = timed("POST", "/classify", {"tech_ids": ids})
    run_id = started["run_id"]
    done, total_s = wait(lambda: (lambda r: r if r and r.get("status") not in ("running", "terminating") else None)(
        json.loads(inside("import json\nfrom app.services.db.mongo import get_collection as g\n"
                          f"print(json.dumps(g('classify_runs').find_one({{'_id': {run_id!r}}}, {{'status':1,'done':1,'total':1}})))"))),
        every=10)
    calls = calls_of(run_id)
    return {"waiting": n, "pending_s": pending_s, "technologies": len(ids), "status": done["status"], "done": done.get("done"),
            "start_s": start_s, "total_s": total_s, "per_technology_s": round(total_s / max(1, len(ids)), 2),
            "stand_in_calls": calls, "model_would_add_s": with_model(calls, 6)}


STEPS = {"start": step_start, "upkeep": step_upkeep, "collection": step_collection, "assessment": step_assessment, "povs": step_povs, "publish": step_publish,
         "import": step_import, "rename": step_rename, "recheck": step_recheck, "recount": step_recount,
         "classify": step_classify}


def load() -> dict:
    return json.load(open(OUT)) if os.path.exists(OUT) else {}


if __name__ == "__main__":
    results = load()
    for name in sys.argv[1:] or list(STEPS):
        print(f"── {name}", flush=True)
        try:
            results[name] = STEPS[name]()
        except Exception as exc:  # a step that fails says why, and the next goes on
            results[name] = {"error": f"{type(exc).__name__}: {exc}"}
        results[name]["at"] = time.strftime("%Y-%m-%d %H:%M")
        print(json.dumps(results[name], indent=1), flush=True)
        json.dump(results, open(OUT, "w"), indent=1)
