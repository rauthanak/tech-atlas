"""The Briefing's findings, kept ready a day at a time, so a week, 30 days or
all time read a few small records instead of every page.

One idea: for each day (UTC, by when pages were collected) the findings of
that day's pages, copies of one story counted once, are kept as rows
(`briefing_rows`, one per finding, in the Briefing's order) with the day's
totals (`briefing_days`). A day is worked out again the next time it's read
after any page of it changed: a collection storing a page, or Check again
rewriting one, marks its day (touch). So today stays current while a
collection runs, and an old day costs nothing until something changes it.

Totals: the first and last day of a window are counted from their rows (the
window may start or end inside them); the days between from their totals.
The list reads only the rows it shows, through an index in the Briefing's
order. People's reordering of the signal list re-ranks the rows (rerank)."""

import logging
import threading
import uuid
from datetime import datetime, timedelta

from pymongo import ASCENDING, DESCENDING

from app.services.db.mongo import get_collection
from app.services.timezone import now_utc

log = logging.getLogger(__name__)
ROWS, DAYS = "briefing_rows", "briefing_days"
ORDER = [("older", ASCENDING), ("rank", ASCENDING), ("date", DESCENDING), ("scraped_at", DESCENDING),
         ("doc_id", ASCENDING), ("n", ASCENDING)]  # the Briefing's order (api/signals.hits, sort="briefing")
_building = threading.Lock()  # one day worked out at a time


def day_of(at: str) -> str:
    return at[:10]


def _next(day: str) -> str:
    return (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()


def touch(at: str | None) -> None:
    """A page collected at `at` was stored or changed: its day is worked out again when next read."""
    if at:
        get_collection(DAYS).update_one({"_id": day_of(at)}, {"$set": {"touched_at": now_utc()}}, upsert=True)


def _fresh(rec: dict | None) -> bool:
    """Worked out since its pages last changed (a day from before its signal counts were kept is worked out again)."""
    return bool(rec and rec.get("built_at") and "hits" in rec and rec["built_at"] >= rec.get("touched_at", ""))


def build(day: str) -> dict:
    """Work one day out from its pages, with the same steps the live list uses."""
    from app.api import signals as s
    with _building:
        rec = get_collection(DAYS).find_one({"_id": day})
        if _fresh(rec):
            return rec  # worked out by another reader meanwhile
        started, build_id = now_utc(), uuid.uuid4().hex[:12]
        window = {"scraped_at": {"$gte": day, "$lt": _next(day)}}
        by = {"older": 1, "rank": 1, "date": -1, "scraped_at": -1, "_id": 1, "n": 1}
        rows = list(get_collection("documents").aggregate([
            *s._unwound(window, None), {"$addFields": s._keys(s.places())}, *s._stories(by),
            {"$project": {"_id": 0, "doc_id": "$_id", "n": 1, "url": "$end_url", "title": 1, "source_id": 1,
                          "run_id": 1, "scraped_at": 1, "published_date": 1, "older": 1, "rank": 1, "date": 1,
                          "signal_id": "$signals.signal_id", "hit": "$signals", "also": 1}}], allowDiskUse=True))
        for r in rows:
            r.update(day=day, build=build_id)
            r["hit"].pop("technologies", None)  # names as the page wrote them; the list resolves its own
            r["hit"].pop("technologies_resolved", None)
        if rows:
            get_collection(ROWS).insert_many(rows)
        types: dict[str, list[int]] = {}
        for r in rows:
            t = types.setdefault(r["signal_id"] or "", [0, 0])
            t[0] += 1
            t[1] += 1 if r["older"] else 0
        pages = get_collection("documents").count_documents({"is_stub": False, **window})
        get_collection(DAYS).update_one({"_id": day}, {"$set": {
            "built_at": started, "build": build_id, "pages": pages,
            "hits": s.hit_counts({"is_stub": False, **window}),  # every finding and set-aside page, for the Signals list
            "types": [{"signal_id": k, "count": c, "older": o} for k, (c, o) in types.items()]}}, upsert=True)
        get_collection(ROWS).delete_many({"day": day, "build": {"$ne": build_id}})  # the day's earlier rows
        return get_collection(DAYS).find_one({"_id": day})


def _days(since: str | None, until: str) -> list[str]:
    first = since or (get_collection("documents").find_one({"is_stub": False}, {"scraped_at": 1},
                                                           sort=[("scraped_at", 1)]) or {}).get("scraped_at")
    if not first:
        return []
    out, day = [], day_of(first)
    while day <= day_of(until):
        out.append(day)
        day = _next(day)
    return out


AT_ONCE_FROM = timedelta(days=1)  # days changed this recently are worked out when read: a running collection shows at once
ALWAYS_NOW = False  # every changed day worked out when read: the tests' mode, where nothing runs in the background


def ready(since: str | None, until: str) -> tuple[list[dict], int]:
    """The window's days as kept, and how many are still being brought up to
    date. A changed day of today or yesterday is worked out now; older changed
    days (a Check again rewrites pages of every day) are worked out in the
    background (catch_up), and until then show as they were last worked out;
    a day never worked out yet shows nothing until it is."""
    days = _days(since, until)
    recs = {r["_id"]: r for r in get_collection(DAYS).find({"_id": {"$in": days}})}
    recent = day_of((datetime.fromisoformat(now_utc()) - AT_ONCE_FROM).isoformat())
    behind = 0
    for d in days:
        if _fresh(recs.get(d)):
            continue
        if d >= recent or ALWAYS_NOW:
            recs[d] = build(d)
        else:
            behind += 1
    return [recs[d] for d in days if (recs.get(d) or {}).get("build")], behind


def _bounds(since: str | None, until: str) -> dict:
    return {"scraped_at": {**({"$gte": since} if since else {}), "$lt": until}}


def summary(since: str | None, until: str) -> dict:
    """A window's findings by kind and its pages, as the Briefing shows them."""
    recs, behind = ready(since, until)
    counts: dict[str, list[int]] = {}
    pages = 0
    edges = {recs[0]["_id"], recs[-1]["_id"]} if recs else set()
    for rec in recs:
        if rec["_id"] in edges:  # the window may start or end inside it: count its rows inside the window
            for g in get_collection(ROWS).aggregate([
                    {"$match": {"build": rec["build"], **_bounds(since, until)}},
                    {"$group": {"_id": "$signal_id", "count": {"$sum": 1}, "older": {"$sum": {"$cond": ["$older", 1, 0]}}}}]):
                c = counts.setdefault(g["_id"] or "", [0, 0])
                c[0], c[1] = c[0] + g["count"], c[1] + g["older"]
            pages += get_collection("documents").count_documents(
                {"is_stub": False, "scraped_at": {"$gte": max(since or rec["_id"], rec["_id"]), "$lt": min(until, _next(rec["_id"]))}})
        else:
            for t in rec.get("types") or []:
                c = counts.setdefault(t["signal_id"], [0, 0])
                c[0], c[1] = c[0] + t["count"], c[1] + t["older"]
            pages += rec.get("pages") or 0
    return {"pages": pages, "types": counts, "updating_days": behind}


def page(since: str | None, until: str, signal_id: str | None, older: bool | None, skip: int, limit: int) -> list[dict]:
    """The rows the Briefing's list shows, in its order."""
    recs, _ = ready(since, until)
    q = {"build": {"$in": [r["build"] for r in recs]}, **_bounds(since, until),
         **({"signal_id": signal_id} if signal_id else {}), **({"older": older} if older is not None else {})}
    return list(get_collection(ROWS).find(q, {"_id": 0, "build": 0, "day": 0}).sort(ORDER).skip(skip).limit(limit))


def rerank() -> None:
    """The signal list's order changed: each kept finding takes its kind's new
    place (only the kinds that moved are written: see signals.places)."""
    from app.api import signals as s
    listed = s.places()
    rows = get_collection(ROWS)
    for signal_id in rows.distinct("signal_id"):
        place = listed.get(signal_id, s.GONE + (signal_id == "other"))
        rows.update_many({"signal_id": signal_id, "rank": {"$ne": place}}, {"$set": {"rank": place}})


_stop = threading.Event()


def catch_up() -> int:
    """Work out every day that changed or was never worked out, newest first; how many."""
    days = _days(None, now_utc())
    recs = {r["_id"]: r for r in get_collection(DAYS).find({"_id": {"$in": days}})}
    done = 0
    for d in reversed(days):
        if _stop.is_set():
            break
        if not _fresh(recs.get(d)):
            build(d)
            done += 1
    return done


def _loop() -> None:
    try:
        rerank()  # the seeding data may have changed the signal list's order since the rows were kept
    except Exception:
        log.exception("briefing days: couldn't re-rank at start-up")
    while not _stop.is_set():
        try:
            catch_up()
        except Exception:  # the next round tries again; reading still works from the days kept
            log.exception("briefing days: catching up failed")
        _stop.wait(5)


def start() -> None:
    """In the process that runs the jobs (services/jobs.upkeep): days changed in bulk catch up in the background."""
    _stop.clear()
    threading.Thread(target=_loop, name="briefing-days", daemon=True).start()


def stop() -> None:
    _stop.set()


def prepare() -> None:
    """Every day not worked out yet, worked out now (a one-off: the stress check, or by hand)."""
    rerank()
    catch_up()
