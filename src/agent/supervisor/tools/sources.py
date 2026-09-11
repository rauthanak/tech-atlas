"""Supervisor tool: the sources of the supervisor's category. Paid sources
(cost=licensed — anything needing a subscription) are filtered out unless
INCLUDE_PAID_SOURCES=true in .env."""

from app.services.db.mongo import get_collection
from app.settings import get_settings


def fetch_sources(category: str) -> list[dict]:
    """Deterministic source list for a category, paid filter applied."""
    query: dict = {"horizon": category, "enabled": True}
    if not get_settings().include_paid_sources:
        query["cost"] = {"$ne": "licensed"}
    return list(get_collection("sources").find(query).sort("name", 1))


def make_sources_tool(category: str):
    def get_category_sources() -> str:
        """List this category's sources, one per line as 'name (url)'."""
        sources = fetch_sources(category)
        if not sources:
            return f"no enabled sources for {category}"
        return "\n".join(f"{s['name']} ({s['url']})" for s in sources)

    return get_category_sources
