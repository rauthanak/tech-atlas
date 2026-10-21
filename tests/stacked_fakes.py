"""Seeded configuration and a stand-in model for the stacked-call tests."""

import json
import re
from pathlib import Path

SEEDS = Path(__file__).parents[1] / "seeds"


def load_seeded(db, *names):
    """Load these seeded lists into the test database, as boot would."""
    from app.services.db.seeding import ID_FIELDS
    for name in names:
        items = json.loads((SEEDS / f"{name}.json").read_text())[name]
        db[name].insert_many([{"_id": i[ID_FIELDS[name]], **i} for i in items])


class StackedModel:
    """Answers a stacked call by its keys ('Its keys are exactly: a, b.'),
    and a single measure call with one measure answer. `drop` leaves keys out
    of stacked replies; `gates` is the fabric choice."""

    def __init__(self, gates=("cloud", "network"), drop=(), score=6):
        self.gates, self.drop, self.score = list(gates), set(drop), score
        self.calls: list[dict] = []

    def measure(self):
        return {"score": self.score, "justification": "the evidence shows it", "evidence_urls": ["https://a"],
                "counter_case": "c", "unscorable": False, "missing": None}

    def ask(self, prompt, system=None, *, blocks=None):
        self.calls.append({"prompt": prompt, "blocks": blocks})
        text = "\n".join([*(blocks or []), prompt])
        keys = re.search(r"Its keys are exactly: (.*?)\. Under", text)
        if keys:
            out = {}
            for k in keys.group(1).split(", "):
                if k in self.drop:
                    continue
                out[k] = ({"fabrics": self.gates} if k == "fabric_relevance" else
                          [{"metric": "m", "current_value": "v"}] if k == "watch_metrics" else self.measure())
            return json.dumps(out)
        if "watch" in text.lower() and "turning point" in text.lower():
            return json.dumps([{"metric": "m", "current_value": "v"}])
        if '"fabrics"' in text and "FABRICS:" in text:
            return json.dumps({"fabrics": self.gates})
        return json.dumps(self.measure())
