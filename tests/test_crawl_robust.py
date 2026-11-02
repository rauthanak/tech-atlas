"""One bad link or page never stops a source: it is skipped, counted with
its reason, and the crawl carries on (22 Oct: Cisco blogs stopped after 6
pages on one malformed link; arXiv after 42 on one undecodable character)."""

from types import SimpleNamespace

import httpx

from agent.scout.tools import crawl as crawler
from agent.scout.tools.context import Outcome
from app.services import page_texts

TEXT = "A page about network slicing and private 5G deployments. " * 10


def _page(links: list[str]) -> str:
    return "<html><body><article><p>" + TEXT + "</p>" + "".join(f'<a href="{h}">x</a>' for h in links) + "</article></body></html>"


SITE = {
    "https://blogs.example.com/": _page(["/one", "http://[bad", "/two", "/broken"]),
    "https://blogs.example.com/one": _page([]),
    "https://blogs.example.com/two": _page([]),
}


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith("/broken"):
        raise httpx.ConnectError("refused", request=request)
    if url in SITE:
        return httpx.Response(200, html=SITE[url])
    return httpx.Response(404)


class FakeCtx:
    run_id = "r"
    llm = None
    snapshot: dict = {}
    max_pages = 20
    settings: dict = {}

    def __init__(self):
        self.saved: list[str] = []

    def cancelled(self):
        return False

    def visited(self, outcome, source):
        outcome.pages += 1

    def save(self, outcome, source, url, text, depth=0, meta=None):
        self.saved.append(url)
        outcome.docs += 1


def test_a_malformed_link_and_an_unreachable_page_are_skipped_with_their_reasons(monkeypatch):
    real_client = httpx.Client
    monkeypatch.setattr(crawler.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(_handler), **kw))
    monkeypatch.setattr(crawler, "get_settings", lambda: SimpleNamespace(
        scrape_max_depth=1, scrape_delay_seconds=0, use_playwright=False, show_more_clicks=0))
    monkeypatch.setattr(crawler, "PromptStore", SimpleNamespace(get=lambda name: None))
    monkeypatch.setattr(crawler, "prompt_lines", lambda signals: {"never_miss_names": ""})

    ctx = FakeCtx()
    outcome = crawler.crawl(ctx, {"url": "https://blogs.example.com/", "source_id": "blog"})

    assert outcome.error is None                       # the source finished
    assert set(ctx.saved) == {"https://blogs.example.com/", "https://blogs.example.com/one",
                              "https://blogs.example.com/two"}
    skipped = {(e["what"], e["reason"]): e for e in outcome.skipped_list()}
    assert skipped[("link", "its address is malformed")]["examples"] == ["http://[bad"]
    assert skipped[("page", "the site couldn't be reached (ConnectError)")]["count"] == 1
    assert "1 links skipped: its address is malformed" in outcome.report("Blog")


def test_a_site_whose_robots_txt_refuses_says_so(monkeypatch):
    """31 Oct: The Next Platform's robots.txt refuses unnamed crawlers; the
    source read 0 pages and said nothing."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(200, html=_page([]))
    real_client = httpx.Client
    monkeypatch.setattr(crawler.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(crawler, "get_settings", lambda: SimpleNamespace(
        scrape_max_depth=1, scrape_delay_seconds=0, use_playwright=False, show_more_clicks=0))
    monkeypatch.setattr(crawler, "PromptStore", SimpleNamespace(get=lambda name: None))
    monkeypatch.setattr(crawler, "prompt_lines", lambda signals: {"never_miss_names": ""})

    outcome = crawler.crawl(FakeCtx(), {"url": "https://closed.example.com/", "source_id": "closed"})
    assert outcome.docs == 0
    assert "1 pages skipped: the site's robots.txt asks crawlers not to read it" in outcome.report("Closed")


def test_reasons_read_plainly():
    assert crawler.why_failed(ValueError("Invalid IPv6 URL")) == "its address is malformed"
    assert crawler.why_failed(UnicodeEncodeError("utf-8", "\ud83d", 0, 1, "surrogates not allowed")) \
        == "its text had characters that couldn't be stored"
    assert crawler.why_failed(httpx.ReadTimeout("slow")) == "the site took too long to answer"


def test_text_with_a_lone_surrogate_is_stored(db):
    from app.services.runs import store

    db["runs"].insert_one({"_id": "r"})
    analysis = {"summary": "s", "technologies": [], "scout_take": None, "signals": [], "ignored_by": None,
                "signals_hash": "h", "parts": 1, "partial": False}
    store.save_document("r", "H1", {"source_id": "arxiv", "url": "https://arxiv.org"}, "https://arxiv.org/abs/1",
                        "Broken entity \ud83d here. " + TEXT, lambda url, text: analysis,
                        meta={"title": "Title \udc00"})
    doc = db["documents"].find_one({"end_url": "https://arxiv.org/abs/1"})
    assert "�" in page_texts.text(doc["_id"]) and doc["title"] == "Title �"


def test_one_skip_reason_counts_once_per_page():
    outcome = Outcome()
    for n in range(7):
        outcome.skip(f"https://a.com/{n}", "the site answered 404")
    entry = outcome.skipped_list()[0]
    assert entry["count"] == 7 and len(entry["examples"]) == 5


REAL_CLIENT = httpx.Client  # before any test patches it


def _wide_site(monkeypatch, settings: dict, max_pages: int) -> int:
    """A site where every page links to 50 more, crawled with the AI's link
    picking replaced by "the first n": how many pages does it read?"""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/robots.txt",) or request.url.path.endswith((".xml", "/feed", "/rss", "/atom.xml")):
            return httpx.Response(404)
        here = request.url.path.rstrip("/")
        return httpx.Response(200, html=_page([f"{here}/p{i}" for i in range(50)]))
    monkeypatch.setattr(crawler.httpx, "Client", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(crawler, "get_settings", lambda: SimpleNamespace(
        scrape_max_depth=8, scrape_delay_seconds=0, use_playwright=False, show_more_clicks=0))
    monkeypatch.setattr(crawler, "PromptStore", SimpleNamespace(get=lambda name: None))
    monkeypatch.setattr(crawler, "prompt_lines", lambda signals: {"never_miss_names": ""})
    monkeypatch.setattr(crawler, "select_links", lambda llm, prompt, links, n, names: links[:n])
    ctx = FakeCtx()
    ctx.max_pages, ctx.settings = max_pages, settings
    return crawler.crawl(ctx, {"url": "https://wide.example.com/", "source_id": "wide"}).docs


def test_automatic_links_per_level_reach_the_page_budget(monkeypatch):
    """1 Nov: 15 links per level × 8 levels stopped every website near 121 pages, whatever its budget."""
    assert _wide_site(monkeypatch, {"link_depth": 8}, 150) == 150
    assert crawler.level_width(149, 8) == 19 and crawler.level_width(40, 8) == 15


def test_a_fixed_links_per_level_and_the_depth_are_kept_to(monkeypatch):
    assert _wide_site(monkeypatch, {"link_depth": 8, "links_per_level": 15}, 150) == 121
    assert _wide_site(monkeypatch, {"link_depth": 2, "links_per_level": 15}, 150) == 31
