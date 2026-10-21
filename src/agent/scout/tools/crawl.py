"""Website collection. The crawl is deterministic — BFS over hyperlinks
(articles included) from the source's start pages (entry_urls, or url), up
to SCRAPE_MAX_DEPTH levels within the page budget, politeness delay between
fetches. Discovery is layered: followed links, RSS/Atom feeds (a start page
may itself be a feed), sitemap.xml, and (when USE_PLAYWRIGHT) a headless
browser that renders JS pages and clicks 'show more' buttons.

Subdomains of a source's sites count as the same site. Link aggregators
(follow_outbound) also fetch the story links they point to, one hop: those
pages are stored but their own links are not followed. robots.txt is obeyed
per host, wildcard rules included. The LLM steers which links to descend
into when a level outgrows the budget; links left unvisited for lack of
budget are counted and reported, never dropped silently."""

import io
import logging
import re
import time
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup
from protego import Protego
from pypdf import PdfReader

from agent.scout.tools.browser import BrowserFetcher
from agent.scout.tools.context import Context, Outcome
from app.services.llm.context import with_context
from app.services.prompts import PromptStore
from app.services.signals.snapshot import prompt_lines
from app.settings import get_settings

log = logging.getLogger(__name__)

USER_AGENT = "TechAtlas/0.1 (emerging-technology radar; research use)"
MIN_TEXT_CHARS = 200          # below this a page is navigation, not content
LINK_SELECTION_WIDTH = 15     # frontier wider than this per level gets LLM-pruned
COMMON_FEED_PATHS = ("/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml")
SKIP_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".css",
                   ".js", ".ico", ".zip", ".mp4", ".mp3", ".woff", ".woff2", ".xml")


# ── which links a crawl may follow ───────────────────────────────────

def site_of(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def sites_for(source: dict) -> set[str]:
    """A source's sites: the host of its url and of each start page, without www."""
    return {site_of(u) for u in [source["url"], *(source.get("entry_urls") or [])] if u}


def same_site(url: str, sites: set[str]) -> bool:
    host = site_of(url)
    return any(host == s or host.endswith("." + s) for s in sites)


def skipped(url: str, patterns: list[str]) -> bool:
    """The editable skip list (crawl settings) plus file types, which are technical."""
    lowered = url.lower()
    return (any(p.lower() in lowered for p in patterns)
            or urlparse(lowered).path.endswith(SKIP_EXTENSIONS))


# ── extraction ───────────────────────────────────────────────────────

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


def is_feed(content_type: str, body: str) -> bool:
    """An RSS or Atom feed, by its content type or by its opening tag."""
    content_type = content_type.lower()
    if "rss" in content_type or "atom" in content_type:
        return True
    head = body[:2000].lower()
    return any(marker in head for marker in ("<rss", "<feed", "<rdf:rdf"))


def feed_links(xml: str) -> list[str]:
    """The item links of an RSS/Atom feed, in feed order."""
    links: list[str] = []
    for match in re.finditer(r"<entry[\s\S]*?</entry>|<item[\s\S]*?</item>", xml):
        block = match.group(0)
        link = (re.search(r"<link[^>]*href=[\"']([^\"']+)", block)
                or re.search(r"<link>\s*(?:<!\[CDATA\[)?\s*(\S+?)\s*(?:\]\]>)?\s*</link>", block))
        if link:
            url = link.group(1).strip()
            if url.startswith(("http://", "https://")) and url not in links:
                links.append(url)
    return links


# ── discovery helpers ────────────────────────────────────────────────

def _robots(client: httpx.Client, scheme: str, host: str, cache: dict):
    """The host's robots.txt rules (cached per crawl), parsed with protego so
    wildcard rules such as `Disallow: /*?*` are obeyed. Fetched with OUR
    user agent (WAFs refuse default ones). Unreachable or unparseable
    robots.txt fails open, per convention."""
    if host not in cache:
        parser = None
        try:
            response = client.get(f"{scheme}://{host}/robots.txt")
            if response.status_code == 200:
                parser = Protego.parse(response.text)
        except Exception:
            parser = None
        cache[host] = parser
    return cache[host]


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
        if response.status_code != 200 or not is_feed("", response.text):
            continue
        for link in feed_links(response.text):
            if link not in pages:
                pages.append(link)
            if len(pages) >= limit:
                return pages
    return pages


# ── link selection ───────────────────────────────────────────────────

def link_selection_values(links: list[str], budget: int, never_miss_names: str) -> dict:
    """The link-selection skill's blanks. The Skills page's preview fills them
    with this same function, so it shows exactly what a crawl sends."""
    return {"budget": str(budget), "links": "\n".join(links), "never_miss_names": never_miss_names}


def select_links(llm, prompt, links: list[str], budget: int, never_miss_names: str) -> list[str]:
    """The LLM picks the links most likely to carry tech updates and signals."""
    try:
        with with_context(skills=["link_selection"]):
            reply = llm.ask(prompt.render(**link_selection_values(links, budget, never_miss_names)))
        offered = set(links)
        chosen = list(dict.fromkeys(line.strip() for line in reply.splitlines()
                                    if line.strip() in offered))
        if chosen:
            return chosen[:budget]
    except Exception as exc:
        log.warning("link selection failed, keeping crawl order: %s", exc)
    return links[:budget]


# ── the crawl ────────────────────────────────────────────────────────

def crawl(ctx: Context, source: dict) -> Outcome:
    """Crawl one website source; every page with content goes through
    ctx.save (stored, summarized with the run's signal list, counted)."""
    settings = get_settings()
    max_depth = settings.scrape_max_depth
    max_pages = ctx.max_pages
    delay = settings.scrape_delay_seconds
    use_browser = settings.use_playwright
    clicks = settings.show_more_clicks
    patterns = list(ctx.settings.get("skip_url_patterns") or [])
    never_miss_names = prompt_lines(ctx.snapshot.get("signal_list") or [])["never_miss_names"]
    link_prompt = PromptStore.get("link_selection")
    follow_outbound = bool(source.get("follow_outbound"))

    sites = sites_for(source)
    primary = urlparse(source["url"])
    scheme, root = primary.scheme, primary.netloc.lower()

    outcome = Outcome()
    visited: set[str] = set()
    candidates: set[str] = set()   # every link that entered a level, kept or not
    leaves: set[str] = set()       # outbound story links: fetched, not followed
    start_pages = [u for u in (source.get("entry_urls") or []) if u] or [source["url"]]
    frontier = list(dict.fromkeys(start_pages))
    candidates.update(frontier)
    feed_hints: list[str] = [f"{scheme}://{root}{p}" for p in COMMON_FEED_PATHS]
    robots_cache: dict[str, Protego | None] = {}
    browser: BrowserFetcher | None = None

    def render(url: str) -> tuple[str, str]:
        nonlocal browser
        if browser is None:
            browser = BrowserFetcher(USER_AGENT)
        return browser.fetch(url, clicks=clicks)

    def allowed(client: httpx.Client, url: str) -> bool:
        parts = urlparse(url)
        parser = _robots(client, parts.scheme, parts.netloc.lower(), robots_cache)
        if parser is None:
            return True
        try:
            return parser.can_fetch(url, USER_AGENT)
        except Exception:
            return True

    def queue(link: str, next_frontier: list[str]) -> None:
        """Add a link to the next level: on-site links are followed; with
        follow_outbound, links to other sites are fetched as leaf pages."""
        if link in visited or link in next_frontier or skipped(link, patterns):
            return
        if same_site(link, sites):
            next_frontier.append(link)
        elif follow_outbound:
            next_frontier.append(link)
            leaves.add(link)

    try:
        with httpx.Client(timeout=20, follow_redirects=True,
                          headers={"User-Agent": USER_AGENT}) as client:
            robots = _robots(client, scheme, root, robots_cache)
            sitemap_hints = list(robots.sitemaps) if robots is not None else []
            sitemap_seed = _sitemap_pages(client, scheme, root, sitemap_hints,
                                          limit=max(50, max_pages))
            for depth in range(max_depth + 1):
                if not frontier or outcome.pages >= max_pages:
                    break
                next_frontier: list[str] = []
                for url in frontier:
                    if outcome.pages >= max_pages:
                        break
                    if ctx.cancelled():
                        raise InterruptedError("RUN CANCELLED")
                    if url in visited:
                        continue
                    visited.add(url)
                    if not allowed(client, url):
                        continue
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
                        content_type = response.headers.get("content-type", "")
                        if depth == 0 and is_feed(content_type, response.text):
                            # a feed start page: its items join the next level; the
                            # feed itself is not stored and uses no page budget
                            for link in feed_links(response.text):
                                queue(link, next_frontier)
                            continue
                        fetched = True
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
                    ctx.visited(outcome, source)
                    if text and len(text.strip()) >= MIN_TEXT_CHARS:
                        ctx.save(outcome, source, url, text.strip(), depth=depth, meta=meta)
                    if depth < max_depth and url not in leaves:
                        for link in links:
                            queue(link, next_frontier)

                if depth == 0:
                    # sitemap + feed articles join the depth-1 frontier: the
                    # content behind 'view more' buttons and JS pagination.
                    # They pass the same relevance gate as followed links.
                    for url in _feed_pages(client, feed_hints, limit=max(50, max_pages)) + sitemap_seed:
                        if same_site(url, sites):
                            queue(url, next_frontier)

                candidates.update(next_frontier)
                remaining = max_pages - outcome.pages
                if remaining <= 0 or not next_frontier:
                    frontier = []
                    continue
                width = min(remaining, LINK_SELECTION_WIDTH)
                if len(next_frontier) > width:
                    with with_context(run_kind="collection", run_id=ctx.run_id):
                        next_frontier = select_links(ctx.llm, link_prompt, next_frontier, width,
                                                     never_miss_names)
                frontier = next_frontier
    except InterruptedError:
        outcome.error = "run cancelled"
    except Exception as exc:  # one broken source must not kill the scout
        log.exception("crawl of %s failed", source["url"])
        outcome.error = str(exc)[:300]
    finally:
        if browser is not None:
            browser.close()

    unvisited = len(candidates - visited)
    if unvisited and outcome.error is None:
        outcome.incomplete_note = f"didn't finish: {unvisited} links left"
    return outcome


# ── one page, on its own (Find evidence, Add a link) ─────────────────

def fetch_page(url: str) -> tuple[str | None, dict, str | None]:
    """(text, meta, why not): one page read the way the crawler reads it —
    the page itself, a PDF's text, or the headless browser when the page is
    a script shell or blocks a plain fetch."""
    text, meta, why = None, {}, None
    try:
        with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(url)
        if response.status_code >= 400:
            why = f"the site answered {response.status_code}"
        else:
            content_type = response.headers.get("content-type", "")
            if "pdf" in content_type or str(response.url).lower().endswith(".pdf"):
                text, meta = _extract_pdf(response.content), {"kind": "pdf", "title": None, "published_date": None}
            elif "html" in content_type or "xml" in content_type:
                text, _, meta = _extract_html(response.text, str(response.url))
            else:
                why = f"not a page or a PDF ({content_type or 'unknown type'})"
    except httpx.HTTPError as exc:
        why = f"the site couldn't be reached ({type(exc).__name__})"
    if (not text or len(text.strip()) < MIN_TEXT_CHARS) and meta.get("kind") != "pdf" and get_settings().use_playwright:
        browser = BrowserFetcher(USER_AGENT)
        try:
            html, final_url = browser.fetch(url, clicks=0)
            rtext, _, rmeta = _extract_html(html, final_url)
            if rtext and len(rtext) > len(text or ""):
                text, meta, why = rtext, {**rmeta, **{k: v for k, v in meta.items() if v}}, None
        except Exception as exc:
            why = why or f"the page couldn't be rendered ({type(exc).__name__})"
        finally:
            browser.close()
    if text and len(text.strip()) >= MIN_TEXT_CHARS:
        return text.strip(), meta, None
    return None, meta, why or "too little text on the page"
