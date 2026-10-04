"""Adapter parsing, offline: the documented response shapes of the APIs that
need keys (EPO, SEC, USAJOBS), and the job-board digest's stability."""

from datetime import date

from agent.scout.tools.adapters import epo_ops, job_boards, sec_edgar, usajobs
from agent.scout.tools.adapters.job_boards import digest_text

EPO_DOC = {
    "@country": "EP", "@doc-number": "4512345", "@kind": "A1", "@family-id": "88001234",
    "bibliographic-data": {
        "publication-reference": {"document-id": [
            {"@document-id-type": "docdb", "country": {"$": "EP"}, "doc-number": {"$": "4512345"},
             "kind": {"$": "A1"}, "date": {"$": "20260916"}},
            {"@document-id-type": "epodoc", "doc-number": {"$": "EP4512345"}}]},
        "invention-title": [{"@lang": "de", "$": "Quantenschlüssel"},
                            {"@lang": "en", "$": "Quantum key distribution over fibre"}],
        "parties": {"applicants": {"applicant": [
            {"@data-format": "epodoc", "applicant-name": {"name": {"$": "TOSHIBA CORP [JP]"}}},
            {"@data-format": "original", "applicant-name": {"name": {"$": "Toshiba Corporation"}}}]}},
        "patent-classifications": {"patent-classification": {
            "section": {"$": "H"}, "class": {"$": "04"}, "subclass": {"$": "L"},
            "main-group": {"$": "9"}, "subgroup": {"$": "0852"}}},
    },
    "abstract": {"@lang": "en", "p": {"$": "A method for distributing keys..."}},
}


def test_epo_document_parsing():
    item = epo_ops.parse_document(EPO_DOC)
    assert item.title == "Quantum key distribution over fibre"
    assert item.published_date == "2026-09-16" and item.kind == "patent"
    assert item.url.endswith("pn%3DEP4512345A1")
    assert "TOSHIBA CORP [JP]" in item.text and "Toshiba Corporation" not in item.text
    assert "H04L9/0852" in item.text and "A method for distributing keys" in item.text


def test_epo_window_pages_and_totals(monkeypatch):
    calls = []

    def fake_search(self, client, cql, first, last):
        calls.append((cql, first, last))
        docs = [{"exchange-document": dict(EPO_DOC, **{"@doc-number": str(n)})} for n in range(first, min(last, 150) + 1)]
        return {"ops:world-patent-data": {"ops:biblio-search": {
            "@total-result-count": "150",
            "ops:search-result": {"exchange-documents": docs}}}}

    monkeypatch.setattr(epo_ops.EpoOps, "_search", fake_search)
    items, total = epo_ops.EpoOps().window('ta="qkd"', date(2026, 9, 1), date(2026, 10, 3))
    assert total == 150 and len(items) == 150
    assert [c[1:] for c in calls] == [(1, 100), (101, 200)]
    assert calls[0][0] == '(ta="qkd") and pd within "20260901 20261003"'


class FakeResponse:
    def __init__(self, data=None, text=""):
        self._data, self.text = data, text

    def json(self):
        return self._data


def test_sec_window_filters_forms_and_dates(monkeypatch):
    submissions = {"name": "VERIZON COMMUNICATIONS INC", "filings": {"recent": {
        "form": ["8-K", "4", "10-Q", "8-K", "D"],
        "filingDate": ["2026-09-30", "2026-09-29", "2026-08-01", "2026-09-10", "2026-09-12"],
        "accessionNumber": ["0000732712-26-000101", "x", "0000732712-26-000090",
                            "0000732712-26-000095", "0000732712-26-000096"],
        "primaryDocument": ["vz-8k.htm", "x.xml", "vz-10q.htm", "vz-8k2.htm", "primary_doc.xml"],
        "items": ["2.02,9.01", "", "", "7.01", ""]}}}
    monkeypatch.setattr(sec_edgar, "fetch", lambda client, method, url, **kw: FakeResponse(submissions))
    items, total = sec_edgar.ADAPTER.window("0000732712 Verizon", date(2026, 9, 1), date(2026, 10, 3))
    assert total == 3
    assert sorted(i.published_date for i in items) == ["2026-09-10", "2026-09-12", "2026-09-30"]
    first = next(i for i in items if i.published_date == "2026-09-30")
    assert first.url == ("https://www.sec.gov/Archives/edgar/data/732712/000073271226000101/"
                         "0000732712-26-000101-index.htm")
    assert first.extra["primary"].endswith("/vz-8k.htm") and first.extra["items"] == "2.02,9.01"


def test_sec_complete_reads_the_ex99_exhibit(monkeypatch):
    index = """<table><tr><th>Seq</th></tr>
      <tr><td>1</td><td>8-K</td><td><a href="/Archives/edgar/data/732712/x/vz-8k.htm">vz-8k.htm</a></td><td>8-K</td></tr>
      <tr><td>2</td><td>Press release</td><td><a href="/ix?doc=/Archives/edgar/data/732712/x/ex99.htm">ex99.htm</a></td><td>EX-99</td></tr>
    </table>"""
    pages = {"https://www.sec.gov/Archives/edgar/data/732712/x/ex99.htm":
             "<html><body><p>Verizon launches a quantum-safe network service for enterprises.</p></body></html>",
             "primary": "<html><body><p>Item 7.01 Regulation FD Disclosure.</p></body></html>"}

    def fake_fetch(client, method, url, **kw):
        if url.endswith("-index.htm"):
            return FakeResponse(text=index)
        return FakeResponse(text=pages.get(url, pages["primary"]))

    monkeypatch.setattr(sec_edgar, "fetch", fake_fetch)
    monkeypatch.setattr(sec_edgar, "PAUSE", 0)
    item = sec_edgar.Item(url="https://www.sec.gov/Archives/edgar/data/732712/x/acc-index.htm",
                          title="t", text="", published_date="2026-09-30", kind="filing",
                          extra={"company": "VERIZON", "form": "8-K", "items": "7.01",
                                 "primary": "https://www.sec.gov/Archives/edgar/data/732712/x/vz-8k.htm"})
    text = sec_edgar.ADAPTER.complete(item).text
    assert "Form 8-K" in text and "Exhibit EX-99" in text and "quantum-safe network" in text


def test_job_digest_is_stable_and_counts_change():
    roles = [("Engineer, Quantum", "Research"), ("Engineer, Quantum", "Research"), ("Recruiter", "")]
    first = digest_text("Hiring at x", roles, None)
    assert "3 open roles now (first count)" in first
    assert digest_text("Hiring at x", list(reversed(roles)), None) == first   # order-independent
    later = digest_text("Hiring at x", roles, 5)
    assert "(5 at the last run, -2)" in later and "- Engineer, Quantum (2)" in later
    assert "- Unspecified: 1" in later


def test_job_board_queries_are_validated():
    try:
        job_boards.ADAPTER.digest_item("workday:acme", None)
    except ValueError as exc:
        assert "greenhouse:<board>" in str(exc)
    else:
        raise AssertionError("an unknown platform must be refused")


def test_usajobs_digest(monkeypatch):
    result = {"SearchResult": {"SearchResultCountAll": 2, "SearchResultItems": [
        {"MatchedObjectDescriptor": {"PositionTitle": "IT Specialist (INFOSEC)", "OrganizationName": "NSA"}},
        {"MatchedObjectDescriptor": {"PositionTitle": "Physicist", "OrganizationName": "NIST"}}]}}
    monkeypatch.setattr(usajobs, "fetch", lambda client, method, url, **kw: FakeResponse(result))
    item, count = usajobs.ADAPTER.digest_item("post-quantum cryptography", 1)
    assert count == 2 and item.kind == "jobs-digest"
    assert "Postings by agency:" in item.text and "(1 at the last run, +1)" in item.text
    assert item.url == "https://www.usajobs.gov/Search/Results?k=post-quantum%20cryptography"
