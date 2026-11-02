"""Find evidence (agent/find_evidence): its cost first, start it, and how it
went. Only a person starts it, choosing where to look (services/places: the
radar's data sources, its websites, the web) and how many per place, with the
cost shown first; there is no daily cap. Add a link needs no search; nor does
Add evidence (POST /find-evidence/add): links and files a person gives for one
technology, optionally carried on to its Point of View."""

import json

from urllib.parse import urlsplit
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

from agent.find_evidence import job as finder
from agent.scout.tools.addresses import private_host
from agent.scout.tools.crawl import extract_pdf
from app.services import places as places_service, websearch
from app.services.db.mongo import get_collection
from app.services.settings_store import radar_settings
from app.services.timezone import request_tz

router = APIRouter()

NOT_PUBLIC = ("this link points inside a private network: the radar reads only public websites. "
              "Save the page as a PDF and add the file instead")
NO_LOGINS = ("a link can't carry a login: the radar reads pages as any visitor would and never keeps passwords. "
             "Save the page as a PDF and add the file instead")


def _bad_link(url: str) -> str | None:
    """Why a pasted link can't be read, or None."""
    if not url.startswith(("http://", "https://")):
        return f"paste each page's full address, starting with http:// or https://: {url}"
    parts = urlsplit(url)
    if parts.username or parts.password:
        return NO_LOGINS
    if private_host(url):
        return NOT_PUBLIC
    return None


class Gap(BaseModel):
    kind: Literal["technology", "measure", "use_case", "link"]
    tech_id: str = Field(min_length=1)
    fabric_id: str | None = None
    measure_id: str | None = None
    key: str | None = None  # a use case's key: look for its market size
    url: str | None = Field(default=None, max_length=2000)
    target: Literal["technology", "measure", "use_case"] | None = None  # what a pasted link re-runs
    places: list[str] | None = Field(default=None, max_length=50)  # where to look (services/places); none: the web
    per_place: int | None = Field(default=None, ge=1, le=50)       # how many from each place
    counts: dict[str, int] | None = None                           # a place's own number; the rest take per_place

    @field_validator("counts")
    @classmethod
    def _counts(cls, counts: dict[str, int] | None) -> dict[str, int] | None:
        if counts and any(not 1 <= n <= 50 for n in counts.values()):
            raise ValueError("each place takes 1 to 50")
        return counts


class Start(BaseModel):
    gap: Gap


NO_SEARCH = "Find evidence needs a web search key (the server's .env), or a data source it can search. Add a link still works."


def _why_not(chosen: list[str], offered: list[dict]) -> HTTPException | None:
    """Why a search can't start now, as the refusal starting one gets; None when it can."""
    usable = {p["id"] for p in offered if p["available"]}
    if not usable:
        return HTTPException(status_code=409, detail=NO_SEARCH)
    if not set(chosen) & usable:
        return HTTPException(status_code=422, detail="Choose at least one place that can be searched.")
    return None


def _cost(chosen: list[str], offered: list[dict], per_place: int, counts: dict[str, int] | None = None) -> dict:
    """What a search costs in model calls: each page read (a counts place gives one page;
    a place with its own number reads up to that), each web search (the model runs it),
    and one to work out the gap again."""
    picked = [p for p in offered if p["id"] in chosen and p["available"]]
    pages = sum(1 if p["kind"] == "counts" else (counts or {}).get(p["id"]) or per_place for p in picked)
    searches = sum(1 for p in picked if p["kind"] in ("websites", "web"))
    return {"pages": pages, "searches": searches, "calls": pages + searches + 1}


@router.get("/find-evidence/preview")
def preview(kind: str, tech_id: str, fabric_id: str | None = None, measure_id: str | None = None,
            key: str | None = None, places: str | None = None, per_place: int | None = None,
            counts: str | None = None) -> dict:
    """What a search would do, before it runs: where it can look (every place
    that can be searched is chosen unless `places` says otherwise), under which
    names, and what it costs."""
    gap = {"kind": kind, "tech_id": tech_id, "fabric_id": fabric_id, "measure_id": measure_id, "key": key}
    offered = places_service.places()
    chosen = places.split(",") if places is not None else [p["id"] for p in offered if p["available"]]
    n = per_place or int(radar_settings()["find_evidence_results"])
    tech = get_collection("technologies").find_one({"_id": tech_id}, {"name": 1, "label": 1, "aliases": 1}) or {}
    own = {k: int(v) for k, v in (c.split(":") for c in (counts or "").split(",") if ":" in c) if v.isdigit()}
    why = _why_not(chosen, offered)
    cost = _cost(chosen, offered, n, own)
    return {"configured": websearch.configured(), "provider": websearch.provider(),
            "query": finder.query_for(gap) if kind != "link" else None, "names": places_service.names(tech),
            "places": [{**p, "chosen": p["id"] in chosen and p["available"]} for p in offered],
            "per_place": n, "counts": own, "cost": cost, "searches": cost["searches"], "page_reads": cost["pages"], "reruns": 1,
            "why_not": why.detail if why else None}


@router.post("/find-evidence", status_code=202)
def start(body: Start, tz: str = Depends(request_tz)) -> dict:
    gap = body.gap.model_dump()
    if not get_collection("technologies").find_one({"_id": gap["tech_id"]}, {"_id": 1}):
        raise HTTPException(status_code=404, detail=f"unknown technology {gap['tech_id']!r}")
    if gap.get("measure_id"):
        m = get_collection("measures").find_one({"_id": gap["measure_id"]}, {"name": 1, "scope": 1}) or {}
        if m.get("scope") == "tata":
            raise HTTPException(status_code=422, detail=(
                f"{m.get('name')} is a figure Tata enters, not one scored from pages: enter it on the "
                "technology's Assessment tab, or leave it out."))
    if gap["kind"] == "link":
        if why := _bad_link(gap.get("url") or ""):
            raise HTTPException(status_code=422, detail=why)
    elif why := _why_not(gap.get("places") or [places_service.WEB], places_service.places()):
        raise why
    if gap["kind"] == "measure" and not gap.get("measure_id"):
        raise HTTPException(status_code=422, detail="say which measure")
    return {"job_id": finder.start(gap, tz)}


MAX_LINKS, MAX_FILES = 20, 10
# what one job can hold (a stored record is at most 16 MB) and what the portal passes on; its AddEvidence mirrors them
MAX_FILE_MB, MAX_FILES_MB, MAX_TEXT_MB = 8, 16, 12
MB = 1024 * 1024
READABLE = (".pdf", ".txt", ".md", ".html", ".htm")


def _text_of(name: str, content: bytes) -> str:
    """An uploaded file as text, or a refusal that says why."""
    if not name.lower().endswith(READABLE):
        raise HTTPException(status_code=422, detail=f"{name}: only PDF, text, Markdown or HTML files can be read")
    text = extract_pdf(content) if name.lower().endswith(".pdf") else content.decode("utf-8", errors="replace")
    if not (text or "").strip():
        raise HTTPException(status_code=422, detail=f"{name} has no text to read (a scanned PDF needs its text first)")
    return text


@router.post("/find-evidence/add", status_code=202)
def add_evidence(tech_id: str = Form(...), urls: str = Form("[]"), through: str = Form("judge"),
                       assess_anyway: bool = Form(False), files: list[UploadFile] = File(default=[]),
                       tz: str = Depends(request_tz)) -> dict:
    """Links (a JSON list) and files for one technology: read and filed under
    it, its evidence judged again, and with through=pov assessed and its Point
    of View written."""
    if not get_collection("technologies").find_one({"_id": tech_id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail=f"unknown technology {tech_id!r}")
    try:
        links = [u.strip() for u in json.loads(urls) if str(u).strip()]
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="the links weren't readable: send them as a list")
    if why := next((w for u in links if (w := _bad_link(u))), None):
        raise HTTPException(status_code=422, detail=why)
    if len(links) > MAX_LINKS or len(files) > MAX_FILES:
        raise HTTPException(status_code=422, detail=f"at most {MAX_LINKS} links and {MAX_FILES} files at a time")
    given, size, chars = [], 0, 0
    for f in files:  # read no more than the limit allows, so an oversized file is refused at once
        name = f.filename or "file"
        content = f.file.read(MAX_FILE_MB * MB + 1)
        if len(content) > MAX_FILE_MB * MB:
            raise HTTPException(status_code=413, detail=f"{name} is larger than {MAX_FILE_MB} MB: split it, or save "
                                                        "only the pages you need as a PDF")
        size += len(content)
        if size > MAX_FILES_MB * MB:
            raise HTTPException(status_code=413, detail=f"the files together are larger than {MAX_FILES_MB} MB: "
                                                        "add them in two goes")
        text = _text_of(name, content)
        chars += len(text.encode())
        if chars > MAX_TEXT_MB * MB:
            raise HTTPException(status_code=422, detail=f"the text read from these files is more than {MAX_TEXT_MB} MB "
                                                        "together: add fewer files at a time")
        given.append({"name": name, "text": text})
    if not links and not given:
        raise HTTPException(status_code=422, detail="add at least one link or file")
    if through not in ("judge", "pov"):
        raise HTTPException(status_code=422, detail="through is judge or pov")
    gap = {"kind": "links", "tech_id": tech_id, "urls": list(dict.fromkeys(links)), "through": through,
           "assess_anyway": assess_anyway}
    return {"job_id": finder.start(gap, tz, given)}


@router.get("/find-evidence/{job_id}")
def get_job(job_id: str) -> dict:
    j = get_collection("find_evidence_jobs").find_one({"_id": job_id})
    if j is None:
        raise HTTPException(status_code=404, detail="no such Find evidence job")
    return finder.view(j)


@router.get("/find-evidence")
def list_jobs(tech_id: str, limit: int = 10) -> dict:
    """The technology's jobs, newest first, each as it reads now: what was
    filed, set aside (by which rule) and not read (why)."""
    name = finder.name_of(tech_id)
    return {"jobs": [finder.view(j, name) for j in get_collection("find_evidence_jobs").find({"gap.tech_id": tech_id})
                     .sort("at", -1).limit(max(1, min(limit, 50)))]}
