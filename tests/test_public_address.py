"""The radar reads only public websites (code review CR08): links and
redirects to private addresses are refused before they're fetched, by the
crawler, by Find evidence and for pasted links, saying why."""

import httpx
import pytest
from fastapi.testclient import TestClient

from agent.scout.tools import addresses, browser, crawl
from app.main import app


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost:8100/api", "http://10.0.0.5/", "http://172.16.0.1/",
                                 "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/",
                                 "http://[fe80::1]/", "http://[fc00::1]/", "http://0.0.0.0/", "http://224.0.0.1/",
                                 "http://[::ffff:127.0.0.1]/", "http://100.64.0.1/"])
def test_private_addresses_are_refused(url):
    assert addresses.private_host(url)


@pytest.mark.parametrize("url", ["http://93.184.216.34/", "https://nothing.invalid/", "upload:deck.pdf"])
def test_public_and_unresolvable_addresses_pass(url):
    assert addresses.private_host(url) is None


def test_a_name_resolving_to_a_private_address_is_refused(monkeypatch):
    monkeypatch.setattr(addresses.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.1.2.3", 0))])
    assert addresses.private_host("https://intranet.example/") == "intranet.example"


def _mock(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(crawl.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(crawl.get_settings(), "use_playwright", False)


def test_a_redirect_to_a_private_address_is_refused(monkeypatch):
    asked = []

    def handler(request):
        asked.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
    _mock(monkeypatch, handler)
    assert crawl.fetch_page("https://public.example/") == (None, {}, addresses.PRIVATE)
    assert asked == ["https://public.example/"]   # the private address is never asked


def test_a_private_page_is_refused_before_it_is_asked(monkeypatch):
    asked = []
    _mock(monkeypatch, lambda r: asked.append(r) or httpx.Response(200, text="x"))
    assert crawl.fetch_page("http://127.0.0.1:8100/api/health")[2] == addresses.PRIVATE and asked == []


def test_crawl_says_why_a_private_link_was_skipped():
    assert crawl.why_failed(addresses.NotPublic(addresses.PRIVATE)) == addresses.PRIVATE


def test_a_pasted_private_link_is_refused(db):
    from factories import tech
    tech(db)
    client = TestClient(app)
    r = client.post("/api/find-evidence/add", data={"tech_id": "edge-ai", "urls": '["http://169.254.169.254/latest"]'})
    assert r.status_code == 422 and "inside a private network" in r.json()["detail"]
    r = client.post("/api/find-evidence", json={"gap": {"kind": "link", "tech_id": "edge-ai", "url": "http://10.0.0.5/x"}})
    assert r.status_code == 422 and "inside a private network" in r.json()["detail"]


def test_the_browser_aborts_requests_to_private_addresses():
    class Route:
        def __init__(self, url):
            self.request, self.done = type("R", (), {"url": url})(), None

        def abort(self, why):
            self.done = why

        def continue_(self):
            self.done = "continued"
    guard = browser._public_only({})
    private, public = Route("http://169.254.169.254/latest"), Route("http://93.184.216.34/page")
    guard(private)
    guard(public)
    assert (private.done, public.done) == ("blockedbyclient", "continued")
