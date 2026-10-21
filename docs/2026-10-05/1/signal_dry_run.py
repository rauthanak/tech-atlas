"""Plan 7, step 2: does the new signal list catch what it should? Reads each test page the way
a collection does (our user agent, the same text extraction) and runs the same page-analysis
call with the live instruction and signal list. Nothing is stored; about 1 model call a page.
Run inside the atlas container:
  docker exec -i tech-radar-atlas-1 python - < signal_dry_run.py"""

import httpx

from agent.scout.tools.crawl import USER_AGENT, _extract_html
from agent.scout.tools.summarize import summarize_page
from app.services.llm.llm import LLM
from app.services.signals import snapshot

# (what the page is, url, the signal it should be found as; "ignore:<id>" for a page that should be set aside)
PAGES = [  # (what the page is, candidate urls: the first readable one is used, the signal it should be found as)
    ("Pre-seed round", ["https://thequantuminsider.com/2026/07/16/arq-raises-1-4-million-pre-seed-round-to-lay-the-foundations-for-the-quantum-internet/"], "funding-round"),
    ("Company-university MoU", ["https://www.6gflagship.com/news/6g-flagship-and-bharat-6g-alliance-sign-a-memorandum/",
                                "https://www.oulu.fi/en/news/6g-flagship-and-bharat-6g-alliance-sign-memorandum",
                                "https://www.bweducation.com/article/tec-iit-hyderabad-sign-mou-to-advance-6g-ai-and-telecom-standardisation-576940",
                                "https://apacnewsnetwork.com/2026/01/tec-iit-kanpur-sign-mou-to-collaborate-on-6g-and-next-gen-telecom-standards/amp/",
                                "https://pokde.net/system/service/telco-isp/iium-joins-u-mobile-eip"], "partnership"),
    ("Hyperscaler moving into TCL's market", ["https://thenextweb.com/news/amazon-leo-satellite-internet-mid-2026"], "competitor-move"),
    ("Startup out of stealth", ["https://techcrunch.com/2026/03/10/ai-network-startup-eridu-emerges-from-stealth-with-hefty-200m-series-a/"], "spin-out"),
    ("Analyst's first report on a field", ["https://ir.crowdstrike.com/news-releases/news-release-details/crowdstrike-named-leader-inaugural-2026-gartnerr-magic",
                                           "https://www.prnewswire.com/news-releases/group-ib-named-a-leader-in-the-inaugural-gartner-magic-quadrant-for-cyberthreat-intelligence-technologies-302762559.html",
                                           "https://www.crowdstrike.com/en-us/press-releases/crowdstrike-named-a-leader-2026-gartner-magic-quadrant-for-cyberthreat-intelligence-technologies/"], "market-figure"),
    ("NIST validation", ["https://quantumxc.com/fips-203-validated-pqc/",
                         "https://www.globenewswire.com/news-release/2026/09/24/3368306/0/en/sealsq-leverages-nist-fips-140-3-level-3-validation-to-accelerate-government-critical-infrastructure-and-post-quantum-hardware-security-programs-provides-updated-certification-and-.html",
                         "https://www.wolfssl.com/wolfssl-advances-post-quantum-encryption-and-fips-140-3-across-embedded-and-enterprise-systems-to-facilitate-cnsa-2-0-compliance/"], "approval-licence-or-certification"),
    ("Check: Series B round", ["https://techcrunch.com/2026/05/12/exaforce-raises-125m-series-b-to-build-ai-for-catching-and-stopping-cyberattacks-as-they-happen/"], "funding-round"),
    ("Check: patch notes", ["https://www.postgresql.org/docs/release/17.2/"], "ignore:routine-update"),
]

import os
ONLY = [x.strip() for x in os.environ.get("ONLY", "").split(",") if x.strip()]  # run a subset by label
PAGES = [p for p in PAGES if not ONLY or p[0] in ONLY]

snap = snapshot.build()
names = {r["_id"]: r["name"] for r in snap["signal_list"]}
print(f"signal list: {len(snap['signal_list'])} types, fingerprint {snap['signals_hash']}")
llm = LLM.initialize()
passed = 0
with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=90) as client:
    for label, urls, expected in PAGES:
        print(f"\n== {label}: expect {names.get(expected, expected)}")
        url = text = None
        for candidate in urls:
            try:
                r = client.get(candidate)
                text = _extract_html(r.text, str(r.url))[0] if r.status_code == 200 else None
                reason = f"HTTP {r.status_code}" + ("" if r.status_code != 200 else ", no readable text")
            except Exception as exc:
                text, reason = None, f"{type(exc).__name__}: {exc}"
            print(f"   {'read' if text else 'could not read (' + reason + ')'}: {candidate[:100]}")
            if text:
                url = candidate
                break
        if not text:
            print("   NOT TESTED: no candidate page could be read")
            continue
        out = summarize_page(llm, url, text, snap)
        if out.get("analysis_error"):
            print(f"   ANALYSIS FAILED: {out['analysis_error']}")
            continue
        hits = out.get("signals") or []
        for h in hits:
            print(f"   found {h['name']}{' (' + h['label'] + ')' if h.get('label') else ''}: {h.get('headline')}")
        if out.get("ignored_by"):
            print(f"   set aside as {names.get(out['ignored_by'], out['ignored_by'])}")
        if not hits and not out.get("ignored_by"):
            print("   no signal")
        ok = (out.get("ignored_by") == expected.split(":", 1)[1]) if expected.startswith("ignore:") \
            else any(h["signal_id"] == expected for h in hits)
        passed += ok
        print("   PASS" if ok else "   MISS")
print(f"\n{passed} of {len(PAGES)} pages found as expected")
