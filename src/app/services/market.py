"""Market size as a band (agreed with Tata on 21 Oct): never a figure the
model makes up. The Addressable market measure returns the one figure it rests
on, with its year, its scope and the page that gives it (engine._figure keeps
it only when that page is one the measure cites); the band is worked out here."""

MEASURE = "addressable-market"
# upper limits in US$ billions; the last band has none
BANDS = [(1, "under $1B"), (5, "$1–5B"), (20, "$5–20B"), (100, "$20–100B"), (None, "over $100B")]


def band(amount_usd_bn: float) -> str:
    return next(name for top, name in BANDS if top is None or amount_usd_bn < top)


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
