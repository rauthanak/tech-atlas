"""The shared path for data sources (access: query). Each adapter answers a
source's saved searches from one free API; this module turns its results
into documents exactly like crawled pages, and keeps per-search progress so
nothing is skipped silently.

Saved-search windows:
- A search's window runs from its `through` date to today (from today minus
  lookback_days the first time); both ends included.
- Each run reads the window's results (at most MAX_RESULTS) and skips those
  already collected (by URL); those don't count toward the limit. Of the new
  ones it takes up to `limit`, oldest first.
- `remaining` is the new results not taken; `through` moves to today only
  when nothing is left to collect in the window.
- A window holding more than MAX_RESULTS is `too_broad`: narrow the search.
- An error leaves `through` unchanged, so the window is read again.

Digest adapters (job boards, USAJOBS) take a fresh snapshot each run: one
summary page per company or keyword, with the previous run's count."""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx

from agent.scout.tools.context import Context, Outcome
from app.services.db.mongo import get_collection
from app.services.llm import call_with_backoff

log = logging.getLogger(__name__)

MAX_RESULTS = 2000  # EPO's limit per query; the same cap for every adapter


@dataclass
class Item:
    url: str                    # stable and unique per item (the dedupe key)
    title: str
    text: str                   # what the summarizing step reads
    published_date: str | None
    kind: str                   # patent | paper | grant | filing | jobs-digest
    extra: dict = field(default_factory=dict)  # what complete() needs, if anything


class NotConfigured(Exception):
    """A key the adapter needs is missing from .env."""


class _Retry(Exception):
    pass


def fetch(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    """One API call. Rate limits, throttling, server and network errors back
    off and retry (call_with_backoff); any other error raises at once."""
    def once() -> httpx.Response:
        try:
            response = client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            raise _Retry(f"{type(exc).__name__}: {exc}") from exc
        throttled = response.status_code == 403 and "x-rejection-reason" in response.headers
        if response.status_code == 429 or response.status_code >= 500 or throttled:
            raise _Retry(f"HTTP {response.status_code} from {urlhost(url)}")
        return response

    response = call_with_backoff(once)
    response.raise_for_status()
    return response


def urlhost(url: str) -> str:
    return httpx.URL(url).host


class Adapter:
    """One free API. A window adapter implements window() (and complete()
    when an item's full text needs another call); a digest adapter sets
    digest = True and implements digest_item()."""
    name = ""
    label = ""
    kind = ""
    search_help = ""
    example = ""
    keys: tuple[str, ...] = ()      # .env names it needs
    digest = False

    def missing_keys(self) -> list[str]:
        from app.settings import get_settings
        settings = get_settings()
        return [k for k in self.keys if not getattr(settings, k.lower(), "")]

    def window(self, query: str, since: date, until: date) -> tuple[list[Item], int]:
        """Every result in the window, at most MAX_RESULTS, in any order, and
        the API's total for the window."""
        raise NotImplementedError

    def complete(self, item: Item) -> Item:
        return item

    def digest_item(self, query: str, last_count: int | None) -> tuple[Item, int]:
        raise NotImplementedError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect(ctx: Context, source: dict, registry: dict) -> Outcome:
    outcome = Outcome()
    adapter = registry.get(source.get("adapter") or "")
    if adapter is None:
        outcome.error = f"unknown adapter {source.get('adapter')!r}"
        return outcome
    missing = adapter.missing_keys()
    if missing:
        outcome.error = f"not configured: set {' and '.join(missing)} in .env"
        return outcome
    searches = [s.strip() for s in source.get("searches") or [] if s.strip()]
    if not searches:
        outcome.error = "no saved searches"
        return outcome

    limit = max(1, ctx.max_pages // len(searches))
    current = get_collection("sources").find_one({"_id": source["source_id"]}, {"progress": 1}) or {}
    progress = {p["search"]: p for p in current.get("progress") or [] if p.get("search")}
    errors: list[str] = []
    for query in searches:
        if ctx.cancelled():
            outcome.error = "run cancelled"
            break
        entry = {"search": query, **{k: v for k, v in progress.get(query, {}).items() if k != "search"}}
        try:
            if adapter.digest:
                _digest(ctx, outcome, source, adapter, query, entry)
            else:
                _window(ctx, outcome, source, adapter, query, entry, limit)
            entry.pop("error", None)
        except InterruptedError:
            outcome.error = "run cancelled"
        except Exception as exc:  # one failing search must not stop the others
            log.warning("%s search %r failed: %s", source["source_id"], query, exc)
            entry["error"] = str(exc)[:300]
            errors.append(f"{query}: {str(exc)[:200]}")
        entry["checked_at"] = _now()
        progress[query] = entry
        # the app's own note — never part of the seeding data, no updated_at
        get_collection("sources").update_one(
            {"_id": source["source_id"]},
            {"$set": {"progress": [progress[q] for q in searches if q in progress]}})
        if outcome.error == "run cancelled":
            break

    if errors and outcome.error is None:
        outcome.error = "; ".join(errors)[:500]
    owed = [(q, progress[q].get("remaining") or 0) for q in searches if q in progress]
    broad = [q for q in searches if q in progress and progress[q].get("too_broad")]
    notes = []
    if sum(n for _, n in owed):
        notes.append(f"{sum(n for _, n in owed)} still to collect ("
                     + ", ".join(f"{q}: {n}" for q, n in owed if n) + ")")
    if broad:
        notes.append("too broad: narrow the search (" + ", ".join(broad) + ")")
    outcome.incomplete_note = "; ".join(notes) or None
    return outcome


def _window(ctx: Context, outcome: Outcome, source: dict, adapter: Adapter,
            query: str, entry: dict, limit: int) -> None:
    today = date.today()
    lookback = int(ctx.settings.get("lookback_days") or 30)
    since = date.fromisoformat(entry["through"]) if entry.get("through") \
        else today - timedelta(days=lookback)
    items, total = adapter.window(query, since, today)
    items = list({i.url: i for i in items}.values())[:MAX_RESULTS]
    known = {d["end_url"] for d in get_collection("documents").find(
        {"end_url": {"$in": [i.url for i in items]}}, {"end_url": 1})}
    new = sorted((i for i in items if i.url not in known),
                 key=lambda i: (i.published_date or "9999", i.url))
    taken = 0
    for item in new[:limit]:
        if ctx.cancelled():
            raise InterruptedError("RUN CANCELLED")
        try:
            item = adapter.complete(item)
        except Exception as exc:  # stays new, so the next run tries it again
            log.warning("%s: could not read %s: %s", source["source_id"], item.url, exc)
            continue
        ctx.visited(outcome, source)
        ctx.save(outcome, source, item.url, item.text, depth=0,
                 meta={"kind": item.kind, "title": item.title,
                       "published_date": item.published_date})
        taken += 1
    entry["remaining"] = len(new) - taken
    entry["too_broad"] = total > MAX_RESULTS
    entry["through"] = (today if entry["remaining"] == 0 and not entry["too_broad"]
                        else since).isoformat()


def _digest(ctx: Context, outcome: Outcome, source: dict, adapter: Adapter,
            query: str, entry: dict) -> None:
    item, count = adapter.digest_item(query, entry.get("last_count"))
    ctx.visited(outcome, source)
    ctx.save(outcome, source, item.url, item.text, depth=0,
             meta={"kind": item.kind, "title": item.title, "published_date": item.published_date})
    entry["last_count"] = count
