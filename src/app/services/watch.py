"""Signs to watch (the watch_metrics skill, one call per technology per
assessment): each names what's measured, its threshold (the point at which
the answer changes), the value now and whether it crossed. The model
proposes them at a technology's first assessment and carries each one
forward word for word, so a sign's wording identifies it across
assessments: `key` is a short id made from it.

A person may own a sign (decisions): set its threshold in their own words
(watch_threshold), or say it hasn't crossed whatever the model said
(watch_crossed: no). Both are kept like every other choice, never
overwritten by a new assessment, with Undo; `apply` shows them on a sign."""

import hashlib

from app.services import decisions


def sign_key(metric: str) -> str:
    """A sign's id: from its wording, the same in every assessment that carries it forward."""
    return "w:" + hashlib.sha1(" ".join(str(metric).lower().split()).encode()).hexdigest()[:16]


def apply(metrics: list[dict], chosen: list[dict]) -> list[dict]:
    """The signs as people left them (`chosen`: the technology's choices in
    force): each with its key, a person's threshold (`threshold_by`, and the
    choice's id for Undo) and a person's "not crossed"."""
    out = []
    for m in metrics or []:
        key = sign_key(m.get("metric") or "")
        sign = {**m, "key": key}
        threshold = decisions.pick(chosen, "watch_threshold", key=key)
        if threshold:
            sign.update(model_threshold=m.get("inflection_threshold"), inflection_threshold=threshold["value"],
                        threshold_by={"decision_id": threshold["_id"], "at": threshold["at"], "tz": threshold.get("tz"),
                                      "reason": threshold.get("reason")})
        overruled = decisions.pick(chosen, "watch_crossed", key=key)
        if overruled:
            sign.update(model_crossed=m.get("crossed"), crossed=False,
                        crossed_by={"decision_id": overruled["_id"], "at": overruled["at"], "tz": overruled.get("tz"),
                                    "reason": overruled.get("reason")})
        out.append(sign)
    return out


def fixed_thresholds(chosen: list[dict]) -> dict[str, str]:
    """The thresholds a person set, by sign key: the next assessment keeps them as they are."""
    return {d["key"]: d["value"] for d in chosen if d["kind"] == "watch_threshold"}
