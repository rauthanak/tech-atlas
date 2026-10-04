"""Company job boards on Greenhouse, Lever and Ashby — public posting APIs,
no key. A single posting is a job ad (set aside by design); the signal is
how many roles a company has open and how that changes, so each saved
search yields one digest per run, against the last run's count."""

from collections import Counter
from urllib.parse import quote

import httpx

from agent.scout.tools.adapters.base import Adapter, Item, fetch

PLATFORMS = {
    # platform: (API URL, public board page)
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true",
                   "https://job-boards.greenhouse.io/{board}"),
    "lever": ("https://api.lever.co/v0/postings/{board}?mode=json",
              "https://jobs.lever.co/{board}"),
    "ashby": ("https://api.ashbyhq.com/posting-api/job-board/{board}",
              "https://jobs.ashbyhq.com/{board}"),
}


def _roles(platform: str, data) -> list[tuple[str, str]]:
    """(title, department) for every open role."""
    if platform == "greenhouse":
        return [(j.get("title") or "", ((j.get("departments") or [{}])[0] or {}).get("name") or "")
                for j in data.get("jobs") or []]
    if platform == "lever":
        return [(j.get("text") or "", (j.get("categories") or {}).get("department")
                 or (j.get("categories") or {}).get("team") or "") for j in data or []]
    return [(j.get("title") or "", j.get("department") or j.get("team") or "")
            for j in data.get("jobs") or []]


def digest_text(heading: str, roles: list[tuple[str, str]], last_count: int | None) -> str:
    """Stable text (no dates), so an unchanged board stores a stub."""
    count = len(roles)
    change = ("first count" if last_count is None
              else f"{last_count} at the last run, {count - last_count:+d}")
    lines = [f"{heading}: {count} open roles now ({change})."]
    departments = Counter(d or "Unspecified" for _, d in roles)
    if departments:
        lines += ["", "Open roles by department:"]
        lines += [f"- {d}: {n}" for d, n in sorted(departments.items(), key=lambda x: (-x[1], x[0]))]
    titles = Counter(t.strip() for t, _ in roles if t.strip())
    if titles:
        lines += ["", "All open role titles:"]
        lines += [f"- {t}" + (f" ({n})" if n > 1 else "") for t, n in sorted(titles.items())]
    return "\n".join(lines)


class JobBoards(Adapter):
    name = "job_boards"
    label = "Company job boards"
    kind = "jobs-digest"
    digest = True
    search_help = "greenhouse:<board>, lever:<company> or ashby:<board> — the name in the board's web address."
    example = "greenhouse:cloudflare"

    def digest_item(self, query: str, last_count: int | None) -> tuple[Item, int]:
        platform, _, board = query.partition(":")
        platform, board = platform.strip().lower(), board.strip()
        if platform not in PLATFORMS or not board:
            raise ValueError(f"{query!r}: use greenhouse:<board>, lever:<company> or ashby:<board>")
        api, page = PLATFORMS[platform]
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            data = fetch(client, "GET", api.format(board=quote(board))).json()
        roles = _roles(platform, data)
        heading = f"Hiring at {board} ({platform.title()} job board)"
        return Item(url=page.format(board=quote(board)), title=f"Open roles: {board}",
                    text=digest_text(heading, roles, last_count), published_date=None,
                    kind=self.kind), len(roles)


ADAPTER = JobBoards()
