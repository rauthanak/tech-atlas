"""Orchestrator tool: the discovery categories (H horizons)."""

from app.horizons import HORIZONS


def get_h_categories() -> str:
    """Return the discovery categories (H horizons) for this run, one per line
    as 'key: label'."""
    return "\n".join(f"{key}: {meta['label']}" for key, meta in HORIZONS.items())


def category_keys() -> list[str]:
    """Deterministic list of category keys for the runner's fan-out."""
    return list(HORIZONS)
