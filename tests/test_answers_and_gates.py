"""Where each answer came from: Tata's list (an import) is named as such, and
what the radar judged shows beside a person's or Tata's value; an unanswered
nascent flag survives a reading of new pages with no early sign; a Yes on
nascent says what it would replace; switched-off technologies leave Gate 2."""

from fastapi.testclient import TestClient

from agent.classifier import classify
from app.main import app
from app.services import classify_effective, decisions
from factories import page
from test_classify import Model, _world
from test_decisions import _setup

client = TestClient(app)
IMPORTED = {"file": "Tata.xlsx", "at": "2026-10-21T04:32:02+00:00", "tz": "America/Chicago",
            "row": {"name": "Edge AI", "description": "Running models on the device itself."}}


def test_an_unanswered_flag_stands_when_new_pages_show_no_early_sign(db):
    _world(db)
    t = lambda: db["technologies"].find_one({"_id": "edge-ai"})
    classify.classify_one(Model(flag=True), t(), "c1", classify.lists(), 10)
    flag = t()["classification"]["nascent"]
    assert flag and flag["quote"] == "the first field trial began"
    page(db, "new", 9, summary_text="a webinar", source_name="Light Reading")
    classify.classify_one(Model(), t(), "c2", classify.lists(), 10)  # only the new page is read: no early sign
    assert t()["classification"]["nascent"] == flag
    # once a person has answered, a reading with no sign no longer holds it
    decisions.create("nascent", "edge-ai", value="no", tz="UTC")
    page(db, "newer", 10, summary_text="a panel", source_name="Light Reading")
    classify.classify_one(Model(), t(), "c3", classify.lists(), 10)
    assert t()["classification"]["nascent"] is None


def test_an_import_names_tata_s_list_and_shows_what_the_radar_judged(db):
    _world(db)
    lists = classify_effective.names()
    t = db["technologies"].find_one({"_id": "edge-ai"})
    t["classification"] = {"availability": {"value_id": "pilot", "reason": "a named trial", "pages": ["p0@1"]}}
    imp = decisions.create("move", "edge-ai", field="availability", value="early_commercial",
                           reason="Imported from Tata.xlsx", tz="America/Chicago")
    c = classify_effective.effective(t, [imp], lists)
    a = c["availability"]
    assert (a["name"], a["source"], a["imported"]) == ("Early commercial", "person", "Tata.xlsx")
    assert {k: a["radar"][k] for k in ("name", "source", "same", "reason", "pages")} == \
        {"name": "Pilot", "source": "pages", "same": False, "reason": "a named trial", "pages": ["p0@1"]}
    assert c["nascent"]["yes_replaces"] == {"name": "Early commercial", "imported": "Tata.xlsx"}
    # pages that couldn't tell say what's missing
    t["classification"]["trl"] = {"level": None, "reason": "", "missing": "no prototype shown yet", "pages": []}
    level = decisions.create("move", "edge-ai", field="trl", value=6, reason="Imported from Tata.xlsx", tz="UTC")
    r = classify_effective.effective(t, [imp, level], lists)["trl"]["radar"]
    assert (r["name"], r["reason"], r["same"]) == (None, "no prototype shown yet", False)
    # a person's own move is no import; the radar agreeing says so; Pilot is where a Yes goes anyway
    mine = decisions.create("move", "edge-ai", field="availability", value="pilot", tz="UTC")
    c = classify_effective.effective(t, [imp, mine], lists)
    assert c["availability"]["imported"] is None and c["availability"]["radar"]["same"]
    assert c["nascent"]["yes_replaces"] is None


def test_the_summary_carries_tata_s_description_and_the_pages_the_radar_cites(db):
    _world(db)
    db["technologies"].update_one({"_id": "edge-ai"}, {"$set": {
        "imported": IMPORTED, "page_count": 5,
        "classification": {"availability": {"value_id": "pilot", "reason": "a named trial", "pages": ["p0@1"]},
                           "nascent": {"reason": "first trial", "quote": "q", "page": "p0@1"}}}})
    decisions.create("move", "edge-ai", field="availability", value="early_commercial",
                     reason="Imported from Tata.xlsx", tz="America/Chicago")
    s = client.get("/api/technologies/edge-ai/summary").json()
    assert s["technology"]["imported"] == {"file": "Tata.xlsx", "at": IMPORTED["at"], "tz": "America/Chicago",
                                           "description": "Running models on the device itself."}
    assert "p0@1" in s["cited_pages"]
    nascent = {g["kind"]: g for g in client.get("/api/gates").json()["gate1"]}["nascent"]
    assert nascent["technologies"][0]["replaces"] == {"name": "Early commercial", "imported": "Tata.xlsx"}


def test_a_switched_off_technology_leaves_the_before_publishing_list(db):
    _setup(db, {"maturity-trl": 7, "commercial-adoption": 7})  # held, with unscored measures
    assert "unscored" in {g["kind"] for g in client.get("/api/gates").json()["gate2"]}
    db["technologies"].update_one({"_id": "edge-ai"}, {"$set": {"enabled": False}})
    assert client.get("/api/gates").json()["gate2"] == []


def test_moving_the_domain_drops_a_sub_domain_of_the_old_one(db):
    """"Cloud › AI Agents" can't happen: a sub-domain shows only under its own domain."""
    _world(db)
    lists = classify_effective.names()
    t = db["technologies"].find_one({"_id": "edge-ai"})
    sub = next(s for s in lists["subdomains"].values() if s["domain_id"] == "ai")
    t["classification"] = {"domain": {"domain_id": "ai", "subdomain_id": sub["_id"], "reason": "agents", "pages": []}}
    assert classify_effective.effective(t, [], lists)["domain"]["subdomain_id"] == sub["_id"]
    moved = decisions.create("move", "edge-ai", field="domain", value="cloud", tz="UTC")
    d = classify_effective.effective(t, [moved], lists)["domain"]
    assert (d["id"], d["subdomain_id"], d["subdomain"]) == ("cloud", None, None)


def test_proposed_sub_domains_wait_before_scoring(db):
    db["subdomains"].insert_many([{"_id": "ai--x", "name": "X", "domain_id": "ai", "status": "new"},
                                  {"_id": "ai--y", "name": "Y", "domain_id": "ai", "status": "seeded"}])
    item = next(i for i in client.get("/api/gates").json()["gate1"] if i["kind"] == "subdomains")
    assert item["count"] == 1 and item["href"] == "/admin/classification/domains"
    assert item["sentence"] == "1 sub-domain the model proposed, to accept, merge or rename"
