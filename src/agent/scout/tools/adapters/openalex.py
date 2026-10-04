"""OpenAlex: research papers (works) and research grants (awards), from one
free API. OPENALEX_API_KEY is optional but recommended: without it the
daily budget is a tenth."""

from datetime import date

import httpx

from agent.scout.tools.adapters.base import MAX_RESULTS, Adapter, Item, fetch
from app.settings import get_settings

BASE = "https://api.openalex.org"
PER_PAGE = 200


def _words(query: str) -> str:
    """Plain words for a filter value (commas and quotes would break it)."""
    return " ".join(query.replace(",", " ").replace('"', " ").split())


def _pages(path: str, params: dict) -> tuple[list[dict], int]:
    """Every result for the filter, cursor-paged, at most MAX_RESULTS, and
    OpenAlex's count."""
    key = get_settings().openalex_api_key
    rows: list[dict] = []
    total, cursor = 0, "*"
    with httpx.Client(timeout=30) as client:
        while cursor and len(rows) < MAX_RESULTS:
            query = {**params, "per_page": PER_PAGE, "cursor": cursor, **({"api_key": key} if key else {})}
            data = fetch(client, "GET", f"{BASE}{path}", params=query).json()
            meta = data.get("meta") or {}
            total = meta.get("count") or total
            batch = data.get("results") or []
            rows += batch
            cursor = meta.get("next_cursor") if batch else None
    return rows[:MAX_RESULTS], total


def _abstract(index: dict | None) -> str:
    if not index:
        return ""
    words = sorted((pos, word) for word, positions in index.items() for pos in positions)
    return " ".join(word for _, word in words)


class Works(Adapter):
    name = "openalex_works"
    label = "OpenAlex: papers"
    kind = "paper"
    search_help = "Plain words, matched in paper titles and abstracts."
    example = "quantum networking"

    def window(self, query: str, since: date, until: date) -> tuple[list[Item], int]:
        rows, total = _pages("/works", {
            "filter": f'title_and_abstract.search:"{_words(query)}",'
                      f"from_publication_date:{since.isoformat()},to_publication_date:{until.isoformat()}",
            "sort": "publication_date:asc",
            "select": "id,doi,display_name,publication_date,primary_location,"
                      "authorships,abstract_inverted_index,type",
        })
        return [self._item(r) for r in rows], total

    def _item(self, work: dict) -> Item:
        venue = ((work.get("primary_location") or {}).get("source") or {}).get("display_name")
        authors = []
        for a in (work.get("authorships") or [])[:12]:
            name = (a.get("author") or {}).get("display_name") or a.get("raw_author_name")
            places = ", ".join(i.get("display_name") for i in a.get("institutions") or []
                               if i.get("display_name"))
            if name:
                authors.append(f"{name} ({places})" if places else name)
        title = work.get("display_name") or "(untitled)"
        lines = [f"Paper: {title}",
                 f"Type: {work.get('type') or 'n/a'} · Published: {work.get('publication_date') or 'n/a'}"
                 + (f" · Venue: {venue}" if venue else ""),
                 "Authors: " + ("; ".join(authors) if authors else "n/a")]
        abstract = _abstract(work.get("abstract_inverted_index"))
        lines += ["", "Abstract: " + (abstract or "(no abstract available)")]
        return Item(url=work.get("doi") or work["id"], title=title, text="\n".join(lines),
                    published_date=work.get("publication_date"), kind=self.kind)


class Awards(Adapter):
    name = "openalex_awards"
    label = "OpenAlex: grants"
    kind = "grant"
    search_help = "Plain words, matched in grant titles and descriptions."
    example = "quantum key distribution"

    def window(self, query: str, since: date, until: date) -> tuple[list[Item], int]:
        # there is no start-date filter: read from the year before, then window by start_date
        rows, total = _pages("/awards", {
            "filter": f'default.search:"{_words(query)}",start_year:>{since.year - 1}',
            "sort": "start_year:asc",
        })
        items = [self._item(r) for r in rows
                 if r.get("start_date") and since.isoformat() <= r["start_date"] <= until.isoformat()]
        return items, (total if total > MAX_RESULTS else len(items))

    def _item(self, award: dict) -> Item:
        funder = (award.get("funder") or {}).get("display_name") or "n/a"
        lead = award.get("lead_investigator") or {}
        who = " ".join(x for x in (lead.get("given_name"), lead.get("family_name")) if x)
        where = ", ".join(x for x in ((lead.get("affiliation") or {}).get("name"),
                                      (lead.get("affiliation") or {}).get("country")) if x)
        amount = award.get("amount")
        money = f"{amount:,.0f} {award.get('currency') or ''}".strip() if amount else "not disclosed"
        title = award.get("display_name") or "(untitled grant)"
        lines = [f"Grant: {title}",
                 f"Funder: {funder}" + (f" · Scheme: {award['funder_scheme']}" if award.get("funder_scheme") else "")
                 + (f" · Award ID: {award['funder_award_id']}" if award.get("funder_award_id") else ""),
                 f"Amount: {money} · Start: {award.get('start_date') or 'n/a'}"
                 f" · End: {award.get('end_date') or 'n/a'}",
                 "Lead investigator: " + (f"{who} ({where})" if who and where else who or "n/a"),
                 "", "Description: " + (award.get("description") or "(no description)")]
        if award.get("landing_page_url"):
            lines.append(f"Funder page: {award['landing_page_url']}")
        return Item(url=award["id"], title=title, text="\n".join(lines),
                    published_date=award.get("start_date"), kind=self.kind)


WORKS = Works()
AWARDS = Awards()
