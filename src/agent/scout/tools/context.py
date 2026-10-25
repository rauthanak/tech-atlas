"""What collecting one source needs, shared by the crawler and the data
source adapters: the run, its snapshot (signal list, crawl settings), the
model, the page budget — and the one path every item takes: stored,
summarized with the run's signal list, counted."""

from dataclasses import dataclass, field

from agent.scout.tools.summarize import summarize_page
from app.services.llm.context import with_context
from app.services.runs import store

MAX_EXAMPLES = 5  # addresses kept per reason a page or link was skipped

@dataclass
class Outcome:
    pages: int = 0          # items visited (pages fetched, results read)
    docs: int = 0
    new_docs: int = 0
    error: str | None = None
    incomplete_note: str | None = None  # what was left for lack of budget
    skipped: dict = field(default_factory=dict)  # (page|link, reason) -> {what, reason, count, examples}

    def skip(self, url: str, reason: str, link: bool = False) -> None:
        """A page or link left out because it couldn't be read: counted by
        reason, with a few examples, so the source carries on and says why."""
        what = "link" if link else "page"
        entry = self.skipped.setdefault((what, reason), {"what": what, "reason": reason, "count": 0, "examples": []})
        entry["count"] += 1
        if len(entry["examples"]) < MAX_EXAMPLES:
            entry["examples"].append(url[:300])

    def skipped_list(self) -> list[dict]:
        return sorted(self.skipped.values(), key=lambda e: -e["count"])

    def report(self, name: str) -> str:
        skipped = "; ".join(f"{e['count']} {e['what']}s skipped: {e['reason']}" for e in self.skipped_list())
        return (f"{name}: {self.pages} items visited, {self.docs} documents ({self.new_docs} new)"
                + (f", incomplete: {self.incomplete_note}" if self.incomplete_note else "")
                + (f", {skipped}" if skipped else "")
                + (f", error: {self.error}" if self.error else ""))


@dataclass
class Context:
    run_id: str
    category: str
    llm: object
    snapshot: dict          # signal_list, signals_hash, crawl_settings
    max_pages: int

    @property
    def settings(self) -> dict:
        return self.snapshot.get("crawl_settings") or {}

    def cancelled(self) -> bool:
        return store.cancelled(self.run_id)

    def summarize(self, url: str, text: str) -> dict:
        with with_context(run_kind="collection", run_id=self.run_id):
            return summarize_page(self.llm, url, text, self.snapshot, self.cancelled)

    def visited(self, outcome: Outcome, source: dict) -> None:
        outcome.pages += 1
        store.bump_source(self.run_id, source["source_id"], pages=1)

    def save(self, outcome: Outcome, source: dict, url: str, text: str,
             depth: int = 0, meta: dict | None = None) -> dict | None:
        """Store one item; returns its analysis when it is new or changed."""
        analysis = store.save_document(self.run_id, self.category, source, url, text,
                                       self.summarize, depth=depth, meta=meta)
        outcome.docs += 1
        outcome.new_docs += int(analysis is not None)
        store.bump_source(self.run_id, source["source_id"], docs=1,
                          new_docs=int(analysis is not None), **store.signal_counts(analysis))
        return analysis
