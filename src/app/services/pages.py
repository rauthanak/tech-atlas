"""Which page a visit is of (24 Oct scale plan, spec §3 and §4).

A page is known by its link, tidied: the host without "www.", no "#…" part,
no trailing "/", no tracking parameters, the rest in order. A visit whose
tidied link is new still joins an earlier page with the same site, title and
text: the same page under another link (arXiv's "v1", "?context=cs"). The
title alone isn't enough: many different pages share one ("Press Releases").

Each page's newest visit carries `latest` (older ones `latest: False`) and
`visits`, how many times the page was collected, so lists and counts read one
visit per page."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit

from app.services.db.mongo import get_collection

TRACKING = re.compile(r"^(utm_.*|share|ref|fbclid|gclid|mc_cid|mc_eid)$", re.I)
NEWEST = {"latest": {"$ne": False}}  # a page's newest visit


def link_key(url: str) -> str:
    """The link, tidied. One that isn't a web address (an uploaded file) stays as it is."""
    s = urlsplit(url)
    if not s.netloc:
        return url
    query = urlencode(sorted((k, v) for k, v in parse_qsl(s.query, keep_blank_values=True) if not TRACKING.match(k)))
    return s.netloc.lower().removeprefix("www.") + s.path.rstrip("/") + (f"?{query}" if query else "")


def _site(key: str) -> str:
    return re.split(r"[/?]", key, maxsplit=1)[0]


def key_for(end_url: str, title: str | None, content_hash: str) -> str:
    """The page a visit is of: its tidied link, or, when that link is new, an
    earlier page on the same site with the same title and text."""
    key = link_key(end_url)
    docs = get_collection("documents")
    if title and not docs.find_one({"page_key": key}, {"_id": 1}):
        for d in docs.find({"content_hash": content_hash, "title": title, "is_stub": False}, {"page_key": 1}):
            if d.get("page_key") and _site(d["page_key"]) == _site(key):
                return d["page_key"]
    return key


def visits(key: str) -> int:
    """How many times this page was collected so far."""
    return get_collection("documents").count_documents({"page_key": key})


def mark_newest(doc: dict) -> None:
    """After `doc` (stored with `latest: True`): older visits of its page aren't the newest any more."""
    get_collection("documents").update_many(
        {"page_key": doc["page_key"], "scraped_at": {"$lt": doc["scraped_at"]}, **NEWEST},
        {"$set": {"latest": False}})
