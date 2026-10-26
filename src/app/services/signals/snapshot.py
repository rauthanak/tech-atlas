"""The run snapshot: the signal list and crawl settings a run uses. Read
once when a run (or a re-check) starts and recorded on it, so edits made
meanwhile apply from the next run.

signals_hash identifies a version of the list: a page checked against a
different hash (or none) is stale and is offered for re-check."""

import hashlib

from app.services.db import seeding
from app.services.db.mongo import get_collection


def enabled_signals() -> list[dict]:
    return list(get_collection("signals").find(
        {"enabled": True}, {"_id": 1, "signal_id": 1, "name": 1, "look_for": 1, "mode": 1})
        .sort("_id", 1))


def signals_hash(rows: list[dict]) -> str:
    lines = sorted(f"{r['_id']}|{r['name']}|{r['look_for']}|{r['mode']}" for r in rows)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:12]


def current_hash() -> str:
    return signals_hash(enabled_signals())


def crawl_settings() -> dict:
    """The crawl settings; any the stored document lacks (never expected
    after start-up) come from the seeding data."""
    seed = next(s for s in seeding.read_list("settings") if s["name"] == "crawl")
    return {"_id": "crawl", **seed, **(get_collection("settings").find_one({"_id": "crawl"}) or {})}


def build() -> dict:
    """What a run records about the configuration it used."""
    rows = enabled_signals()
    return {"signal_list": rows, "signals_hash": signals_hash(rows),
            "crawl_settings": {k: v for k, v in crawl_settings().items()
                               if k not in ("_id", "updated_at", "updated_by")}}


def prompt_lines(rows: list[dict]) -> dict:
    """The signal list as the summarizing and link-selection prompts read it."""
    def lines(mode: str) -> str:
        chosen = [f"- {r['name']}: {r['look_for']}" for r in rows if r["mode"] == mode]
        return "\n".join(chosen) or "(none)"
    return {
        "never_miss": lines("never_miss"),
        "can_ignore": lines("can_ignore"),
        "never_miss_names": "\n".join(f"- {r['name']}" for r in rows
                                      if r["mode"] == "never_miss") or "(none)",
    }
