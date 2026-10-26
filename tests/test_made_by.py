"""Who did what: a choice, a setting change, an import, a publish and a run
record the signed-in person; a job records the person who started it, in
the worker or in a thread; `updated_by` is never a setting change itself."""

import threading

from fastapi.testclient import TestClient

import test_editions as editions_world
import test_imports as imports_world
from app.main import app
from app.services import auth, jobs
from app.services.db import seeding
from app.settings import get_settings
from factories import tech
from stacked_fakes import load_seeded

client = TestClient(app)
ADMIN = {"email": "admin@test.example", "name": "Test admin"}
HASAN = {"email": "hasan@example.org", "name": "Hasan Pasha"}


def test_a_choice_and_its_undo_say_who(db):
    load_seeded(db, "availability")
    tech(db, "edge-ai", "edge ai")
    r = client.post("/api/decisions", json={"kind": "move", "tech_id": "edge-ai", "field": "availability",
                                            "value": "mature"})
    assert r.status_code == 201, r.text
    made = db["decisions"].find_one()
    assert made["by"] == ADMIN
    client.delete(f"/api/decisions/{made['_id']}")
    assert db["decisions"].find_one()["undone_by"] == ADMIN


def test_a_setting_change_says_who_and_isnt_a_change_by_itself(db):
    seeding.load_if_new()
    item = seeding.read_list("availability")[0]
    r = client.put(f"/api/lists/availability/{item['availability_id']}", json={"name": item["name"] + " (edited)"})
    assert r.status_code == 200, r.text
    rows = seeding.changes()["items"]
    assert [(c["id"], c["updated_by"]) for c in rows] == [(item["availability_id"], ADMIN)]
    assert [f["field"] for f in rows[0]["fields"]] == ["name"]            # updated_by is not a difference
    client.put(f"/api/lists/availability/{item['availability_id']}", json={"name": item["name"]})
    assert seeding.changes()["count"] == 0                                 # back as seeded, despite updated_by


def test_an_import_says_who_uploaded_and_confirmed(db, monkeypatch):
    imports_world._world(db, monkeypatch)
    imp = imports_world.upload(imports_world.book([["Edge AI", "AI", "Edge AI", "d", "6", "Early Commercial"]])).json()
    assert client.post(f"/api/imports/{imp['_id']}/confirm").status_code == 200
    stored = db["imports"].find_one({"_id": imp["_id"]})
    assert stored["by"] == stored["confirmed_by"] == ADMIN


def test_a_publish_says_who(db):
    editions_world._world(db)
    e = client.post("/api/editions").json()["edition"]
    assert e["by"] == ADMIN and client.get("/api/editions").json()["editions"][0]["by"] == ADMIN


def test_a_run_record_says_who_started_it(db):
    from app.services.runs import store
    with auth.acting_as(HASAN):
        run_id = store.create_run({"kind": "collection"}, {})
    assert db["runs"].find_one({"_id": run_id})["by"] == HASAN
    assert db["runs"].find_one({"_id": store.create_run({"kind": "collection"}, {})})["by"] is None   # the radar's own


SEEN: list = []


def remember(_arg):
    SEEN.append(auth.by())


def test_the_worker_runs_a_job_as_the_person_who_started_it(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "jobs_in_worker", True)
    SEEN.clear()
    with auth.acting_as(HASAN):
        jobs.start(remember, "x")
    job = jobs.take("w1")
    assert job["by"] == HASAN
    jobs.run(job)
    assert SEEN == [HASAN] and auth.by() is None


def test_a_job_in_a_thread_sees_the_person_too(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "jobs_in_worker", False)
    SEEN.clear()
    done = threading.Event()
    monkeypatch.setattr(jobs.threading, "Thread", _thread_then(done))
    with auth.acting_as(HASAN):
        jobs.start(remember, "x")
    assert done.wait(5) and SEEN == [HASAN]


def _thread_then(done):
    real = threading.Thread

    class Thread(real):
        def run(self):
            super().run()
            done.set()
    return Thread
