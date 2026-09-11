"""Scout tool: crawl_source. The crawl itself is deterministic — BFS over
hyperlinks (articles included) up to SCRAPE_MAX_DEPTH levels within a
MAX_PAGES_PER_SOURCE budget, same-domain, robots.txt-respecting, with a
politeness delay. Discovery is layered: followed links, sitemap.xml, RSS/Atom
feeds, and (when USE_PLAYWRIGHT) a headless browser that renders JS pages and
clicks 'show more' buttons. The LLM steers which frontier links to descend
into when the frontier outgrows the remaining budget, and summarizes new
content."""

import io
import json
import logging
import re
import time
from urllib import robotparser
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup
from pypdf import PdfReader

from agent.scout.tools.browser import BrowserFetcher
from app.services.prompts import PromptStore
from app.services.runs import store
from app.settings import get_settings

log = logging.getLogger(__name__)

USER_AGENT = "TechAtlas/0.1 (emerging-technology radar; research use)"
MIN_TEXT_CHARS = 200          # below this a page is navigation, not content
LINK_SELECTION_WIDTH = 15     # frontier wider than this per level gets LLM-pruned
COMMON_FEED_PATHS = ("/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml")
SKIP_SUBSTRINGS = (
    "login", "signin", "signup", "register", "careers", "privacy", "terms",
    "cookie", "mailto:", "javascript:", "/tag/", "/tags/", "/category/",
    "/author/", "facebook.com", "twitter.com", "x.com/", "linkedin.com",
    "youtube.com", "instagram.com",
)
SKIP_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".css",
                   ".js", ".ico", ".zip", ".mp4", ".mp3", ".woff", ".woff2", ".xml")


def _same_domain(url: str, root: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return netloc == root or netloc.endswith("." + root)


def _extract_html(html: str, base_url: str) -> tuple[str | None, list[str], dict]:
    """(readable text, absolute links, metadata) from an HTML document."""
    text = trafilatura.extract(html)
    title = published = None
    try:
        meta = trafilatura.extract_metadata(html)
        if meta is not None:
            title, published = meta.title, meta.date
    except Exception:
        pass
    links = []
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        url = urldefrag(urljoin(base_url, a["href"]))[0]
        if url.startswith(("http://", "https://")):
            links.append(url)
    return text, links, {"kind": "article", "title": title, "published_date": published}


def _extract_pdf(content: bytes) -> str | None:
    try:
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return None


def _load_robots(client: httpx.Client, scheme: str, root: str):
    """(robots parser or None, sitemap URLs). Fetched with OUR user agent —
    urllib's robotparser.read() uses Python's default UA, which WAFs 403,
    and robotparser then treats 403 as disallow-everything. Unreachable or
    unparseable robots.txt fails open (crawl allowed), per convention."""
    try:
        response = client.get(f"{scheme}://{root}/robots.txt")
    except httpx.HTTPError:
        return None, []
    if response.status_code != 200:
        return None, []
    robots = robotparser.RobotFileParser()
    robots.parse(response.text.splitlines())
    sitemaps = [line.split(":", 1)[1].strip()
                for line in response.text.splitlines()
                if line.lower().startswith("sitemap:")]
    return robots, sitemaps


def _sitemap_pages(client: httpx.Client, scheme: str, root: str,
                   hints: list[str], limit: int) -> list[str]:
    """Page URLs listed in the site's sitemap(s) — reaches articles hidden
    behind 'view more' buttons and JS pagination that a link crawler can't
    click. Follows one level of sitemap indexes."""
    queue = list(hints) or [f"{scheme}://{root}/sitemap.xml"]
    pages: list[str] = []
    fetched = 0
    while queue and fetched < 6 and len(pages) < limit:
        sitemap_url = queue.pop(0)
        fetched += 1
        try:
            response = client.get(sitemap_url)
        except httpx.HTTPError:
            continue
        if response.status_code != 200:
            continue
        for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", response.text):
            if loc.lower().endswith((".xml", ".xml.gz")):
                if len(queue) < 10:
                    queue.append(loc)
            elif len(pages) < limit:
                pages.append(loc)
    return pages


def _advertised_feeds(html: str, base_url: str) -> list[str]:
    """RSS/Atom feed URLs the page advertises in its <head>."""
    feeds = []
    for match in re.finditer(r"<link[^>]+>", html, re.I):
        tag = match.group(0)
        if (re.search(r"rel=[\"']alternate[\"']", tag, re.I)
                and re.search(r"type=[\"']application/(rss|atom)\+xml", tag, re.I)):
            href = re.search(r"href=[\"']([^\"']+)", tag)
            if href:
                feeds.append(urljoin(base_url, href.group(1)))
    return feeds


def _feed_pages(client: httpx.Client, candidates: list[str], limit: int) -> list[str]:
    """Article URLs from RSS/Atom feeds — the freshest 'what's new' listing a
    site offers, and immune to JS rendering."""
    pages: list[str] = []
    for feed_url in candidates[:8]:
        try:
            response = client.get(feed_url)
        except httpx.HTTPError:
            continue
        head = response.text[:2000].lower()
        if response.status_code != 200 or not any(m in head for m in ("<rss", "<feed", "<rdf")):
            continue
        for match in re.finditer(r"<entry[\s\S]*?</entry>|<item[\s\S]*?</item>", response.text):
            block = match.group(0)
            link = (re.search(r"<link[^>]*href=[\"']([^\"']+)", block)
                    or re.search(r"<link>\s*(\S+?)\s*</link>", block))
            if link:
                pages.append(link.group(1).strip())
            if len(pages) >= limit:
                return pages
    return pages


def _crawlable(url: str, root: str, visited: set) -> bool:
    lowered = url.lower()
    return (url not in visited
            and _same_domain(url, root)
            and not any(s in lowered for s in SKIP_SUBSTRINGS)
            and not lowered.endswith(SKIP_EXTENSIONS))


def make_crawl_tool(run_id: str, category: str, sources_by_url: dict, llm,
                    max_pages_override: int | None = None):
    """Build the crawl_source tool bound to this scout's run context."""
    settings = get_settings()
    max_depth = settings.scrape_max_depth
    max_pages = max_pages_override or settings.max_pages_per_source
    delay = settings.scrape_delay_seconds
    use_browser = settings.use_playwright
    clicks = settings.show_more_clicks
    summary_prompt = PromptStore.get("article_summary")
    link_prompt = PromptStore.get("link_selection")

    def summarize(url: str, text: str) -> tuple[str, list[str], str | None]:
        """(summary, granular technologies, scout's take) — a single LLM call."""
        try:
            reply = llm.ask(summary_prompt.render(url=url, text=text[:12000]))
        except Exception as exc:  # a failed summary must not lose the document
            log.warning("summary failed for %s: %s", url, exc)
            return f"(summary unavailable: {exc})", [], None
        cleaned = reply.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            data = json.loads(cleaned)
            summary = str(data.get("summary", "")).strip() or reply
            technologies = [str(t).strip().lower() for t in data.get("technologies", [])
                            if str(t).strip()]
            take = str(data.get("scout_take", "")).strip() or None
            return summary, technologies, take
        except Exception:  # model ignored the JSON shape — keep its text as the summary
            return reply, [], None

    def select_links(candidates: list[str], budget: int) -> list[str]:
        """LLM picks the frontier links most likely to carry tech updates."""
        try:
            reply = llm.ask(link_prompt.render(budget=str(budget), links="\n".join(candidates)))
            chosen = [line.strip() for line in reply.splitlines() if line.strip() in set(candidates)]
            if chosen:
                return chosen[:budget]
        except Exception as exc:
            log.warning("link selection failed, keeping crawl order: %s", exc)
        return candidates[:budget]

    def crawl_source(source_url: str) -> str:
        """Crawl one assigned source website for technology updates. Pass one of
        your assigned source URLs verbatim. Crawls up to the configured depth and
        page budget (links + sitemap + RSS feeds, with a headless browser for JS
        pages), stores every update found with its reference URL, extracted text
        and summary, and returns a one-line report."""
        source = sources_by_url.get(source_url.strip().rstrip("/")) or sources_by_url.get(source_url.strip())
        if source is None:
            return f"unknown source URL {source_url!r} — pass an assigned source URL verbatim"
        if store.cancelled(run_id):
            return "RUN CANCELLED"

        store.start_source(run_id, category, source)
        root = urlparse(source["url"]).netloc.lower()
        scheme = urlparse(source["url"]).scheme

        pages = docs = new_docs = 0
        error: str | None = None
        visited: set[str] = set()
        frontier = [source["url"]]
        feed_hints: list[str] = [f"{scheme}://{root}{p}" for p in COMMON_FEED_PATHS]
        browser: BrowserFetcher | None = None

        def render(url: str) -> tuple[str, str]:
            nonlocal browser
            if browser is None:
                browser = BrowserFetcher(USER_AGENT)
            return browser.fetch(url, clicks=clicks)

        try:
            with httpx.Client(timeout=20, follow_redirects=True,
                              headers={"User-Agent": USER_AGENT}) as client:
                robots, sitemap_hints = _load_robots(client, scheme, root)
                sitemap_seed = _sitemap_pages(client, scheme, root, sitemap_hints,
                                              limit=max(50, max_pages))
                for depth in range(max_depth + 1):
                    if not frontier or pages >= max_pages:
                        break
                    next_frontier: list[str] = []
                    for url in frontier:
                        if pages >= max_pages:
                            break
                        if store.cancelled(run_id):
                            raise InterruptedError("RUN CANCELLED")
                        if url in visited:
                            continue
                        visited.add(url)
                        if robots is not None:
                            try:
                                if not robots.can_fetch(USER_AGENT, url):
                                    continue
                            except Exception:
                                pass
                        time.sleep(delay)

                        text: str | None = None
                        links: list[str] = []
                        meta: dict = {}
                        fetched = False
                        response = None
                        try:
                            response = client.get(url)
                        except httpx.HTTPError:
                            pass
                        if response is not None and response.status_code < 400:
                            fetched = True
                            content_type = response.headers.get("content-type", "")
                            if "pdf" in content_type or str(response.url).lower().endswith(".pdf"):
                                text = _extract_pdf(response.content)
                                meta = {"kind": "pdf", "title": None, "published_date": None}
                            elif "html" in content_type or "xml" in content_type:
                                text, links, meta = _extract_html(response.text, str(response.url))
                                if depth == 0:
                                    feed_hints = _advertised_feeds(
                                        response.text, str(response.url)) + feed_hints

                        # Headless browser: JS shells, blocked fetches, and every
                        # entry page (to click 'show more' and expand card grids).
                        thin = not text or len(text.strip()) < MIN_TEXT_CHARS or not links
                        if use_browser and meta.get("kind") != "pdf" and (not fetched or thin or depth == 0):
                            try:
                                html, final_url = render(url)
                                rtext, rlinks, rmeta = _extract_html(html, final_url)
                                if rtext and len(rtext) > len(text or ""):
                                    text = rtext
                                    meta = {**rmeta, **{k: v for k, v in meta.items() if v}}
                                for link in rlinks:
                                    if link not in links:
                                        links.append(link)
                                if depth == 0:
                                    feed_hints = _advertised_feeds(html, final_url) + feed_hints
                                fetched = True
                            except Exception as exc:
                                log.debug("browser render failed for %s: %s", url, exc)

                        if not fetched:
                            continue
                        pages += 1
                        store.bump_source(run_id, source["source_id"], pages=1)
                        if text and len(text.strip()) >= MIN_TEXT_CHARS:
                            is_new = store.save_document(
                                run_id, category, source, url,
                                text.strip(), summarize, depth=depth, meta=meta)
                            docs += 1
                            new_docs += int(is_new)
                            store.bump_source(run_id, source["source_id"],
                                              docs=1, new_docs=int(is_new))
                        if depth < max_depth:
                            for link in links:
                                if _crawlable(link, root, visited) and link not in next_frontier:
                                    next_frontier.append(link)

                    if depth == 0:
                        # sitemap + feed articles join the depth-1 frontier: the
                        # content behind 'view more' buttons and JS pagination.
                        # They pass the same relevance gate as followed links.
                        feed_seed = _feed_pages(client, feed_hints, limit=max(50, max_pages))
                        for url in feed_seed + sitemap_seed:
                            if _crawlable(url, root, visited) and url not in next_frontier:
                                next_frontier.append(url)

                    remaining = max_pages - pages
                    if remaining <= 0 or not next_frontier:
                        frontier = []
                        continue
                    width = min(remaining, LINK_SELECTION_WIDTH)
                    if len(next_frontier) > width:
                        next_frontier = select_links(next_frontier, width)
                    frontier = next_frontier
        except InterruptedError:
            error = "run cancelled"
        except Exception as exc:  # one broken source must not kill the scout
            log.exception("crawl of %s failed", source["url"])
            error = str(exc)[:300]
        finally:
            if browser is not None:
                browser.close()
        store.finish_source(run_id, source["source_id"], pages, docs, new_docs, error)
        if error == "run cancelled":
            return "RUN CANCELLED"
        report = (f"{source['name']}: {pages} pages visited, {docs} documents "
                  f"({new_docs} new)" + (f", error: {error}" if error else ""))
        log.info(report)
        return report

    return crawl_source
