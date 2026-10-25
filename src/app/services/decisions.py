"""People's choices, kept apart from what the model wrote: a run never
overwrites them. One document per choice; a new choice for the same thing
replaces the old one (the old one is kept, inactive), and undo deactivates.

  kind        what it's about                      value                 reason
  move        a technology's field (availability,  the new value         optional
              domain, subdomain, trl)
  override    a technology in a fabric             P1–P6                 required
  hand_score  a measure (technology-scope: every   0–10                  required
              fabric; else one fabric)
  accept_gap  a measure, as above                  true                  —
  tata_entry  a measure Tata enters (scope tata)   0–10                  required
  nascent     a technology the model flagged       yes | no              —
  catalog     a technology: in Tata's catalog      yes | no              —
              (its own list of emerging
              technologies) or not
  use_case    a suggested use case in a fabric     accept | reject       —
  path_step   a technology in a fabric             a path-to-scale step  optional
  finance     a technology in a fabric             {upfront, running,    —
                                                    revenue | volume and
                                                    price, displaced,
                                                    margin, loss rates,
                                                    mechanism, and the
                                                    rungs' notes: buyer,
                                                    budget, exposed
                                                    contracts, cost per
                                                    outcome} (services/
                                                    finance)
  bottlenecks a technology in a fabric             {picked: from the     optional
                                                    fabric's blockers,
                                                    other: text}
  commitment  a technology in a fabric: what a     {owner, next_action,  optional
              leader records (deck p.13); never     due: a date, and the
              changes a score                       resources: people,
                                                    budget, poc}
  watch_threshold  a sign to watch (`key`: its      the threshold, in     optional
              wording's key, services/watch)        words
  watch_crossed    a sign to watch, as above        no (it hasn't         optional
                                                    crossed, whatever the
                                                    model said)

What a leader records sets the state Frontier shows (leader_state): Undefined
(no owner yet), Defined (an owner and a next action), Aligned (the path step
and the bottlenecks recorded too), Integrated (resources recorded too).
"""

import uuid
from datetime import date

from app.services.db.mongo import get_collection
from app.services.timezone import now_utc

PRIORITIES = {f"P{n}" for n in range(1, 7)}
MOVE_FIELDS = {"availability", "domain", "subdomain", "trl"}
REASON_REQUIRED = {"override", "hand_score", "tata_entry"}
# a finance choice's inputs (services/finance): amounts, shares from 0 to 1, and the rungs' notes
FINANCE_AMOUNTS = ("upfront", "running", "revenue", "volume", "price", "displaced")
FINANCE_SHARES = ("margin", "loss_without", "loss_with")
FINANCE_NOTES = ("buyer", "budget", "exposed_contracts", "cost_per_outcome")
# what a leader records: who answers for it, the next action and its date, then the resources committed
COMMITMENT_FIELDS = ("owner", "next_action", "due", "people", "budget", "poc")
RESOURCES = {"people": "people", "budget": "budget", "poc": "a proof of concept"}


class Refused(ValueError):
    """A choice that can't be recorded; the message says why, in plain words."""


def _measure(measure_id: str | None) -> dict:
    m = get_collection("measures").find_one({"_id": measure_id}) if measure_id else None
    if m is None:
        raise Refused(f"unknown measure {measure_id!r}")
    return m


def _score(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 10:
        raise Refused("a score is a number from 0 to 10")
    return round(float(value), 1)


def _check(kind: str, d: dict) -> dict:
    """The choice, checked and normalised for its kind; raises Refused."""
    t = get_collection("technologies").find_one({"_id": d["tech_id"]},
                                                {"classification.nascent": 1, "imported": 1, "origin": 1})
    if not t:
        raise Refused(f"unknown technology {d['tech_id']!r}")
    if kind in REASON_REQUIRED and not (d.get("reason") or "").strip():
        raise Refused("say why: a reason is required, so others can see what this rests on")
    v = d.get("value")
    if kind == "move":
        if d.get("field") not in MOVE_FIELDS:
            raise Refused(f"a move changes one of: {', '.join(sorted(MOVE_FIELDS))}")
        if d["field"] == "trl" and (isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 9):
            raise Refused("TRL is a whole number from 1 to 9")
        if d["field"] != "trl" and not (isinstance(v, str) and v.strip()):
            raise Refused("choose a value from the list")
    elif kind == "override":
        if not d.get("fabric_id"):
            raise Refused("an override is for one fabric")
        if v not in PRIORITIES:
            raise Refused("a priority is one of P1 to P6")
    elif kind in ("hand_score", "accept_gap", "tata_entry"):
        m = _measure(d.get("measure_id"))
        scope = m.get("scope") or "fabric"
        if kind == "tata_entry" and scope != "tata":
            raise Refused(f"{m.get('name')} is scored from the pages, not entered by Tata: score it by hand instead")
        if kind == "hand_score" and scope == "tata":
            raise Refused(f"{m.get('name')} is entered by Tata: use Enter instead")
        # a technology-wide measure is the same in every fabric, so the choice is too
        d["fabric_id"] = None if scope == "technology" else d.get("fabric_id")
        if scope != "technology" and not d["fabric_id"]:
            raise Refused(f"{m.get('name')} is judged per fabric: say which fabric")
        d["value"] = True if kind == "accept_gap" else _score(v)
    elif kind == "nascent":
        if v not in ("yes", "no"):
            raise Refused("answer yes or no")
        if not (t.get("classification") or {}).get("nascent"):
            raise Refused("the model hasn't flagged it as possibly nascent")
    elif kind == "catalog":
        if v not in ("yes", "no"):
            raise Refused("add it to the catalog (yes) or take it out (no)")
        if in_catalog(t, pick(active([t["_id"]], ["catalog"]), "catalog"))["in"] == (v == "yes"):
            raise Refused("it's already in the catalog" if v == "yes" else "it isn't in the catalog")
    elif kind == "use_case":
        if v not in ("accept", "reject") or not d.get("key") or not d.get("fabric_id"):
            raise Refused("accept or reject one suggested use case, in one fabric")
    elif kind == "watch_threshold":
        if not d.get("key") or not (isinstance(v, str) and v.strip()) or len(v) > 1000:
            raise Refused("a threshold is about one sign to watch, in words (up to 1,000 characters)")
        d["value"] = v.strip()
    elif kind == "watch_crossed":
        if not d.get("key") or v != "no":
            raise Refused("say that one sign to watch hasn't crossed (no)")
    elif kind == "path_step":
        if not d.get("fabric_id") or not (isinstance(v, str) and v):
            raise Refused("a path-to-scale step is for one fabric")
        if get_collection("path_steps").find_one({"_id": v}, {"_id": 1}) is None:
            raise Refused(f"unknown path-to-scale step {v!r}")
    elif kind == "finance":
        if not d.get("fabric_id") or not isinstance(v, dict):
            raise Refused("finance inputs are for one fabric")
        clean = {}
        for k in (*FINANCE_AMOUNTS, *FINANCE_SHARES):
            x = v.get(k)
            if x is None or x == "":
                continue
            if isinstance(x, bool) or not isinstance(x, (int, float)) or x < 0 or (k in FINANCE_SHARES and x > 1):
                raise Refused(f"{k} must be a number of at least 0" + (" and at most 1 (a share)" if k in FINANCE_SHARES else ""))
            clean[k] = float(x)
        for k in FINANCE_NOTES:
            if str(v.get(k) or "").strip():
                clean[k] = str(v[k]).strip()[:1000]
        if v.get("mechanism") not in (None, "", "protect", "earn"):
            raise Refused("the revenue counts as protected (protect) or new (earn)")
        if v.get("mechanism"):
            clean["mechanism"] = v["mechanism"]
        d["value"] = clean
    elif kind == "bottlenecks":
        if not d.get("fabric_id") or not isinstance(v, dict):
            raise Refused("execution bottlenecks are picked for one fabric")
        listed = (get_collection("fabrics").find_one({"_id": d["fabric_id"]}, {"bottlenecks": 1}) or {}).get("bottlenecks") or []
        picked = [b for b in v.get("picked") or [] if isinstance(b, str)]
        if unknown := [b for b in picked if b not in listed]:
            raise Refused(f"not on this fabric's list of blockers: {', '.join(unknown)}. Write it under other instead")
        other = str(v.get("other") or "").strip()[:500]
        if not picked and not other:
            raise Refused("pick at least one blocker from the list, or write another")
        d["value"] = {"picked": [b for b in listed if b in picked], "other": other}
    elif kind == "commitment":
        if not d.get("fabric_id") or not isinstance(v, dict):
            raise Refused("what a leader records is for one fabric")
        clean = {k: str(v.get(k) or "").strip()[:500] for k in COMMITMENT_FIELDS if str(v.get(k) or "").strip()}
        missing = [w for k, w in (("owner", "the owner"), ("next_action", "the next action"), ("due", "its date"))
                   if k not in clean]
        if missing:
            raise Refused(f"a record needs an owner, a next action and its date: {' and '.join(missing)} "
                          f"{'is' if len(missing) == 1 else 'are'} missing")
        try:
            clean["due"] = date.fromisoformat(clean["due"]).isoformat()
        except ValueError:
            raise Refused("the next action's date is a day, like 2026-11-15")
        d["value"] = clean
    else:
        raise Refused(f"unknown kind of choice {kind!r}")
    return d


def _key(d: dict) -> dict:
    """What makes two choices about the same thing."""
    return {"kind": d["kind"], "tech_id": d["tech_id"], "fabric_id": d.get("fabric_id"),
            "measure_id": d.get("measure_id"), "field": d.get("field"), "key": d.get("key")}


def create(kind: str, tech_id: str, *, value=None, fabric_id: str | None = None, measure_id: str | None = None,
           field: str | None = None, key: str | None = None, reason: str | None = None, tz: str,
           computed: str | None = None, extra: dict | None = None) -> dict:
    d = _check(kind, {"kind": kind, "tech_id": tech_id, "fabric_id": fabric_id, "measure_id": measure_id,
                      "field": field, "key": key, "value": value, "reason": (reason or "").strip() or None})
    coll = get_collection("decisions")
    coll.update_many({**_key(d), "active": True}, {"$set": {"active": False, "replaced_at": now_utc()}})
    doc = {"_id": uuid.uuid4().hex[:12], **d, "computed": computed, "at": now_utc(), "tz": tz, "by": None, "active": True,
           **({"extra": extra} if extra else {})}
    coll.insert_one(doc)
    return doc


def deactivate(decision_id: str, tz: str) -> dict | None:
    return get_collection("decisions").find_one_and_update(
        {"_id": decision_id, "active": True},
        {"$set": {"active": False, "undone_at": now_utc(), "undone_tz": tz}}, return_document=True)


def active(tech_ids: list[str] | None = None, kinds: list[str] | None = None) -> list[dict]:
    query: dict = {"active": True}
    if tech_ids is not None:
        query["tech_id"] = {"$in": tech_ids}
    if kinds:
        query["kind"] = {"$in": kinds}
    return list(get_collection("decisions").find(query).sort("at", 1))


def by_tech(decs: list[dict]) -> dict[str, list[dict]]:
    """Choices grouped by technology, each group still oldest first: read once,
    so a loop over many technologies doesn't scan every choice for each."""
    out: dict[str, list[dict]] = {}
    for d in decs:
        out.setdefault(d["tech_id"], []).append(d)
    return out


def pick(decs: list[dict], kind: str, **match) -> dict | None:
    """The newest of these choices (`active` lists them oldest first) of this
    kind whose fields equal `match`. A choice with no fabric is about the
    technology as a whole, so it matches any fabric."""
    return next((d for d in reversed(decs) if d["kind"] == kind and all(
        d.get(k) == v or (k == "fabric_id" and d.get(k) is None) for k, v in match.items())), None)


def in_catalog(tech: dict, choice: dict | None) -> dict:
    """Whether a technology is in Tata's catalog (its own list of emerging
    technologies): a person's add or take-out first, else whether an import
    added or matched it (both keep the `imported` record)."""
    if choice:
        return {"in": choice["value"] == "yes", "decision_id": choice["_id"], "at": choice["at"], "tz": choice.get("tz")}
    return {"in": bool(tech.get("imported")) or tech.get("origin") == "imported", "decision_id": None}


def leader_state(decs: list[dict], tech_id: str, fabric_id: str) -> dict:
    """What a leader has recorded for a technology in a fabric and the state
    it follows, each step needing the one before: undefined, defined (an
    owner and a next action), aligned (the step reached and the blockers
    recorded too), integrated (resources too). `needs` says what the next
    state still needs, in words; `decision` is the record (for Undo)."""
    rec = pick(decs, "commitment", tech_id=tech_id, fabric_id=fabric_id)
    v = (rec or {}).get("value") or {}
    unaligned = [w for k, w in (("path_step", "the step Tata has reached"), ("bottlenecks", "the blockers"))
                 if not pick(decs, k, tech_id=tech_id, fabric_id=fabric_id)]
    if not rec:
        state, needs = "undefined", "an owner and a next action, with its date"
    elif unaligned:
        state, needs = "defined", f"{' and '.join(unaligned)} recorded"
    elif not any(v.get(k) for k in RESOURCES):
        state, needs = "aligned", "resources: people, budget or a proof of concept"
    else:
        state, needs = "integrated", None
    return {"state": state, "needs": needs, **{k: v.get(k) for k in COMMITMENT_FIELDS},
            "decision": {k: rec.get(k) for k in ("_id", "at", "tz", "reason")} if rec else None}
