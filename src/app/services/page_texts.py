"""A page version's full text, kept apart from its visit record (24 Oct
scale plan, spec §5): lists and counts read visits, and only the few jobs
that read text open this. A visit says whether its text is here (`has_text`).

A version's text is `superseded` once a newer version of the same page is
stored; retention deletes superseded texts from older collections."""

from app.services.db.mongo import get_collection


def put(visit_id: str, text: str, page_key: str, run_id: str) -> None:
    """Store a new version's text; the page's older versions are superseded by it."""
    texts = get_collection("page_texts")
    texts.replace_one({"_id": visit_id}, {"text": text, "page_key": page_key, "run_id": run_id, "superseded": False},
                      upsert=True)  # safe to repeat (an upgrade stopped between this and its visit's mark)
    texts.update_many({"page_key": page_key, "_id": {"$ne": visit_id}, "superseded": False},
                      {"$set": {"superseded": True}})


def get(ids) -> dict[str, str]:
    """These versions' texts, by visit id (a pruned one isn't there)."""
    return {t["_id"]: t["text"] for t in get_collection("page_texts").find({"_id": {"$in": list(ids)}})}


def text(visit_id: str) -> str | None:
    return get([visit_id]).get(visit_id)


def prune(recent_runs: list[str]) -> list[str]:
    """Delete superseded texts from collections other than these; returns their visit ids."""
    texts = get_collection("page_texts")
    ids = texts.distinct("_id", {"superseded": True, "run_id": {"$nin": recent_runs}})
    if ids:
        texts.delete_many({"_id": {"$in": ids}})
    return ids
