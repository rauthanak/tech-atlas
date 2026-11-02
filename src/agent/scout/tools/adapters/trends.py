"""Trends: counts per year for a saved search, one page per search per
collection, the digest way the job boards work. They let the radar say how
fast research, citations and patent filings grow (28 Oct review: "growth in
patents and citations over the last two to three years").

OpenAlex trends: papers per year, citations per year to the most-cited of
those papers, papers by authors' country (the countries Tata named first),
and public research grants started per year. EPO patent trends: filings
published per year, and the applicants on a sample of the latest full
year's filings, so a reader sees whether startups or only incumbents file.
The text has no day, so an unchanged count stores a stub."""

from collections import Counter
from datetime import date
from urllib.parse import quote, urlencode

import httpx

from agent.scout.tools.adapters import epo_ops, openalex
from agent.scout.tools.adapters.base import Adapter, Item, fetch
from app.settings import get_settings

YEARS = 3                                # full years before this one
NAMED = ("US", "IL", "CA", "SG", "CN")   # the countries Tata asked about, listed first
CITED = 200                              # the most-cited papers whose citations are summed
SAMPLE = 25                              # filings whose applicants are counted
NONE = "No results for this search in these years."


def years() -> list[int]:
    this = date.today().year
    return list(range(this - YEARS, this + 1))


def series(label: str, counts: dict[int, int]) -> str:
    """"Papers per year: 2023: 1,144 · … · 2026 so far (to October): 2,255"."""
    today = date.today()
    return f"{label}: " + " · ".join(
        f"{y}{f' so far (to {today:%B})' if y == today.year else ''}: {counts.get(y, 0):,}" for y in years())


def trend_text(heading: str, lines: list[str], url: str) -> str:
    return "\n".join([heading, "", *lines, "", f"Source: {url}"])


def _by_year(groups: list[dict]) -> dict[int, int]:
    return {int(g["key"]): g["count"] for g in groups if str(g.get("key")).isdigit()}


class OpenAlexTrends(Adapter):
    name = "openalex_trends"
    label = "OpenAlex: trends"
    kind = "trend"
    digest = True
    search_help = "Plain words, matched in paper titles and abstracts: one page of counts per year for each search."
    example = "quantum networking"
    by_name = True
    find_label = "Research trends"
    find_gives = "one page: papers, citations and grants per year, and where the research comes from"

    def digest_item(self, query: str, last_count: int | None) -> tuple[Item, int]:
        words, first = openalex._words(query), years()[0]
        where = f'title_and_abstract.search:"{words}",from_publication_date:{first}-01-01'
        key = get_settings().openalex_api_key
        with httpx.Client(timeout=30) as client:
            def get(path: str, **params) -> dict:
                return fetch(client, "GET", f"{openalex.BASE}{path}",
                             params={**params, **({"api_key": key} if key else {})}).json()
            papers = _by_year(get("/works", filter=where, group_by="publication_year")["group_by"])
            top = get("/works", filter=where, sort="cited_by_count:desc", per_page=CITED, select="counts_by_year")["results"]
            places = get("/works", filter=where, group_by="authorships.institutions.country_code")["group_by"]
            grants = _by_year(get("/awards", filter=f'default.search:"{words}",start_year:>{first - 1}',
                                  group_by="start_year")["group_by"])
        cited = Counter()
        for work in top:
            for c in work.get("counts_by_year") or []:
                cited[c["year"]] += c["cited_by_count"]
        lines = [NONE] if not papers and not grants else [
            series("Papers per year", papers),
            series(f"Citations per year to the {min(CITED, len(top))} most-cited of these papers", cited),
            f"Papers by authors' country, {first}–{years()[-1]}: " + _countries(places),
            series("Public research grants started per year (not venture funding)", grants),
        ]
        url = f"{openalex.BASE}/works?" + urlencode({"filter": where, "group_by": "publication_year"})
        heading = f'Research activity for "{words}" (OpenAlex, paper titles and abstracts)'
        return Item(url=url, title=f"Research trend: {words}", text=trend_text(heading, lines, url),
                    published_date=None, kind=self.kind), papers.get(years()[-1], 0)


def _countries(groups: list[dict]) -> str:
    """The countries Tata named first (0 when none), then the next five by count."""
    counts = {str(g["key"]).rsplit("/", 1)[-1]: (g.get("key_display_name") or g["key"], g["count"]) for g in groups}
    named = [f"{counts.get(c, (c, 0))[0]} {counts.get(c, (c, 0))[1]:,}" for c in NAMED]
    others = sorted((v for k, v in counts.items() if k not in NAMED and len(k) == 2), key=lambda v: -v[1])[:5]
    return " · ".join(named + [f"{n} {c:,}" for n, c in others])


class EpoTrends(epo_ops.EpoOps):
    name = "epo_trends"
    label = "EPO: patent trends"
    kind = "patent-trend"
    digest = True
    search_help = 'CQL over titles and abstracts, e.g. ta="quantum key distribution": one page of filings per year for each search.'
    find_label = "Patent trends"
    find_gives = "one page: patent filings per year, and who files them"

    def digest_item(self, query: str, last_count: int | None) -> tuple[Item, int]:
        counts, applicants, latest = {}, Counter(), years()[-2]
        with httpx.Client(timeout=60) as client:
            for y in years():
                total, docs = epo_ops.documents(self._search(client, f'({query}) and pd within "{y}0101 {y}1231"', 1, SAMPLE))
                counts[y] = total
                if y == latest:
                    applicants.update(n for d in docs for n in set(epo_ops.applicants(d)))
        lines = [NONE] if not any(counts.values()) else [
            series("Patent filings published per year", counts),
            f"Applicants on {min(SAMPLE, counts[latest])} of {latest}'s filings: "
            + (", ".join(f"{n} ({c})" if c > 1 else n for n, c in applicants.most_common()) or "none named"),
        ]
        url = f"https://worldwide.espacenet.com/patent/search?q={quote(query)}"
        heading = f"Patent activity for {query} (EPO Open Patent Services, titles and abstracts)"
        return Item(url=url, title=f"Patent trend: {query}", text=trend_text(heading, lines, url),
                    published_date=None, kind=self.kind), counts[years()[-1]]


OPENALEX = OpenAlexTrends()
EPO = EpoTrends()
