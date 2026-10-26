"""Speed check: how long the screens' main API calls take, one at a time and
five at once (as several people, or several open tabs), and how big each
answer is. Read-only GETs; no model calls. Run against the live API and an
API started on the 1-million-page copy (scale_copy.py) to compare.

    python3 perf.py http://localhost:8100 http://localhost:8199
    (from this Mac: the first is live, the second the 1-million-page copy; plain
    Python, nothing to install, and outside the containers it measures)

It signs in to each API first (since 25 Oct), as RADAR_CHECK_EMAIL /
RADAR_CHECK_PASSWORD from the environment (an account on each, never stored
here); each address keeps its own session.

Target (plan v1, §11): every screen's calls under 0.5 s, at any size.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

TARGET_S = 0.5
GIVE_UP_S = 120  # a call still running after this is recorded as such, not waited for
CALLS = [  # (screen, call); {week}: the Briefing's own window, as its page sends it
    ("Status pill (every page)", "/api/pipeline"),
    ("Setup badge (every page)", "/api/changes/count"),
    ("Briefing (a week)", "/api/briefing"),
    ("Briefing, 30 days", "/api/briefing?days=30"),
    ("Briefing, all time", "/api/briefing?days=all"),
    ("Briefing: To do", "/api/gates"),
    ("Briefing: findings (a week)", "/api/signals/found?sort=briefing&limit=15&skip=0&{week}"),
    ("Technologies", "/api/technologies?limit=50"),
    ("Technologies, a filter", "/api/technologies?limit=50&status=ready&catalog=yes"),
    ("Technology", "/api/technologies/agentic-ai"),
    ("Technology: pages", "/api/technologies/agentic-ai/documents?limit=50"),
    ("Points of View", "/api/scoring/povs?limit=48&sort=priority"),
    ("Assessment runs", "/api/scoring/runs"),
    ("Operations: problems", "/api/problems"),
    ("Collections", "/api/runs"),
    ("Leaders' view", "/api/frontier"),
]
ONE_ONLY = {"Briefing, all time"}  # five at once would only queue five of the slowest call behind each other


SESSIONS: dict[str, str] = {}  # each API address its own sign-in cookie


def sign_in(base: str) -> None:
    body = json.dumps({"email": os.environ["RADAR_CHECK_EMAIL"], "password": os.environ["RADAR_CHECK_PASSWORD"]})
    req = urllib.request.Request(base + "/api/auth/sign-in", data=body.encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        SESSIONS[base] = r.headers["Set-Cookie"].split(";", 1)[0]


def opened(url: str, timeout: float = GIVE_UP_S):
    """urlopen with the sign-in cookie of the address it calls."""
    base = next((b for b in SESSIONS if url.startswith(b + "/")), None)
    return urllib.request.urlopen(urllib.request.Request(url, headers={"Cookie": SESSIONS[base]} if base else {}),
                                  timeout=timeout)


def week(base: str) -> str:
    """The Briefing's window, as its page passes it to the findings list."""
    from urllib.parse import urlencode
    scope = json.load(opened(base + "/api/briefing"))["scope"]
    return urlencode({"since": scope["from"], "until": scope["to"]})


def get(url: str) -> tuple[float, int, int | str]:
    t = time.time()
    try:
        with opened(url) as r:
            body = r.read()
            return time.time() - t, len(body), r.status
    except urllib.error.HTTPError as e:
        return time.time() - t, 0, e.code
    except Exception as e:  # noqa: BLE001 — a timeout or a server that went away is the finding
        return time.time() - t, 0, type(e).__name__


def back(base: str, wait_s: int = 300) -> bool:
    """After a call stopped the server (out of memory), wait for it to restart."""
    end = time.time() + wait_s
    while time.time() < end:
        if get(base + "/api/health")[2] == 200:
            return True
        time.sleep(5)
    return False


def measure(base: str) -> dict:
    out = {}
    window = week(base)
    for screen, path in CALLS:
        path = path.replace("{week}", window)
        one, size, status = get(base + path)
        if status != 200 and not back(base):
            out[screen] = {"path": path, "one": one, "five": one, "kb": 0, "status": f"{status}, then didn't come back"}
            continue
        if status == 200 and screen in ONE_ONLY:
            five = one
        elif status == 200:
            with ThreadPoolExecutor(5) as pool:
                five = max(t for t, _, _ in pool.map(lambda _: get(base + path), range(5)))
            back(base)
        else:
            five = one  # one call already stopped it; five at once would only do it again
        out[screen] = {"path": path, "one": one, "five": five, "kb": size / 1024, "status": status}
        print(f"  {base}  {screen}: {one:.2f}s, five at once {five:.2f}s, {size / 1024:.0f} KB, {status}", flush=True)
    return out


def counts(base: str) -> str:
    try:
        p = json.load(opened(base + "/api/technologies?limit=1"))
        return f"{p.get('total', 0):,} technologies"
    except Exception as exc:  # noqa: BLE001
        return f"(counts unavailable: {exc})"


bases = sys.argv[1:] or ["http://localhost:8100"]
for b in bases:
    sign_in(b)
results = {b: measure(b) for b in bases}
print(f"{'screen':30}" + "".join(f"{b.split(':')[-1]:>30}" for b in bases))
print(f"{'':30}" + "".join(f"{'one · five at once · size':>30}" for _ in bases))
for screen, _ in CALLS:
    row = f"{screen:30}"
    for b in bases:
        r = results[b][screen]
        flag = "" if r["status"] == 200 else f" HTTP {r['status']}"
        slow = " SLOW" if r["one"] > TARGET_S else ""
        row += f"{r['one']:>8.2f}s {r['five']:>7.2f}s {r['kb']:>7.0f} KB{slow:>5}{flag}"
    print(row)
for b in bases:
    slow = [s for s, r in results[b].items() if r["one"] > TARGET_S]
    print(f"\n{b}: {counts(b)}; {len(slow)} of {len(CALLS)} calls over {TARGET_S} s" + (f": {', '.join(slow)}" if slow else ""))
