"""EPO Open Patent Services: patents worldwide (US included), searched with
CQL over titles and abstracts. Free registration, no ID check:
EPO_OPS_KEY and EPO_OPS_SECRET. Fair use: up to 4 GB a week; throttling
answers (403 with X-Rejection-Reason) back off and retry."""

import threading
import time
from datetime import date
from urllib.parse import quote

import httpx

from agent.scout.tools.adapters.base import MAX_RESULTS, Adapter, Item, fetch
from app.settings import get_settings

TOKEN_URL = "https://ops.epo.org/3.2/auth/accesstoken"
SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search/abstract,biblio"
PAGE = 100  # OPS returns at most 100 results per request (X-OPS-Range)


def as_list(value) -> list:
    return value if isinstance(value, list) else ([] if value is None else [value])


def text_of(value) -> str:
    """OPS JSON wraps text as {"$": "..."}; paragraphs may be a list."""
    if isinstance(value, dict):
        return str(value.get("$", "")).strip()
    if isinstance(value, list):
        return " ".join(text_of(v) for v in value).strip()
    return str(value or "").strip()


def _cpc(classification: dict) -> str:
    parts = [text_of(classification.get(k)) for k in ("section", "class", "subclass")]
    group = text_of(classification.get("main-group"))
    sub = text_of(classification.get("subgroup"))
    return "".join(parts) + (f"{group}/{sub}" if group else "")


def parse_document(doc: dict) -> Item:
    """One exchange-document from a search reply."""
    biblio = doc.get("bibliographic-data") or {}
    ids = as_list((biblio.get("publication-reference") or {}).get("document-id"))
    docdb = next((d for d in ids if d.get("@document-id-type") == "docdb"), ids[0] if ids else {})
    country = text_of(docdb.get("country")) or doc.get("@country", "")
    number = text_of(docdb.get("doc-number")) or doc.get("@doc-number", "")
    kind = text_of(docdb.get("kind")) or doc.get("@kind", "")
    raw_date = text_of(docdb.get("date"))
    published = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}" if len(raw_date) == 8 else None

    titles = as_list(biblio.get("invention-title"))
    title = next((text_of(t) for t in titles if isinstance(t, dict) and t.get("@lang") == "en"),
                 text_of(titles[0]) if titles else "") or "(untitled patent)"
    applicants = as_list(((biblio.get("parties") or {}).get("applicants") or {}).get("applicant"))
    names = [text_of((a.get("applicant-name") or {}).get("name")) for a in applicants
             if a.get("@data-format") == "epodoc"] or \
            [text_of((a.get("applicant-name") or {}).get("name")) for a in applicants]
    classes = as_list((biblio.get("patent-classifications") or {}).get("patent-classification"))
    cpc = list(dict.fromkeys(c for c in (_cpc(x) for x in classes) if c))
    abstracts = as_list(doc.get("abstract"))
    abstract = next((text_of(a.get("p")) for a in abstracts if isinstance(a, dict) and a.get("@lang") == "en"),
                    text_of(abstracts[0].get("p")) if abstracts and isinstance(abstracts[0], dict) else "")

    publication = f"{country}{number}{kind}"
    lines = [f"Patent: {title}",
             f"Publication: {publication} · published {published or 'n/a'}"
             + (f" · family {doc['@family-id']}" if doc.get("@family-id") else ""),
             "Applicants: " + (", ".join(n for n in names if n) or "n/a"),
             "CPC classes: " + (", ".join(cpc[:15]) or "n/a"),
             "", "Abstract: " + (abstract or "(no English abstract)")]
    return Item(url=f"https://worldwide.espacenet.com/patent/search?q=pn%3D{quote(publication)}",
                title=title, text="\n".join(lines), published_date=published, kind="patent")


class EpoOps(Adapter):
    name = "epo_ops"
    label = "EPO Open Patent Services"
    kind = "patent"
    keys = ("EPO_OPS_KEY", "EPO_OPS_SECRET")
    search_help = ('CQL over titles and abstracts, e.g. ta="quantum key distribution". '
                   "The publication-date window is added for you.")
    example = 'ta="quantum key distribution"'

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_at = 0.0
        self._lock = threading.Lock()

    def _auth(self, client: httpx.Client, force: bool = False) -> str:
        with self._lock:  # a token lasts ~20 minutes; refresh a little earlier
            if force or not self._token or time.time() - self._token_at > 1100:
                settings = get_settings()
                reply = fetch(client, "POST", TOKEN_URL,
                              auth=(settings.epo_ops_key, settings.epo_ops_secret),
                              data={"grant_type": "client_credentials"})
                self._token, self._token_at = reply.json()["access_token"], time.time()
            return self._token

    def _search(self, client: httpx.Client, cql: str, first: int, last: int) -> dict | None:
        for attempt in (1, 2):
            token = self._auth(client, force=attempt == 2)
            try:
                return fetch(client, "GET", SEARCH_URL, params={"q": cql},
                             headers={"Authorization": f"Bearer {token}",
                                      "Accept": "application/json",
                                      "X-OPS-Range": f"{first}-{last}"}).json()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 404:  # OPS answers "no results" with 404
                    return None
                if status == 401 and attempt == 1:
                    continue  # expired token: refresh once
                if status == 400:
                    raise ValueError(f"EPO rejected the search {cql!r}: {exc.response.text[:200]}")
                raise
        return None

    def window(self, query: str, since: date, until: date) -> tuple[list[Item], int]:
        cql = f'({query}) and pd within "{since:%Y%m%d} {until:%Y%m%d}"'
        items: list[Item] = []
        total, first = 0, 1
        with httpx.Client(timeout=60) as client:
            while first <= MAX_RESULTS:
                last = min(first + PAGE - 1, MAX_RESULTS)
                data = self._search(client, cql, first, last)
                if data is None:
                    break
                search = (data.get("ops:world-patent-data") or {}).get("ops:biblio-search") or {}
                total = int(search.get("@total-result-count") or 0)
                result = search.get("ops:search-result") or {}
                for entry in as_list(result.get("exchange-documents")):
                    for doc in as_list(entry.get("exchange-document", entry)):
                        items.append(parse_document(doc))
                if last >= min(total, MAX_RESULTS):
                    break
                first = last + 1
        return items, total


ADAPTER = EpoOps()
