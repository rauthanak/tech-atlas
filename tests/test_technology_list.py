"""The Technologies list over Tata's commercial availability buckets: in
the catalog means imported or matched, unless a person took it out (or a
person added it); each filter's counts leave out only
its own choice; the views over availability list the earliest values first;
"select all" gets every id; Setup counts the same way the list does."""

from fastapi.testclient import TestClient

from app.main import app
from app.services import decisions
from factories import tech
from stacked_fakes import load_seeded

client = TestClient(app)


def _classified(db, tech_id: str, availability: str | None, trl: int | None = None, domain: str = "ai",
                subdomain: str | None = None, pages: int = 3, **extra) -> None:
    tech(db, tech_id, tech_id.replace("-", " "))
    cls = {"domain": {"domain_id": domain, "subdomain_id": subdomain}}
    if availability:
        cls["availability"] = {"value_id": availability, "reason": "r", "pages": []}
    if trl:
        cls["trl"] = {"level": trl, "reason": "r", "pages": []}
    db["technologies"].update_one({"_id": tech_id}, {"$set": {"classification": cls, "page_count": pages,
                                                              "doc_count": pages, **extra}})


def _world(db):
    load_seeded(db, "availability", "domains", "subdomains", "trl_levels")
    _classified(db, "mature-new", "mature", 8, pages=9)                    # found by the radar only
    _classified(db, "mature-matched", "mature", 9, pages=8,                # matched to a row of Tata's list
                imported={"import_id": "i1", "file": "tata.xlsx"})
    _classified(db, "pilot-high", "pilot", 6, subdomain="ai--ai_agents", pages=7)
    _classified(db, "pilot-low", "pilot", 4, subdomain="ai--ai_agents", pages=6)
    _classified(db, "research", "research", 2, domain="quantum", pages=5)
    tech(db, "imported-new", "imported new")                               # added by an import, no pages
    db["technologies"].update_one({"_id": "imported-new"}, {"$set": {"origin": "imported",
                                                                     "imported": {"import_id": "i1", "file": "tata.xlsx"}}})


def test_a_matched_technology_is_in_the_catalog(db):
    _world(db)
    body = client.get("/api/technologies").json()
    assert body["view_counts"]["mature_not_on_tata"] == 1 and body["view_counts"]["mature"] == 2
    ids = lambda **p: [t["_id"] for t in client.get("/api/technologies", params=p).json()["technologies"]]
    assert ids(view="mature_not_on_tata") == ["mature-new"]
    assert "mature-matched" not in ids(view="emerging_new") and set(ids(catalog="yes")) == {"mature-matched", "imported-new"}
    assert body["facets"]["catalog"] == {"yes": 2, "no": 4}
    assert "imported-new" in ids(view="emerging")  # one in the catalog with no value yet counts as emerging


def test_a_person_adds_one_to_the_catalog_or_takes_one_out_and_undo_puts_it_back(db):
    _world(db)
    db["imports"].insert_one({"_id": "i1", "file": "tata.xlsx", "confirmed_at": "2026-10-21T04:32:06+00:00",
                              "tz": "America/Chicago", "status": "ready"})
    ids = lambda **p: [t["_id"] for t in client.get("/api/technologies", params=p).json()["technologies"]]
    post = lambda tid, v: client.post("/api/decisions", json={"kind": "catalog", "tech_id": tid, "value": v})
    assert post("mature-new", "yes").status_code == 201        # a blind spot Tata now tracks
    out = post("mature-matched", "no")
    assert out.status_code == 201
    assert ids(view="mature_not_on_tata") == ["mature-matched"]
    body = client.get("/api/technologies").json()
    assert body["catalog"] == {"files": [{"file": "tata.xlsx", "at": "2026-10-21T04:32:06+00:00", "tz": "America/Chicago",
                                          "technologies": 2}], "emptied": 0, "added": 1, "taken_out": 1}
    row = next(t for t in body["technologies"] if t["_id"] == "mature-new")
    assert row["catalog"]["in"] and row["catalog"]["decision_id"]
    assert post("mature-new", "yes").json()["detail"] == "it's already in the catalog"
    assert post("pilot-low", "no").json()["detail"] == "it isn't in the catalog"
    client.delete(f"/api/decisions/{out.json()['decision']['_id']}")
    assert ids(view="mature_not_on_tata") == []


def test_nascent_is_answered_only_for_one_the_model_flagged(db):
    _world(db)
    r = client.post("/api/decisions", json={"kind": "nascent", "tech_id": "pilot-low", "value": "yes"})
    assert r.status_code == 422 and r.json()["detail"] == "the model hasn't flagged it as possibly nascent"


def test_emerging_lists_the_earliest_values_first_then_the_lowest_trl(db):
    _world(db)
    ids = [t["_id"] for t in client.get("/api/technologies", params={"view": "emerging"}).json()["technologies"]]
    assert ids == ["research", "pilot-low", "pilot-high", "imported-new"]  # Research, Pilot (TRL 4, 6), then not known


def test_each_filters_counts_leave_out_only_its_own_choice(db):
    _world(db)
    body = client.get("/api/technologies", params={"availability": "pilot", "view": "emerging"}).json()
    assert body["total"] == 2
    assert body["facets"]["availability"] == {"research": 1, "pilot": 2, "unclassified": 1}  # the view, not the bucket
    assert body["facets"]["domain"] == {"ai": 2}
    assert body["facets"]["trl"] == {"4": 1, "6": 1}
    assert "subdomain" not in body["facets"]  # only within a chosen domain
    assert body["status_counts"] == {"ready": 2}  # the rows of this view and these filters, not the register
    sub = client.get("/api/technologies", params={"domain": "ai", "subdomain": "ai--ai_agents"}).json()
    assert sub["total"] == 2
    assert {s["id"]: s["n"] for s in sub["facets"]["subdomain"]} == {"ai--ai_agents": 2, "none": 2}
    assert sub["facets"]["subdomain"][0]["name"] == "AI Agents"


def test_select_all_gets_every_id_of_the_view_past_the_page(db):
    _world(db)
    body = client.get("/api/technologies", params={"view": "emerging", "limit": 1, "ids_only": True}).json()
    assert body == {"ids": ["research", "pilot-low", "pilot-high", "imported-new"], "total": 4}


def test_setup_counts_the_classification_the_list_uses(db):
    _world(db)
    decisions.create("move", "research", field="availability", value="mature", tz="UTC")  # a person's move wins
    counts = {i["_id"]: i["technologies"] for i in client.get("/api/lists/availability").json()["items"]}
    assert counts == {"research": 0, "pilot": 2, "early_commercial": 0, "mature": 3, "unclassified": 1}
    listed = client.get("/api/technologies").json()["facets"]["availability"]
    assert all(listed.get(k, 0) == n for k, n in counts.items())
    trl = {i["level"]: i["technologies"] for i in client.get("/api/lists/trl_levels").json()["items"]}
    assert (trl[2], trl[4], trl[9]) == (1, 1, 1)


def test_a_nascent_flag_brings_its_page(db):
    _world(db)
    db["documents"].insert_one({"_id": "d1", "title": "First field trial", "end_url": "https://x/1",
                                "source_name": "Light Reading", "published_date": "2026-10-01"})
    db["technologies"].update_one({"_id": "research"}, {"$set": {"classification.nascent": {
        "reason": "a first trial", "quote": "the first field trial began", "page": "d1"}}})
    body = client.get("/api/technologies", params={"view": "nascent"}).json()
    assert [t["_id"] for t in body["technologies"]] == ["research"]
    assert body["cited_pages"]["d1"]["url"] == "https://x/1"


def test_merging_proposed_subdomains_moves_them_and_undo_puts_them_back(db):
    """Domains › bulk Merge: technologies move and the counts follow; Undo
    brings the sub-domains, their technologies and the people's choices back.
    Bulk Accept and its Undo set the status."""
    _world(db)
    for sid in ("ai--bots", "ai--helpers"):
        db["subdomains"].insert_one({"_id": sid, "subdomain_id": sid, "name": sid[4:], "domain_id": "ai", "status": "new"})
    _classified(db, "bot-one", "pilot", subdomain="ai--bots")
    db["technologies"].update_one({"_id": "bot-one"}, {"$set": {"classification.domain.subdomain_new": True}})
    _classified(db, "helper-one", "pilot", subdomain="ai--helpers")
    db["decisions"].insert_one({"_id": "d1", "kind": "move", "field": "subdomain", "value": "ai--helpers",
                                "active": True, "tech_id": "helper-one"})
    count = lambda sid: {i["_id"]: i["technologies"] for i in client.get("/api/lists/subdomains").json()["items"]}.get(sid)  # noqa: E731

    out = client.post("/api/lists/subdomains/merge", json={"ids": ["ai--bots", "ai--helpers"], "into": "ai--ai_agents"}).json()
    assert (out["merged"], out["technologies_moved"]) == (2, 2)
    assert db["subdomains"].count_documents({"_id": {"$in": ["ai--bots", "ai--helpers"]}}) == 0
    assert count("ai--ai_agents") == 4
    assert db["decisions"].find_one({"_id": "d1"})["value"] == "ai--ai_agents"

    back = client.post("/api/lists/subdomains/unmerge", json=out["undo"]).json()
    assert back == {"put_back": 2, "technologies_moved_back": 2}
    assert count("ai--ai_agents") == 2 and count("ai--bots") == 1
    assert db["technologies"].find_one({"_id": "bot-one"})["classification"]["domain"]["subdomain_new"] is True
    assert db["decisions"].find_one({"_id": "d1"})["value"] == "ai--helpers"

    assert client.post("/api/lists/subdomains/status", json={"ids": ["ai--bots", "ai--helpers"], "status": "seeded"}).json() == {"changed": 2}
    assert client.post("/api/lists/subdomains/status", json={"ids": ["ai--bots"], "status": "new"}).json() == {"changed": 1}
    assert db["subdomains"].find_one({"_id": "ai--bots"})["status"] == "new"
