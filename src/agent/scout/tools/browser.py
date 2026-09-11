"""Headless-browser fetch (Playwright/Chromium). Renders JavaScript pages the
plain HTTP crawler sees as empty shells, and clicks 'show more'-style buttons
so lazily-loaded card grids expand before we read the page.

All Playwright work runs on one dedicated thread per fetcher — the sync API
refuses to run inside a thread that owns an asyncio loop, and scout threads
may hold one via the agent runtime."""

import logging
import re
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

MORE_BUTTON = re.compile(
    r"(load|show|view|see)\s*more|more\s*(stories|articles|news|posts|results)", re.I)


class BrowserFetcher:
    def __init__(self, user_agent: str):
        self._user_agent = user_agent
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser")
        self._playwright = None
        self._browser = None

    def _ensure(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)

    def _fetch(self, url: str, clicks: int) -> tuple[str, str]:
        self._ensure()
        context = self._browser.new_context(user_agent=self._user_agent)
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)  # let first client-side render settle
            for _ in range(clicks):
                try:
                    button = page.get_by_role("button", name=MORE_BUTTON).first
                    if not button.is_visible():
                        break
                    button.click(timeout=3000)
                    page.wait_for_timeout(1200)
                except Exception:
                    break  # no (more) expandable button — normal
            return page.content(), page.url
        finally:
            context.close()

    def fetch(self, url: str, clicks: int = 3, timeout: float = 75) -> tuple[str, str]:
        """(rendered HTML, final URL) after JS execution and show-more clicks."""
        return self._pool.submit(self._fetch, url, clicks).result(timeout=timeout)

    def close(self) -> None:
        def _shutdown():
            try:
                if self._browser is not None:
                    self._browser.close()
                if self._playwright is not None:
                    self._playwright.stop()
            except Exception:
                pass

        try:
            self._pool.submit(_shutdown).result(timeout=15)
        except Exception:
            pass
        self._pool.shutdown(wait=False)
