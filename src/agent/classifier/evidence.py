"""The evidence a Classify call reads about one technology: bounded and
numbered, so every answer can point at the pages it rests on.

The newest visit of each page; pages with a kept finding about this
technology first, then the newest; at most `cap` pages. Each page reads
"[n] source (kind of source) · date · title", then its summary, then the
word-for-word quotes of its findings about this technology. FACTS give the
whole picture: all its pages, independent sources, and the kinds of source.
An incremental call reads only the pages its last classification didn't."""

from app.services.db.mongo import get_collection
from app.services.websearch import source_of
from app.services.evidence import page_key

FIELDS ={"end_url": 1, "page_key": 1, "title": 1, "source_id": 1, "source_name": 1, "scraped_at": 1, "published_date": 1,
          "summary_text": 1, "signals": 1, "is_stub": 1, "ref_doc_id": 1, "ignored_by": 1, "kind": 1}


def version(d: dict) -> str:
    return d["ref_doc_id"] if d.get("is_stub") and d.get("ref_doc_id") else d["_id"]


def _pages(name: str) -> tuple[list[dict], list[str]]:
    """The newest visit of each page, and every version found (older visits too)."""
    latest: dict[str, dict] = {}
    versions: set[str] = set()
    for d in get_collection("documents").find({"technologies_resolved": name, "ignored_by": None}, FIELDS) \
            .sort("scraped_at", -1):
        latest.setdefault(page_key(d), d)
        versions.add(version(d))
    return list(latest.values()), list(versions)


def _findings(d: dict, name: str) -> list[dict]:
    return [s for s in d.get("signals") or [] if name in (s.get("technologies_resolved") or [])]


def pack(name: str, cap: int, seen: set[str] | None = None) -> dict:
    """{text, pages (the doc ids, numbered from 1), facts, read, of, sources,
    known (every page version it has now, read or not, older visits of a page
    too)}. `seen`: the page versions known at its last classification; only
    others are sent."""
    pages, known = _pages(name)
    stubs = [d["ref_doc_id"] for d in pages if d.get("is_stub") and d.get("ref_doc_id")]
    originals = {d["_id"]: d for d in get_collection("documents").find({"_id": {"$in": stubs}}, FIELDS)} if stubs else {}
    pages = [originals.get(d.get("ref_doc_id"), d) if d.get("is_stub") else d for d in pages]
    sources = {source_of(d) for d in pages}  # a page found by web search counts as its own site
    kinds = {s["_id"]: (s.get("cluster") or "").replace("_", " ") for s in get_collection("sources").find(
        {"_id": {"$in": list({d["source_id"] for d in pages if d.get("source_id")})}}, {"cluster": 1})}
    fresh = [d for d in pages if not seen or version(d) not in seen]
    fresh.sort(key=lambda d: (not _findings(d, name),))  # stable: findings first, each group newest first
    chosen = fresh[:cap]
    blocks = []
    for n, d in enumerate(chosen, 1):
        when = d.get("published_date") or str(d.get("scraped_at") or "")[:10]
        head = (f"[{n}] {d.get('source_name') or d.get('source_id')} ({kinds.get(d.get('source_id')) or 'source'})"
                f" · {when} · {d.get('title') or d.get('end_url')}")
        lines = [head]
        if d.get("summary_text"):
            lines.append(d["summary_text"])
        for s in _findings(d, name):
            if s.get("quote"):
                lines.append(f'Finding, {s.get("label") or s.get("name")}: "{s["quote"]}"')
        blocks.append("\n".join(lines))
    kind_counts: dict[str, int] = {}
    for d in pages:
        k = kinds.get(d.get("source_id")) or "other"
        kind_counts[k] = kind_counts.get(k, 0) + 1
    facts = (f"{len(pages)} pages about it in all, from {len(sources)} independent source(s); "
             f"kinds of source: " + ", ".join(f"{k} {v}" for k, v in sorted(kind_counts.items(), key=lambda x: -x[1]))
             + (f". {len(chosen)} of them are numbered below" + (" (those not read before)" if seen else "") + "."))
    return {"text": "\n\n".join(blocks), "pages": [version(d) for d in chosen], "facts": facts,
            "read": len(chosen), "of": len(pages), "sources": len(sources), "known": known}
