"""Where each technology stands — one status with its reason — the views the
Technologies list offers, and the Before scoring list (Gate 1).

  status       rule                                                reason shown
  off          switched off                                        when, and new pages since
  placed       assessed; a fabric has a priority (computed or      "Priority P3 in Cloud, IoT"
               set by a person)
  held         assessed; no fabric has a priority                  what couldn't be scored
  ready        not assessed; the evidence was judged strong or     the verdict, or "3 pages"
               enough (before it's judged: pages at the floor), or
               a person confirmed it as nascent
  thin         not assessed; the evidence was judged thin or not   the verdict's reason, or "2 of 3 pages"
               credible (before it's judged: under the floor)
  no_evidence  no pages yet                                        "Imported Oct 21" · "Added by hand"

Today's run states (being assessed, stopped partway, new pages since its
assessment, ready for a Point of View) become notes on the row.

A technology is in Tata's catalog (its own list of emerging technologies)
when an import added it or matched it (its `imported` record), unless a
person took it out; a person can add one too (services/decisions.in_catalog).
The views over commercial availability (Emerging, Mature, and those not in
the catalog: new to Tata, blind spots) list the earliest values first: by
the list's order, then TRL, lowest first."""

from collections import Counter, defaultdict

from agent.analyzer.estimate import estimate
from app.services import classify_effective, decisions, evidence, gates
from app.services.db.mongo import get_collection
from app.services.settings_store import radar_settings

TRACKED = ("placed", "held")
NOT_ASSESSED = ("ready", "thin", "no_evidence")
VIEWS = ("tracked", "not_assessed", "emerging", "emerging_new", "mature", "mature_not_on_tata", "nascent",
         "imported_thin", "off")
BY_AVAILABILITY = ("emerging", "emerging_new", "mature", "mature_not_on_tata")  # earliest values first
MATURE = "mature"  # the Mature value of the commercial availability list
# each filter of the list, and the query keys it reads; a filter's counts leave out its own keys
FACETS = {"availability": ("availability",), "domain": ("domain",), "subdomain": ("subdomain",),
          "trl": ("trl_min", "trl_max"), "evidence": ("evidence",), "fabric": ("fabric",), "catalog": ("catalog",)}
TECH_FIELDS = {"name": 1, "label": 1, "enabled": 1, "page_count": 1, "source_count": 1, "doc_count": 1, "origin": 1,
               "imported": 1, "classification": 1, "assessed_classification": 1, "switched_off_at": 1,
               "switched_off_tz": 1}
NOTES = {"assessing": "Being assessed now", "stopped_partway": "Its assessment stopped partway",
         "no_pov": "Ready for a Point of View"}


def _pages(n: int, kind: str = "") -> str:
    """A page count in words: "1 new page", "1,204 pages"."""
    return f"{n:,} {kind}{'page' if n == 1 else 'pages'}"


def _held_reason(fabrics: list[dict]) -> str:
    p = fabrics[0]["placement"] if fabrics else {}
    if (p.get("timeline") or {}).get("score") is None:
        return "How soon couldn't be scored"
    if (p.get("potential") or {}).get("score") is None:
        return "How big couldn't be scored"
    return "No fabric could be placed"


def _placed_reason(fabrics: list[dict]) -> str:
    placed = [f for f in fabrics if f["effective"]["priority"]]
    best = min(f["effective"]["priority"] for f in placed)
    return f"Priority {best} in {', '.join(f['fabric'] for f in placed if f['effective']['priority'] == best)}"


def _one(t: dict, state: dict, applied: list[dict], cls: dict, floor: int) -> dict:
    pages = t.get("page_count") or 0
    notes = []
    if state["state"] in NOTES:
        notes.append(NOTES[state["state"]])
    if state["state"] == "new_evidence":
        notes.append(f"{_pages(state['new_pages'], 'new ')} since its assessment")
    if t.get("enabled") is False:
        return {"status": "off", "reason": "Switched off", "notes": notes}
    if applied:
        if any(f["effective"]["priority"] for f in applied):
            return {"status": "placed", "reason": _placed_reason(applied), "notes": notes}
        return {"status": "held", "reason": _held_reason(applied), "notes": notes}
    if pages == 0:
        reason = {"imported": "Imported, no pages yet", "added": "Added by hand, no pages yet"}.get(t.get("origin"),
                                                                                                 "No pages yet")
        return {"status": "no_evidence", "reason": reason, "notes": notes}
    if cls["nascent"]["decision"] == "yes":
        return {"status": "ready", "reason": "Confirmed as possibly nascent", "notes": notes}
    ev = cls["evidence"]
    if ev:
        verdict = ev["verdict"]
        words = {"strong": "Evidence judged strong", "enough": "Evidence judged enough",
                 "thin": "Evidence judged thin", "not_credible": "Evidence judged not credible"}[verdict]
        status = "ready" if verdict in ("strong", "enough") else "thin"
        return {"status": status, "reason": f"{words}: {ev.get('reason')}" if ev.get("reason") else words, "notes": notes}
    if pages >= floor:
        return {"status": "ready", "reason": f"{_pages(pages)}, not yet judged", "notes": notes}
    return {"status": "thin", "reason": f"{pages} of {floor} pages, not yet judged", "notes": notes}


def classifications(techs: list[dict] | None = None) -> dict[str, dict]:
    """Each technology's effective classification (services/classify_effective)
    by id: what the Technologies list filters and counts, and what Setup ›
    Classification counts. `techs`: already read, with their classification
    fields; else every technology."""
    if techs is None:
        techs = list(get_collection("technologies").find({}, {"classification": 1, "assessed_classification": 1}))
    mine = defaultdict(list)
    for d in decisions.active([t["_id"] for t in techs]):
        mine[d["tech_id"]].append(d)
    lists = classify_effective.names()
    return {t["_id"]: classify_effective.effective(t, mine[t["_id"]], lists) for t in techs}


def statuses(tech_ids: list[str], all_states: dict | None = None) -> dict[str, dict]:
    """Each technology's status, reason, notes, effective classification and
    effective priorities, by id (`all_states`: evidence.states(), when already
    worked out)."""
    states, full = evidence.list_states(tech_ids, all_states)
    techs = {t["_id"]: t for t in get_collection("technologies").find({"_id": {"$in": tech_ids}}, TECH_FIELDS)}
    applied = gates.latest_applied(all_states=full)
    classified = classifications(list(techs.values()))
    catalog = {d["tech_id"]: d for d in decisions.active(tech_ids, ["catalog"])}
    floor = int(radar_settings()["evidence_floor"])
    out = {}
    for tid, t in techs.items():
        cls = classified[tid]
        fabrics = applied.get(tid, [])
        out[tid] = {**_one(t, states[tid], fabrics, cls, floor), "classification": cls,
                    "catalog": decisions.in_catalog(t, catalog.get(tid)),
                    "priorities": [{"fabric_id": f["fabric_id"], "fabric": f["fabric"], "priority": f["effective"]["priority"],
                                    "override": bool(f["effective"]["override"])} for f in fabrics]
                    or states[tid]["priorities"],
                    "state": states[tid]["state"], "new_pages": states[tid]["new_pages"],
                    "assessed_at": states[tid]["assessed_at"], "measures": states[tid]["measures"]}
    return out


def in_view(view: str, s: dict) -> bool:
    cls = s["classification"]
    in_catalog = s["catalog"]["in"]
    if view == "off":
        return s["status"] == "off"
    if s["status"] == "off":
        return False
    # one in the catalog with no value counts as emerging until its pages show one
    emerging = cls["availability"]["emerging"] or (in_catalog and cls["availability"]["source"] == "none")
    mature = cls["availability"]["id"] == MATURE
    return {"tracked": s["status"] in TRACKED,
            "not_assessed": s["status"] in NOT_ASSESSED,
            "emerging": emerging,
            "emerging_new": emerging and not in_catalog,
            "mature": mature,
            "mature_not_on_tata": mature and not in_catalog,
            "nascent": bool(cls["nascent"]["flag"]) and cls["nascent"]["decision"] != "no",
            "imported_thin": in_catalog and s["status"] in ("thin", "no_evidence")}[view]


def _values(s: dict, facet: str) -> list:
    """The row's value(s) under one filter, as the counts key them."""
    cls = s["classification"]
    if facet == "availability":
        return [cls["availability"]["id"]]
    if facet == "domain":
        return [cls["domain"]["id"]]
    if facet == "subdomain":
        return [cls["domain"]["subdomain_id"] or "none"]
    if facet == "trl":
        return [cls["trl"]["level"] or "none"]
    if facet == "evidence":
        return [(cls["evidence"] or {}).get("verdict") or "none"]
    if facet == "fabric":
        return sorted({p["fabric_id"] for p in s["priorities"]})
    return ["yes" if s["catalog"]["in"] else "no"]  # catalog


def matches(s: dict, f: dict) -> bool:
    """The list's filters: availability, domain, sub-domain, TRL range,
    evidence verdict ("none": not judged yet), fabric, and in the catalog
    ("yes") or not ("no")."""
    for facet in ("availability", "domain", "subdomain", "evidence", "catalog"):
        if f.get(facet) and f[facet] not in _values(s, facet):
            return False
    level = s["classification"]["trl"]["level"]
    if f.get("trl_min") is not None and (level is None or level < f["trl_min"]):
        return False
    if f.get("trl_max") is not None and (level is None or level > f["trl_max"]):
        return False
    if f.get("fabric") and f["fabric"] not in _values(s, "fabric"):
        return False
    return True


def facets(rows: list[dict], f: dict) -> dict:
    """How many rows each filter value holds, counted over `rows` (the search,
    view and status already applied) and every other filter: so each count
    is what choosing that value would show. Sub-domains are counted within
    the chosen domain only, each with its name."""
    out: dict = {}
    for facet, keys in FACETS.items():
        if facet == "subdomain" and not f.get("domain"):
            continue
        rest = {k: v for k, v in f.items() if k not in keys}
        out[facet] = Counter(v for s in rows if matches(s, rest) for v in _values(s, facet))
    if "subdomain" in out:
        names = {s["classification"]["domain"]["subdomain_id"]: s["classification"]["domain"]["subdomain"] for s in rows}
        counted = out["subdomain"]
        if f.get("subdomain"):
            counted.setdefault(f["subdomain"], 0)  # the chosen one stays listed, even when nothing is left in it
        out["subdomain"] = sorted(({"id": i, "name": (names.get(i) or i) if i != "none" else "No sub-domain yet", "n": n}
                                   for i, n in counted.items()),
                                  key=lambda x: (x["id"] == "none", str(x["name"]).lower()))
    return out


def ordered(view: str | None, ids: list[str], st: dict) -> list[str]:
    """The rows in the view's order (they come most pages first). Views over
    commercial availability: the list's order, then TRL lowest first (not
    known last). Possible nascent: the ones still to settle first."""
    if view in BY_AVAILABILITY:
        order = {a["_id"]: a.get("order", 50) for a in get_collection("availability").find({}, {"order": 1})}
        av, trl = (lambda i: st[i]["classification"]["availability"]["id"]), (lambda i: st[i]["classification"]["trl"]["level"])
        return sorted(ids, key=lambda i: (order.get(av(i), 99), trl(i) or 10))
    if view == "nascent":
        return sorted(ids, key=lambda i: st[i]["classification"]["nascent"]["decision"] is not None)
    return ids


# ── Before scoring (Gate 1) ──────────────────────────────────────────

def gate1(all_states: dict | None = None) -> list[dict]:
    ids = get_collection("technologies").distinct("_id")
    all_s = statuses(ids, all_states)
    techs = {t["_id"]: t for t in get_collection("technologies").find(
        {"_id": {"$in": ids}}, {"name": 1, "label": 1, "enabled": 1, "switched_off_at": 1})}
    name = lambda i: techs[i].get("label") or techs[i]["name"]
    items = []
    nascent = [i for i, s in all_s.items() if s["status"] != "off" and s["classification"]["nascent"]["flag"]
               and s["classification"]["nascent"]["decision"] is None]
    if nascent:
        items.append({"kind": "nascent", "count": len(nascent),
                      "sentence": f"{len(nascent)} possibly nascent {'technology' if len(nascent) == 1 else 'technologies'} to confirm",
                      "sub": "A strong early sign; a person says yes or no. Yes lets it be assessed and moves it to Research or Pilot; No sets it aside until a new page flags it.",
                      "href": "/admin/technologies?view=nascent",
                      "technologies": [{"tech_id": i, "name": name(i),
                                        "note": all_s[i]["classification"]["nascent"]["flag"].get("reason")} for i in nascent]})
    from app.services import imports_gate
    items.extend(imports_gate.items())
    from agent.classifier import classify
    pending = classify.pending()
    if pending:
        items.append({"kind": "classify", "count": len(pending),
                      "sentence": f"{len(pending):,} {'technology has' if len(pending) == 1 else 'technologies have'} new pages not judged yet",
                      "sub": "The Classify step on Operations judges how solid each one's evidence is and sets its domain, "
                             "commercial availability and maturity (TRL): one model call each.",
                      "href": "/admin/operations#classify", "calls": len(pending)})
    ready = [i for i, s in all_s.items() if s["status"] == "ready"]
    if ready:
        cost = estimate(ready)
        items.append({"kind": "ready_to_assess", "count": len(ready), "calls": cost["calls"], "tech_ids": ready,
                      "sentence": f"{len(ready)} {'technology is' if len(ready) == 1 else 'technologies are'} ready to assess",
                      "sub": f"Their evidence was judged enough. About {cost['calls']:,} model calls.",
                      "href": "/admin/technologies?view=not_assessed&status=ready"})
    woke = [i for i, s in all_s.items() if s["status"] == "off" and (i in techs)]
    since = evidence.pages_since_off([techs[i] for i in woke])
    wake = int(radar_settings()["wake_after_pages"])
    woke = [i for i in woke if since.get(i, 0) >= wake]
    if woke:
        items.append({"kind": "switched_off_with_pages", "count": len(woke),
                      "sentence": f"{len(woke)} switched-off {'technology has' if len(woke) == 1 else 'technologies have'} new pages",
                      "sub": f"{wake} or more pages since each was switched off: have a look.",
                      "href": "/admin/technologies?view=off",
                      "technologies": [{"tech_id": i, "name": name(i), "note": _pages(since[i], "new ")} for i in woke]})
    return items
