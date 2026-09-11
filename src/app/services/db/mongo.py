"""MongoDB access. One client, named collection accessors — the single place
collection names are spelled."""

from functools import lru_cache

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from app.settings import get_settings

COLLECTIONS = frozenset({
    "sources", "prompts", "runs", "documents",
    "fabrics", "measures", "scoring_config",
    "technologies", "resolves",
    "scoring_runs", "assessments", "povs", "pov_compose_jobs",
})


@lru_cache
def get_client() -> MongoClient:
    return MongoClient(get_settings().mongo_uri, serverSelectionTimeoutMS=3000)


def get_db() -> Database:
    return get_client()[get_settings().mongo_db]


def get_collection(name: str) -> Collection:
    if name not in COLLECTIONS:
        raise KeyError(f"Unknown collection {name!r}; known: {sorted(COLLECTIONS)}")
    return get_db()[name]


def ping() -> bool:
    get_client().admin.command("ping")
    return True
