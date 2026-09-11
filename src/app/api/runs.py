"""Run endpoints: start, list, detail, terminate."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.db.mongo import get_collection
from app.services.runs import runner

router = APIRouter()


class RunParams(BaseModel):
    categories: list[Literal["H1", "H2", "H3"]] | None = None
    max_sources_per_category: int | None = Field(default=None, ge=1)
    max_pages_per_source: int | None = Field(default=None, ge=1)


@router.post("/runs", status_code=201)
def start_run(params: RunParams | None = None) -> dict:
    run_id = runner.start_run((params or RunParams()).model_dump(exclude_none=True))
    if run_id is None:
        raise HTTPException(status_code=409, detail="a run is already in progress")
    return {"id": run_id, "status": "running"}


@router.get("/runs")
def list_runs() -> dict:
    runs = list(
        get_collection("runs")
        .find({}, {"sources": 0, "params": 0})
        .sort("run_start_date_time", -1)
        .limit(100)
    )
    for run in runs:
        run["id"] = run.pop("_id")
    return {"runs": runs}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = get_collection("runs").find_one({"_id": run_id})
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    run["id"] = run.pop("_id")
    if run.get("resolve_id"):  # attach the chained resolve for the drill-down view
        resolve = get_collection("resolves").find_one({"_id": run["resolve_id"]})
        if resolve:
            resolve["id"] = resolve.pop("_id")
            run["resolve"] = resolve
    return run


@router.get("/runs/{run_id}/documents")
def run_documents(run_id: str, source_id: str | None = None,
                  include_text: bool = False,
                  limit: int = Query(default=20, ge=1, le=100),
                  skip: int = Query(default=0, ge=0)) -> dict:
    """Documents collected in a run, optionally for one source, paged (a page
    of full texts is heavy). Pass include_text=true for the as-is extracted
    text (a stub's text is resolved from the document it references)."""
    query: dict = {"run_id": run_id}
    if source_id:
        query["source_id"] = source_id
    projection: dict = {"content_hash": 0}
    if not include_text:
        projection["extracted_text"] = 0
    collection = get_collection("documents")
    total = collection.count_documents(query)
    docs = list(collection.find(query, projection)
                .sort("scraped_at", 1).skip(skip).limit(limit))
    for doc in docs:
        doc["id"] = doc.pop("_id")
        if include_text and doc.get("is_stub") and doc.get("ref_doc_id"):
            ref = collection.find_one({"_id": doc["ref_doc_id"]},
                                      {"extracted_text": 1, "text_pruned": 1})
            if ref:
                doc["extracted_text"] = ref.get("extracted_text")
                doc["text_pruned"] = ref.get("text_pruned", False)
    return {"documents": docs, "total": total}


@router.post("/runs/{run_id}/terminate")
def terminate_run(run_id: str) -> dict:
    run = get_collection("runs").find_one({"_id": run_id}, {"status": 1})
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    if run["status"] not in ("running",):
        raise HTTPException(status_code=409, detail=f"run is {run['status']}, not running")
    runner.request_terminate(run_id)
    return {"id": run_id, "status": "terminating"}
