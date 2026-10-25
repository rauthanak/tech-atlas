"""Find evidence (agent/find_evidence): its cost first, start it, and how it
went. Only a person starts it; searches have a daily budget (radar settings),
counted in the default time zone. Add a link needs no search, so no budget;
nor does Add evidence (POST /find-evidence/add): links and files a person
gives for one technology, optionally carried on to its Point of View."""

import json

from datetime import datetime
from urllib.parse import urlsplit
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from agent.find_evidence import job as finder
from agent.scout.tools.crawl import extract_pdf
from app.services import websearch
from app.services.db.mongo import get_collection
from app.services.settings_store import radar_settings
from app.services.timezone import request_tz

router = APIRouter()

NO_LOGINS = ("a link can't carry a login: the radar reads pages as any visitor would and never keeps passwords. "
             "Save the page as a PDF and add the file instead")


def _bad_link(url: str) -> str | None:
    """Why a pasted link can't be read, or None."""
    if not url.startswith(("http://", "https://")):
        return f"paste each page's full address, starting with http:// or https://: {url}"
    parts = urlsplit(url)
    if parts.username or parts.password:
        return NO_LOGINS
    return None


class Gap(BaseModel):
    kind: Literal["technology", "measure", "use_case", "link"]
    tech_id: str = Field(min_length=1)
    fabric_id: str | None = None
    measure_id: str | None = None
    url: str | None = Field(default=None, max_length=2000)
    target: Literal["technology", "measure", "use_case"] | None = None  # what a pasted link re-runs


class Start(BaseModel):
    gap: Gap


def searches_today() -> tuple[int, int]:
    """(searches started today, the daily budget), today in the default zone."""
    settings = radar_settings()
    zone = ZoneInfo(settings["default_time_zone"])
    today = datetime.now(zone).date()
    used = sum(1 for j in get_collection("find_evidence_jobs").find({"searched": True}, {"at": 1})
               if datetime.fromisoformat(j["at"]).astimezone(zone).date() == today)
    return used, int(settings["find_evidence_daily_budget"])


def _why_not(used: int, limit: int) -> HTTPException | None:
    """Why a search can't start now, as the refusal starting one gets; None when it can."""
    if not websearch.configured():
        return HTTPException(status_code=409, detail="Find evidence needs a web search key (the server's .env). "
                                                     "Add a link still works.")
    if used >= limit:
        return HTTPException(status_code=429, detail=f"Today's {limit} searches are used up (counted in "
                             f"{radar_settings()['default_time_zone']}); more tomorrow. Add a link still works.")
    return None


@router.get("/find-evidence/preview")
def preview(kind: str, tech_id: str, fabric_id: str | None = None, measure_id: str | None = None) -> dict:
    used, limit = searches_today()
    gap = {"kind": kind, "tech_id": tech_id, "fabric_id": fabric_id, "measure_id": measure_id}
    why = _why_not(used, limit)
    return {"configured": websearch.configured(), "provider": websearch.provider(),
            "query": finder.query_for(gap) if kind != "link" else None,
            "searches": 1, "page_reads": int(radar_settings()["find_evidence_results"]), "reruns": 1,
            "budget": {"used": used, "limit": limit}, "why_not": why.detail if why else None}


@router.post("/find-evidence", status_code=202)
def start(body: Start, tz: str = Depends(request_tz)) -> dict:
    gap = body.gap.model_dump()
    if not get_collection("technologies").find_one({"_id": gap["tech_id"]}, {"_id": 1}):
        raise HTTPException(status_code=404, detail=f"unknown technology {gap['tech_id']!r}")
    if gap["kind"] == "link":
        if why := _bad_link(gap.get("url") or ""):
            raise HTTPException(status_code=422, detail=why)
    elif why := _why_not(*searches_today()):
        raise why
    if gap["kind"] == "measure" and not gap.get("measure_id"):
        raise HTTPException(status_code=422, detail="say which measure")
    return {"job_id": finder.start(gap, tz)}


MAX_LINKS, MAX_FILES, MAX_FILE_MB = 20, 10, 25
READABLE = (".pdf", ".txt", ".md", ".html", ".htm")


def _text_of(name: str, content: bytes) -> str:
    """An uploaded file as text, or a refusal that says why."""
    if not name.lower().endswith(READABLE):
        raise HTTPException(status_code=422, detail=f"{name}: only PDF, text, Markdown or HTML files can be read")
    if len(content) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(status_code=422, detail=f"{name} is larger than {MAX_FILE_MB} MB")
    text = extract_pdf(content) if name.lower().endswith(".pdf") else content.decode("utf-8", errors="replace")
    if not (text or "").strip():
        raise HTTPException(status_code=422, detail=f"{name} has no text to read (a scanned PDF needs its text first)")
    return text


@router.post("/find-evidence/add", status_code=202)
async def add_evidence(tech_id: str = Form(...), urls: str = Form("[]"), through: str = Form("judge"),
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
    given = [{"name": f.filename or "file", "text": _text_of(f.filename or "file", await f.read())} for f in files]
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
