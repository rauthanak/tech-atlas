"""Scout tool: collect_source(source_id). Looks the source up by id (two
sources may share a URL) and collects it by its access type: a website is
crawled (crawl.py); a data source runs its saved searches through its
adapter (adapters/). Either way every item takes the same path — stored,
summarized with the run's signal list, counted — so nothing downstream
changes."""

import logging

from agent.scout.tools import adapters
from agent.scout.tools.context import Context, Outcome
from agent.scout.tools.crawl import crawl
from app.services.db.mongo import get_collection
from app.services.runs import store
from app.services.signals import snapshot as run_snapshot

log = logging.getLogger(__name__)

SNAPSHOT_FIELDS = ("signal_list", "signals_hash", "crawl_settings")


def recorded_snapshot(run_id: str) -> dict:
    """The snapshot the run recorded at its start (the current one if it has none)."""
    run = get_collection("runs").find_one({"_id": run_id}, dict.fromkeys(SNAPSHOT_FIELDS, 1)) or {}
    return ({k: run[k] for k in SNAPSHOT_FIELDS} if all(k in run for k in SNAPSHOT_FIELDS)
            else run_snapshot.build())


def page_budget(snapshot: dict, override: int | None = None) -> int:
    """Pages per source: a run's own max_pages_per_source wins over Crawl settings."""
    return override or int(snapshot["crawl_settings"]["pages_per_source"])


def make_collect_tool(run_id: str, category: str, sources: list[dict], llm,
                      max_pages_override: int | None = None):
    """Build the collect_source tool bound to this scout's run and sources.
    The run's snapshot is read once, so edits made mid-run apply next run."""
    by_id = {s["source_id"]: s for s in sources}
    snapshot = recorded_snapshot(run_id)
    ctx = Context(run_id, category, llm, snapshot, page_budget(snapshot, max_pages_override))
    collected: set[str] = set()

    def collect_source(source_id: str) -> str:
        """Collect one assigned source — pass its exact source_id. A website is
        crawled within the page budget; a data source runs its saved searches.
        Every technology update found is stored with its reference URL,
        extracted text and summary. Returns a one-line report."""
        source = by_id.get(str(source_id).strip())
        if source is None:
            return (f"error: unknown source_id {source_id!r} — use one of: "
                    + ", ".join(sorted(by_id)))
        if ctx.cancelled():
            return "RUN CANCELLED"
        if source["source_id"] in collected:
            return f"{source['name']}: already collected in this run"
        if source.get("access") == "none":
            return f"error: {source['source_id']} is never collected ({source.get('note') or 'access: none'})"
        collected.add(source["source_id"])
        store.start_source(run_id, category, source)
        try:
            outcome = (adapters.collect(ctx, source) if source.get("access") == "query"
                       else crawl(ctx, source))
        except Exception as exc:  # a tool must never raise; the run carries on
            log.exception("collecting %s failed", source["source_id"])
            outcome = Outcome(error=str(exc)[:300])
        store.finish_source(run_id, source["source_id"], outcome.pages, outcome.docs,
                            outcome.new_docs, outcome.error, outcome.incomplete_note)
        if outcome.error == "run cancelled":
            return "RUN CANCELLED"
        report = outcome.report(source["name"])
        log.info(report)
        return report

    return collect_source
