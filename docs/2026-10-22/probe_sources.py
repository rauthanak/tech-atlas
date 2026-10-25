"""Can the crawler read each switched-off free source? Fetches each start page
once (no model calls) and reports the HTTP status, the size of the text and
the number of links. Writes nothing to the database.

    docker cp probe_sources.py tech-radar-atlas-1:/tmp/ && docker exec tech-radar-atlas-1 python /tmp/probe_sources.py
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.services.db.mongo import get_collection as g

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}


def probe(s):
    urls = s.get("entry_urls") or [s["url"]]
    out = []
    for u in urls[:2]:
        try:
            r = httpx.get(u, headers=UA, timeout=20, follow_redirects=True)
            html = r.text
            text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.S)
            out.append({"url": u, "status": r.status_code, "text": len(" ".join(text.split())),
                        "links": len(re.findall(r"<a\s[^>]*href=", html, re.I))})
        except Exception as e:  # noqa: BLE001
            out.append({"url": u, "status": None, "error": type(e).__name__})
    return {"id": s["_id"], "name": s["name"], "cluster": s.get("cluster"), "access": s.get("access"),
            "cost": s.get("cost"), "probes": out}


cands = list(g("sources").find({"enabled": False, "access": "crawl", "cost": {"$in": ["free", "free_tier"]}}))
with ThreadPoolExecutor(12) as ex:
    print(json.dumps(list(ex.map(probe, cands))))
