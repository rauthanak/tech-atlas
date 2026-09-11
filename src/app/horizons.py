"""The three discovery horizons. Presentational metadata only — the sources
collection stores just the horizon key."""

HORIZONS: dict[str, dict[str, str]] = {
    "H1": {
        "label": "Known Knowns — misses",
        "meaning": "The market already has it. If TCL does not, that is a miss.",
    },
    "H2": {
        "label": "Known Unknowns — catchable inflections",
        "meaning": "Capital is moving ahead of market consensus.",
    },
    "H3": {
        "label": "Unknown Unknowns — blind spots",
        "meaning": "Not yet visible to the market.",
    },
}
