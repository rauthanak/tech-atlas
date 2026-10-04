"""USAJOBS: open US federal job postings for a keyword — official public
hiring data. Free key: USAJOBS_API_KEY, used with CONTACT_EMAIL (the email
the key was registered with). One digest per keyword per run."""

from urllib.parse import quote

import httpx

from agent.scout.tools.adapters.base import Adapter, Item, fetch
from agent.scout.tools.adapters.job_boards import digest_text
from app.settings import get_settings

SEARCH_URL = "https://data.usajobs.gov/api/search"
DAYS = 60  # postings from the last 60 days, the API's maximum


class UsaJobs(Adapter):
    name = "usajobs"
    label = "USAJOBS"
    kind = "jobs-digest"
    digest = True
    keys = ("USAJOBS_API_KEY", "CONTACT_EMAIL")
    search_help = "A keyword or phrase, e.g. post-quantum cryptography"
    example = "post-quantum cryptography"

    def digest_item(self, query: str, last_count: int | None) -> tuple[Item, int]:
        settings = get_settings()
        headers = {"Host": "data.usajobs.gov", "User-Agent": settings.contact_email,
                   "Authorization-Key": settings.usajobs_api_key}
        with httpx.Client(timeout=30) as client:
            data = fetch(client, "GET", SEARCH_URL, headers=headers,
                         params={"Keyword": query, "DatePosted": DAYS, "ResultsPerPage": 500}).json()
        result = data.get("SearchResult") or {}
        postings = [i.get("MatchedObjectDescriptor") or {} for i in result.get("SearchResultItems") or []]
        roles = [(p.get("PositionTitle") or "", p.get("OrganizationName") or p.get("DepartmentName") or "")
                 for p in postings]
        count = int(result.get("SearchResultCountAll") or len(roles))
        text = digest_text(f"US federal job postings matching '{query}' (last {DAYS} days)",
                           roles, last_count).replace("Open roles by department:", "Postings by agency:")
        if count > len(roles):
            text += f"\n\n(The titles above cover the first {len(roles)} of {count} postings.)"
        return Item(url=f"https://www.usajobs.gov/Search/Results?k={quote(query)}",
                    title=f"Federal postings: {query}", text=text, published_date=None,
                    kind=self.kind), count


ADAPTER = UsaJobs()
