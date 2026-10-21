"""A technology's classification as the radar uses it: a person's choice
first (a move, an import, a yes on nascent), then what its assessment
judged from the full evidence, then what Classify read on its pages, then
the catch-all. Each answer says where it came from; how solid the evidence
is comes from Classify only."""

from app.services import decisions
from app.services.db.mongo import get_collection

# where an answer came from, in the words a Point of View uses
SOURCE_WORDS = {"person": "set by a person", "assessment": "judged by its assessment", "pages": "judged from its pages",
                "none": "not known"}


def names() -> dict:
    """Display names for the lists' ids."""
    return {"availability": {a["_id"]: a for a in get_collection("availability").find()},
            "domains": {d["_id"]: d for d in get_collection("domains").find()},
            "subdomains": {s["_id"]: s for s in get_collection("subdomains").find()},
            "trl": {t["level"]: t for t in get_collection("trl_levels").find()}}


def meta(source: str, reason=None, pages=None, at=None, tz=None, decision_id=None) -> dict:
    """Where an answer came from, as every answer carries it."""
    return {"source": source, "reason": reason, "pages": pages or [], "at": at, "tz": tz, "decision_id": decision_id}


IMPORTED = "Imported from "  # the reason an import (services/imports.confirm) gives each value it records
EARLY = ("research", "pilot")  # where a Yes on possibly nascent moves commercial availability


def imported_from(decision: dict | None) -> str | None:
    """The file a choice came from when an import recorded it (Tata's list);
    None for a person's own move."""
    reason = (decision or {}).get("reason") or ""
    return reason[len(IMPORTED):] if reason.startswith(IMPORTED) else None


def effective(tech: dict, decs: list[dict], lists: dict) -> dict:
    mine = [d for d in decs if d["tech_id"] == tech["_id"]]
    assessed = tech.get("assessed_classification") or {}
    pages = tech.get("classification") or {}

    def pick(field: str, key: str, name_of) -> tuple:
        """(the value's id, the answer it's from, where from): a person's move
        (or an import's), then the assessment, then the pages. Under a move,
        `imported` names the file it came from, and `radar` is what the
        assessment or the pages judged, with its reason and pages (name None:
        they couldn't tell, and the reason says what's missing)."""
        judged = [(src, c) for src, c in (("assessment", assessed.get(field)), ("pages", pages.get(field))) if c]
        moved = decisions.pick(mine, "move", field=field)
        if moved:
            src, c = next(((s, c) for s, c in judged if c.get(key) is not None), judged[0] if judged else (None, None))
            v = (c or {}).get(key)
            radar = {"value": v, "name": None if v is None else name_of(v), "same": v == moved["value"],
                     **meta(src, c.get("reason") or c.get("missing"), c.get("pages"), c.get("at"))} if c else None
            return moved["value"], {}, {**meta("person", moved.get("reason"), None, moved["at"], moved.get("tz"),
                                               moved["_id"]), "imported": imported_from(moved), "radar": radar}
        if judged:
            src, c = judged[0]
            return c.get(key), c, meta(src, c.get("reason"), c.get("pages"), c.get("at"))
        return None, {}, meta("none")

    av_id, _, av = pick("availability", "value_id", lambda v: lists["availability"].get(v, {}).get("name", v))
    catch = next((a["_id"] for a in lists["availability"].values() if a.get("catch_all")), "unclassified")
    shown = lists["availability"].get(av_id or catch, {})
    availability = {"id": av_id or catch, "name": shown.get("name", "Unclassified"), **av,
                    "emerging": bool(shown.get("emerging"))}

    dom_id, answer, dm = pick("domain", "domain_id", lambda v: lists["domains"].get(v, {}).get("name", v))
    sub_move = decisions.pick(mine, "move", field="subdomain")
    sub_id = sub_move["value"] if sub_move else answer.get("subdomain_id")
    other = next((d["_id"] for d in lists["domains"].values() if d.get("catch_all")), "other")
    sub = lists["subdomains"].get(sub_id) or ({"name": sub_id[4:], "status": "new"} if str(sub_id or "").startswith("new:") else {})
    if sub.get("domain_id") and sub["domain_id"] != dom_id:
        sub_id, sub = None, {}  # a sub-domain of another domain: the domain was moved since, so none is shown
    domain = {"id": dom_id or other, "name": lists["domains"].get(dom_id or other, {}).get("name", "Other"),
              "subdomain_id": sub_id, "subdomain": sub.get("name") or answer.get("subdomain_new"),
              "subdomain_new": sub.get("status") == "new", **dm}

    level, answer, tr = pick("trl", "level", lambda v: f"TRL {v}")
    trl = {"level": level, "name": lists["trl"].get(level, {}).get("name") if level else None,
           **tr, "source": tr["source"] if level else "none", "missing": answer.get("missing")}

    ev = pages.get("evidence")
    nascent_decision = decisions.pick(mine, "nascent")
    flag = pages.get("nascent")
    if nascent_decision and nascent_decision["value"] == "no" and flag and \
            flag.get("page") not in (nascent_decision.get("extra") or {}).get("pages_known", []):
        nascent_decision = None  # a page it hadn't seen flags it again
    return {"availability": availability, "domain": domain, "trl": trl,
            "evidence": ({k: ev.get(k) for k in ("verdict", "reason", "pages", "read", "of", "sources", "at")} if ev else None),
            "nascent": {"flag": flag, "decision": nascent_decision["value"] if nascent_decision else None,
                        "decision_id": nascent_decision["_id"] if nascent_decision else None,
                        "at": nascent_decision["at"] if nascent_decision else None,
                        "tz": nascent_decision.get("tz") if nascent_decision else None,
                        # a Yes moves availability to Research or Pilot (api/decisions): what it would replace
                        "yes_replaces": {"name": availability["name"], "imported": availability.get("imported")}
                        if availability["source"] == "person" and availability["id"] not in EARLY else None},
            "classified_at": pages.get("at")}
