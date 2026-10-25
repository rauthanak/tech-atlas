"""SEC EDGAR: company filings — 8-K current reports with their EX-99
press-release exhibits, 10-Q and 10-K reports, and Form D fundraises. Free;
SEC requires a contact email in the User-Agent (CONTACT_EMAIL) and at most
10 requests a second."""

import time
from datetime import date

import httpx
from bs4 import BeautifulSoup

from agent.scout.tools.adapters.base import Adapter, Item, fetch
from agent.scout.tools.crawl import readable
from app.settings import get_settings

FORMS = ("8-K", "10-Q", "10-K", "D")
PAUSE = 0.15  # seconds between requests (SEC allows 10 a second)


def _client() -> httpx.Client:
    return httpx.Client(timeout=30, follow_redirects=True,
                        headers={"User-Agent": f"TechAtlas {get_settings().contact_email}"})


def _text(html: str) -> str:
    return (readable(html) or BeautifulSoup(html, "html.parser").get_text(" ")).strip()


class SecEdgar(Adapter):
    name = "sec_edgar"
    label = "SEC EDGAR filings"
    kind = "filing"
    keys = ("CONTACT_EMAIL",)
    search_help = "A company's 10-digit CIK, then its name: 0000732712 Verizon"
    example = "0000732712 Verizon"

    def window(self, query: str, since: date, until: date) -> tuple[list[Item], int]:
        cik = query.split()[0].strip().zfill(10)
        with _client() as client:
            data = fetch(client, "GET", f"https://data.sec.gov/submissions/CIK{cik}.json").json()
        company = data.get("name") or " ".join(query.split()[1:]) or cik
        recent = (data.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        column = lambda key: recent.get(key) or [""] * len(forms)  # noqa: E731
        dates, accessions, primaries, item_codes = (column("filingDate"), column("accessionNumber"),
                                                     column("primaryDocument"), column("items"))
        items: list[Item] = []
        for i, form in enumerate(forms):
            filed = dates[i]
            if form not in FORMS or not (since.isoformat() <= filed <= until.isoformat()):
                continue
            accession = accessions[i]
            folder = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
            items.append(Item(
                url=f"{folder}/{accession}-index.htm",
                title=f"{company}: Form {form} filed {filed}",
                text="", published_date=filed, kind=self.kind,
                extra={"company": company, "form": form, "items": item_codes[i],
                       "primary": f"{folder}/{primaries[i]}" if primaries[i] else None}))
        return items, len(items)

    def complete(self, item: Item) -> Item:
        extra = item.extra
        header = [f"Company: {extra['company']}", f"Filing: Form {extra['form']}, filed {item.published_date}"]
        if extra.get("items"):
            header.append(f"8-K items: {extra['items']}")
        sections = ["\n".join(header)]
        with _client() as client:
            if extra.get("primary"):
                time.sleep(PAUSE)
                sections.append(_text(fetch(client, "GET", extra["primary"]).text))
            if extra["form"] == "8-K":  # the press release lives in the EX-99 exhibit(s)
                time.sleep(PAUSE)
                index = BeautifulSoup(fetch(client, "GET", item.url).text, "html.parser")
                for row in index.find_all("tr"):
                    cells = row.find_all("td")
                    link = cells[2].find("a") if len(cells) >= 4 else None
                    if link and cells[3].get_text(strip=True).upper().startswith("EX-99"):
                        href = link["href"].replace("/ix?doc=", "")
                        time.sleep(PAUSE)
                        exhibit = fetch(client, "GET", f"https://www.sec.gov{href}"
                                        if href.startswith("/") else href).text
                        sections.append(f"Exhibit {cells[3].get_text(strip=True)}:\n{_text(exhibit)}")
        item.text = "\n\n".join(s for s in sections if s)
        return item


ADAPTER = SecEdgar()
