"""An assessment's evidence pack reads each page's newest visit, newest first
(findings first when asked), and stops when it's full: the same pack as
reading every visit and cutting at the end (the way it was built before 24 Oct)."""

from agent.analyzer.engine import build_dossier
from app.services.db.mongo import get_collection
from app.services.evidence import page_key
from app.services.runs.store import save_document

SOURCE = {"source_id": "s", "url": "https://example.com"}


def reference(tech_name: str, max_tokens: int, signals_first: bool = False) -> dict:
    """The pack as built before: every visit read, one per page, sorted, then cut."""
    seen: dict[str, dict] = {}
    for d in get_collection("documents").find({"technologies_resolved": tech_name}).sort("scraped_at", -1):
        seen.setdefault(page_key(d), d)
    if signals_first:
        def has_finding(d):
            return not d.get("ignored_by") and any(tech_name in (s.get("technologies_resolved") or [])
                                                  for s in d.get("signals") or [])
        seen = dict(sorted(seen.items(), key=lambda kv: not has_finding(kv[1])))
    kept, pages, cutoff, last, total = [], [], None, None, 0
    for d in seen.values():
        mark = f"[{len(pages) + 1}]" if signals_first else "-"
        lines = [f"{mark} [{d.get('kind') or 'article'}] {d.get('title') or d.get('end_url')}",
                 f"  url: {d.get('end_url')} · source: {d.get('source_id')}"
                 f" · published: {d.get('published_date') or 'n/a'}"
                 f" · extracted: {str(d.get('scraped_at'))[:10]}"]
        if d.get("summary_text"):
            lines.append(f"  summary: {d['summary_text']}")
        if d.get("scout_take"):
            lines.append(f"  scout take: {d['scout_take']}")
        text = "\n".join(lines)
        if total + len(text) > max_tokens * 4:
            kept.append(f"[dossier truncated at ~{max_tokens} tokens — {len(seen) - len(pages)} oldest entries omitted]")
            cutoff = last
            break
        kept.append(text)
        total += len(text)
        pages.append(d["ref_doc_id"] if d.get("is_stub") and d.get("ref_doc_id") else d["_id"])
        last = d.get("scraped_at")
    return {"text": "\n\n".join(kept), "pages": pages, "from": cutoff}


def _world(db):
    db["technologies"].insert_one({"_id": "edge-ai", "name": "edge ai", "aliases": ["edge ai"]})
    for i in range(12):
        finding = [{"signal_id": "launch", "technologies_resolved": ["edge ai"]}] if i % 3 == 0 else []

        def read(url, text, finding=finding, i=i):
            return {"summary": f"summary {i} " * 5, "technologies": ["edge ai"], "scout_take": "t", "signals": finding,
                    "ignored_by": None, "signals_hash": "h", "parts": None, "partial": False}
        save_document("c", "H1", SOURCE, f"https://example.com/{i % 8}", f"text {i}", read, meta={"title": f"Page {i % 8}"})
    save_document("c", "H1", SOURCE, "https://example.com/7", "text 7", None, meta={"title": "Page 7"})  # a stub
    db["documents"].update_many({}, {"$set": {"technologies_resolved": ["edge ai"]}})
    db["technologies"].update_one({}, {"$set": {"page_count": len(db["documents"].distinct("page_key"))}})


def test_the_pack_is_what_reading_every_visit_gave(db):
    _world(db)
    for findings_first in (False, True):
        for budget in (100_000, 60):            # all of it, and cut part-way
            built, ref = build_dossier("edge ai", budget, findings_first), reference("edge ai", budget, findings_first)
            assert (built["text"], built["pages"], built["from"]) == (ref["text"], ref["pages"], ref["from"])
    assert "oldest entries omitted" in build_dossier("edge ai", 60)["text"]
