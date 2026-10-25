"""After the API is redeployed with the watch-check and market-figure code:
the metrics-to-watch skill (v3) checks the previous metrics, the measure skill
can return the market figure a measure rests on, and Addressable market asks
for it. Live through the API, then kept as the defaults (update-seeding-data)."""

import json
import urllib.request

API = "http://localhost:8100/api"


def call(path, body=None, method="GET"):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"content-type": "application/json"})
    return json.load(urllib.request.urlopen(req))


def sub(s, a, b):
    assert s.count(a) == 1, a[:60]
    return s.replace(a, b)


prompts = {p["_id"]: p for p in call("/prompts")["prompts"]}

w = prompts["watch_metrics"]
w_prompt = (
    "Keep track of the indicators that would signal a turning point for this technology: measurable things that, "
    "if they crossed a threshold, would change how ready or how important it is for Tata (Tata Communications; "
    "never write TCL).\n\nTECHNOLOGY: {technology}\n\n"
    "METRICS SET AT ITS LAST ASSESSMENT (check each against the evidence):\n{previous}\n\n"
    "EVIDENCE:\n{evidence}\n\n"
    "First carry forward each metric above that still tells the story: keep its metric and threshold word for word, "
    "put its value then in previous_value, and give today's value from the evidence with the URL that shows it as "
    "source. Set crossed to true only when a page in the evidence shows the threshold passed, false when a page shows "
    "a newer value short of it, and null when no page gives a newer value (then repeat the value then as "
    "current_value, with source null). Then add new metrics so there are 2 to 4 in all; a new one has "
    "previous_value null and crossed null.\n\n"
    "Reply with ONLY a JSON array, no code fences: [{{\"metric\": \"what is measured\", \"current_value\": \"today's "
    "value and when it was reported, in plain words (no URL here)\", \"source\": \"the URL from the evidence that "
    "shows today's value\", \"inflection_threshold\": \"the value that would change the story\", \"direction\": "
    "\"rising|falling\", \"implication\": \"what crossing it would mean for Tata, in plain words (e.g. 'commercial "
    "adoption would be proven, so a pilot becomes worth assessing'); never name priority or horizon codes such as "
    "P1-P6 or H1-H3\", \"previous_value\": \"its value at the last assessment, or null for a new metric\", "
    "\"crossed\": true or false or null}}]. Each metric must be checkable by a future run: vague trends ('more "
    "adoption') are invalid.")
print("watch_metrics →", call("/prompts/watch_metrics", {"description": w["description"], "system": w.get("system"),
      "prompt": w_prompt, "enabled": w["enabled"], "reasoning": w.get("reasoning")}, "PUT")["version"])

m = prompts["measure_scoring"]
m_prompt = sub(m["prompt"],
    '"missing": "if unscorable — exactly what evidence would resolve it, else null"}}.',
    '"missing": "if unscorable — exactly what evidence would resolve it, else null", "figure": null, or, only when '
    'the measure asks for a market figure, the one figure your score rests on: {{"amount_usd_bn": <a number in US$ '
    'billions, e.g. 0.7 for $700 million>, "year": <the year it is for>, "scope": "what it covers, in a few words", '
    '"url": "the evidence URL that states it, also in evidence_urls"}}}}. Never give a figure no page in the evidence '
    'states, and none that a page gives only in another currency.')
print("measure_scoring →", call("/prompts/measure_scoring", {"description": m["description"], "system": m.get("system"),
      "prompt": m_prompt, "enabled": m["enabled"], "reasoning": m.get("reasoning")}, "PUT")["version"])

am = next(x for x in call("/scoring/measures")["measures"] if x["_id"] == "addressable-market")
am["required_evidence"] = (am["required_evidence"] + " Give the one market figure your score rests on as figure: "
                           "the radar shows it to Tata as a band, with its page.")
body = {k: am[k] for k in ("name", "code", "axis", "weight", "definition", "anchors", "required_evidence", "scope",
                           "open_question") if k in am}
print("addressable-market →", call("/scoring/measures/addressable-market", body, "PUT").get("required_evidence")[-80:])

print(call("/changes/update-seeding-data", {"items": [{"collection": "prompts", "id": "watch_metrics"},
                                                     {"collection": "prompts", "id": "measure_scoring"},
                                                     {"collection": "measures", "id": "addressable-market"}]}, "POST"))
