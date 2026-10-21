"""The radar's own settings (settings document `radar`): the time zone shown
when a write didn't say one, when a switched-off technology asks for a look,
the evidence floor before classification, and the budgets of Classify and
Find evidence. Any key the stored document lacks comes from the seeding data."""

from app.services.db import seeding
from app.services.db.mongo import get_collection


def radar_settings() -> dict:
    seed = next(s for s in seeding.read_list("settings") if s["name"] == "radar")
    stored = get_collection("settings").find_one({"_id": "radar"}) or {}
    return {**seed, **{k: v for k, v in stored.items() if k not in ("_id", "updated_at")}}
