"""A figure's own words, found on its page (5 Nov review): a market size, a
growth rate or a use case's size is kept only when the words that state it
are on the page it cites, in the page's saved text or, when that is no longer
kept, its summary. Where the words give a US-dollar amount, it must also
match the figure the band is worked out from, so a slip in converting
"$312 million" to billions is caught too."""

import re

from app.services.db.mongo import get_collection
from app.services.pages import NEWEST, link_key

MOST = 300  # characters: words that state a figure, not a paragraph
SIGNS = str.maketrans({" ": " ", "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
USD = re.compile(r"(?:us\s?\$|usd\s?|\$)\s?(\d[\d,]*(?:\.\d+)?)\s*(trillion|billion|million|tn|bn|mn|t|b|m)?\b", re.I)
SCALE = {"t": 1000, "tn": 1000, "trillion": 1000, "b": 1, "bn": 1, "billion": 1, "m": 0.001, "mn": 0.001, "million": 0.001}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").translate(SIGNS)).strip().lower()


def _text(doc: dict | None) -> str:
    if not doc:
        return ""
    full = (get_collection("page_texts").find_one({"_id": doc["_id"]}, {"text": 1}) or {}).get("text") if doc.get("has_text") else None
    return f"{full or ''} {doc.get('summary_text') or ''}"


def on_page(quote, url: str | None = None, doc_id: str | None = None) -> bool:
    """Whether these words are on the page (by its visit id, else its link's newest visit)."""
    q = norm(quote) if isinstance(quote, str) else ""
    if not q or len(q) > MOST or not re.search(r"\d", q):
        return False
    docs = get_collection("documents")
    fields = {"has_text": 1, "summary_text": 1}
    if doc_id:
        doc = docs.find_one({"_id": doc_id}, fields)
    elif url:
        doc = docs.find_one({"page_key": link_key(url), **NEWEST}, fields) or \
            docs.find_one({"$or": [{"end_url": url}, {"source_url": url}]}, fields, sort=[("scraped_at", -1)])
    else:
        doc = None
    return q in norm(_text(doc))


def usd_bn(quote: str) -> list[float]:
    """The US-dollar amounts the words give with a scale ("$312.4 million"), in
    billions. One without a scale ("$5 to 10 billion"'s 5) is left out."""
    return [float(m.group(1).replace(",", "")) * SCALE[m.group(2).lower()] for m in USD.finditer(quote or "") if m.group(2)]


def matches(amount_usd_bn: float, quote: str) -> bool:
    """Whether the words agree with the figure, within 5% (true when they give no dollar amount)."""
    said = usd_bn(quote)
    return not said or any(abs(v - amount_usd_bn) <= 0.05 * amount_usd_bn for v in said)
