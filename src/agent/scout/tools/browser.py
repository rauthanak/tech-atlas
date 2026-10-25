"""Headless-browser fetch (Playwright/Chromium). Renders JavaScript pages the
plain HTTP crawler sees as empty shells, and clicks 'show more'-style buttons
so lazily-loaded card grids expand before we read the page.

All Playwright work runs on one dedicated thread per fetcher — the sync API
refuses to run inside a thread that owns an asyncio loop, and scout threads
may hold one via the agent runtime. A page that hangs the browser past the
time limit has that browser's processes stopped, and the next page starts a
fresh one, so one bad page never holds up the rest (or leaks a browser)."""

import logging
import os
import re
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as Timeout

log = logging.getLogger(__name__)

MORE_BUTTON = re.compile(
    r"(load|show|view|see)\s*more|more\s*(stories|articles|news|posts|results)", re.I)


_launching = threading.Lock()  # one browser starts at a time, so each knows which processes are its own


def _descendants(pid: int) -> set[int]:
    """Every process started under `pid` (Linux /proc; empty elsewhere)."""
    parents: dict[int, int] = {}
    for entry in os.listdir("/proc") if os.path.isdir("/proc") else []:
        if entry.isdigit():
            try:
                with open(f"/proc/{entry}/stat") as f:
                    parents[int(entry)] = int(f.read().rsplit(")", 1)[1].split()[1])
            except (OSError, ValueError, IndexError):
                continue
    out, todo = set(), [pid]
    while todo:
        p = todo.pop()
        kids = [c for c, parent in parents.items() if parent == p]
        out.update(kids)
        todo.extend(kids)
    return out


class BrowserFetcher:
    def __init__(self, user_agent: str):
        self._user_agent = user_agent
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser")
        self._playwright = None
        self._browser = None
        self._procs: set[int] = set()  # this browser's processes, to stop it if it hangs

    def _ensure(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            with _launching:
                before = _descendants(os.getpid())
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(headless=True)
                self._procs = _descendants(os.getpid()) - before

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
        """(rendered HTML, final URL) after JS execution and show-more clicks.
        A page that hangs past `timeout` stops this browser; the next fetch
        starts a fresh one."""
        try:
            return self._pool.submit(self._fetch, url, clicks).result(timeout=timeout)
        except Timeout:
            log.warning("browser hung on %s for %ss: stopping it, the next page starts a fresh one", url, timeout)
            self._kill()
            raise

    def _kill(self) -> None:
        """Stop this browser's processes (the hung thread then fails and ends),
        and start the next fetch on a new thread with a new browser."""
        for pid in self._procs | {d for p in self._procs for d in _descendants(p)}:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        self._pool.shutdown(wait=False)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser")
        self._playwright = self._browser = None
        self._procs = set()

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
