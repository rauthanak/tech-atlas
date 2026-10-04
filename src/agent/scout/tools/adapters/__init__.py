"""Data-source adapters, registered by name — one module per free API. The
shared path (saved-search windows, progress, digests) is in base.py."""

from agent.scout.tools.adapters import base, epo_ops, job_boards, openalex, sec_edgar, usajobs

REGISTRY = {a.name: a for a in (epo_ops.ADAPTER, openalex.WORKS, openalex.AWARDS,
                                sec_edgar.ADAPTER, job_boards.ADAPTER, usajobs.ADAPTER)}


def collect(ctx, source: dict):
    return base.collect(ctx, source, REGISTRY)


def describe() -> list[dict]:
    """Search help per adapter, for the portal's source editor."""
    return [{"name": a.name, "label": a.label, "search_help": a.search_help,
             "example": a.example, "keys": list(a.keys), "configured": not a.missing_keys()}
            for a in REGISTRY.values()]
