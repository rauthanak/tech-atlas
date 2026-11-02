"""Market size as a band (agreed with Tata on 21 Oct): never a figure the
model makes up. The Addressable market measure returns the one figure it rests
on, with its year, its scope and the page that gives it (engine._figure keeps
it only when that page is one the measure cites); each use case carries its
ballpark size the same way (value.size). The band is worked out here, from the
bands in Setup (scoring_config `market_bands`, Hasan's scale: hundreds of
millions, billions, trillions)."""

from app.services.db.mongo import get_collection

MEASURE = "addressable-market"
# used when a database has no market_bands yet: the seeded list
DEFAULT_BANDS = [{"below_usd_bn": 0.1, "label": "under $100M"}, {"below_usd_bn": 1, "label": "$100M–1B"},
                 {"below_usd_bn": 10, "label": "$1–10B"}, {"below_usd_bn": 100, "label": "$10–100B"},
                 {"below_usd_bn": 1000, "label": "$100B–1T"}, {"below_usd_bn": None, "label": "over $1T"}]


def band(amount_usd_bn: float) -> str:
    bands = (get_collection("scoring_config").find_one({"_id": "market_bands"}) or {}).get("bands") or DEFAULT_BANDS
    return next(b["label"] for b in bands if b["below_usd_bn"] is None or amount_usd_bn < b["below_usd_bn"])


def market_size(measures: dict | None) -> dict | None:
    """From an assessment's measures: {band, amount_usd_bn, year, scope, url},
    or {band: None} when the measure was asked for a figure and no page gave
    one, or None when the assessment predates the figures (or has no such
    measure)."""
    m = (measures or {}).get(MEASURE)
    if not m or "figure" not in m:
        return None
    f = m["figure"]
    return {**f, "band": band(f["amount_usd_bn"])} if f else {"band": None}


def size_words(size: dict) -> str:
    """A use case's ballpark size in words: "$1–10B (what it covers, year)", "about 15% saving (…)",
    or "no reliable data: why"."""
    if size["basis"] == "none":
        return f"no reliable data: {size.get('reason')}"
    what = band(size["amount_usd_bn"]) if size.get("amount_usd_bn") else f"about {size['saving_pct']:g}% saving"
    detail = ", ".join(str(x) for x in (size.get("covers"), size.get("year")) if x)
    return f"{what}{f' ({detail})' if detail else ''}"


def use_case_size(size: dict | None) -> dict | None:
    """A use case's stored size with its band and words (None before sizes were asked)."""
    if not size:
        return None
    return {**size, "band": band(size["amount_usd_bn"]) if size.get("amount_usd_bn") else None, "words": size_words(size)}
