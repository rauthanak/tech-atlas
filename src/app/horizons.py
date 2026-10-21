"""The three discovery horizons. Presentational metadata only — the sources
collection stores just the horizon key."""

HORIZONS: dict[str, dict[str, str]] = {
    "H1": {
        "label": "Already on the market",
        "meaning": "If TCL does not have it, that is a miss.",
    },
    "H2": {
        "label": "Money is moving before the market",
        "meaning": "Early signs: capital moves ahead of market consensus.",
    },
    "H3": {
        "label": "Not yet visible to the market",
        "meaning": "Research and blind spots.",
    },
}
