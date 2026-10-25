"""Prompt endpoints. Reads feed the portal's Prompts tab; PUT is an admin edit
(version bumped, timestamped). `variables` is never edited directly — it is
recomputed from the {placeholder} slots in the prompt text on every save, so
the stored list can't drift from the template. A save whose placeholders
differ from what the stage fills in is refused (422), so an edit can never
break a stage at run time. The preview shows what a skill turns into when it
runs — saved text or an unsaved draft — and never calls a model."""

from string import Formatter
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.db.mongo import get_collection
from app.services.prompts import preview as skill_preview
from app.services.timezone import now_utc

router = APIRouter()

# the placeholders each stage fills in when it renders its prompt
EXPECTED_VARIABLES: dict[str, set[str]] = {
    "orchestrator": set(),
    "supervisor": {"category"},
    "scout": {"category", "sources", "max_depth", "max_pages"},
    "article_summary": {"url", "text", "never_miss", "can_ignore"},
    "link_selection": {"budget", "links", "never_miss_names"},
    "technology_resolve": {"known_list", "tech_list"},
    "technology_label": {"names"},
    "technology_names": {"technologies"},
    "name_check": {"technology", "passages"},
    "analyzer": set(),
    "measure_scoring": {"measure_name", "definition", "anchors", "required_evidence",
                        "technology", "fabric_name", "fabric_definition", "tcl_today", "evidence"},
    "watch_metrics": {"technology", "evidence", "previous"},
    "fabric_relevance": {"technology", "fabrics", "evidence"},
    "pov": {"technology", "assessment_data"},
    "evidence_strength": {"technology", "evidence", "facts"},
    "domain_subdomain": {"technology", "evidence", "domains", "subdomains"},
    "commercial_availability": {"technology", "evidence", "availability_values"},
    "trl_level": {"technology", "evidence", "trl_levels"},
    "possible_nascent": {"technology", "evidence"},
    "value_levers": {"technology", "fabric_name", "fabric_definition", "tcl_today", "fabric_levers", "mechanisms",
                     "fabric_cautions", "fabric_blockers", "evidence"},
}


def _check_variables(name: str, found: list[str]) -> None:
    expected = EXPECTED_VARIABLES.get(name)
    if expected is None:
        return
    missing = sorted(expected - set(found))
    unknown = sorted(set(found) - expected)
    if missing or unknown:
        parts = []
        if missing:
            parts.append("missing " + ", ".join("{" + v + "}" for v in missing))
        if unknown:
            parts.append("unknown " + ", ".join("{" + v + "}" for v in unknown))
        keep = ", ".join("{" + v + "}" for v in sorted(expected)) or "no placeholders"
        raise HTTPException(
            status_code=422,
            detail=f"{'; '.join(parts)}. The {name} prompt must use exactly: {keep}. "
                   "Write literal braces as {{ }}.")


def _extract_variables(prompt_text: str) -> list[str]:
    """Placeholder names used by str.format — {{ }} escapes are literals."""
    try:
        fields = [f for _, f, _, _ in Formatter().parse(prompt_text) if f]
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"unbalanced braces in prompt text ({exc}); JSON examples need "
                   "doubled braces {{ }} — single braces are variables")
    seen: list[str] = []
    for f in fields:
        if f not in seen:
            seen.append(f)
    return seen


class PromptEdit(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    system: str | None = Field(default=None, max_length=20000)
    prompt: str = Field(min_length=1, max_length=40000)
    enabled: bool
    reasoning: Literal["on", "off"] | None = None  # None: left as it is


@router.get("/prompts")
def list_prompts() -> dict:
    return {"prompts": list(get_collection("prompts").find().sort("_id", 1))}


@router.put("/prompts/{name}")
def update_prompt(name: str, edit: PromptEdit) -> dict:
    changes = edit.model_dump(exclude_none=True)
    changes.setdefault("system", None)
    changes["variables"] = _extract_variables(changes["prompt"])
    _check_variables(name, changes["variables"])
    changes["updated_at"] = now_utc()
    updated = get_collection("prompts").find_one_and_update(
        {"_id": name},
        {"$set": changes, "$inc": {"version": 1}},
        return_document=True,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"unknown prompt {name!r}")
    return updated


class PreviewDraft(BaseModel):
    """Unsaved skill text, plus the same switches the GET takes."""
    system: str | None = Field(default=None, max_length=20000)
    prompt: str = Field(min_length=1, max_length=40000)
    technology: str | None = None
    fabric: str | None = None
    measure: str | None = None
    source: str | None = None
    page: str | None = None
    horizon: str | None = None


@router.get("/prompts/{name}/preview")
def preview_prompt(name: str, technology: str | None = None, fabric: str | None = None,
                   measure: str | None = None, source: str | None = None,
                   page: str | None = None, horizon: str | None = None) -> dict:
    """What a skill turns into: how many versions of it a run sends, where its
    blanks are filled from, and one real example built from today's settings."""
    return _preview(name, {"technology": technology, "fabric": fabric, "measure": measure,
                           "source": source, "page": page, "horizon": horizon})


@router.post("/prompts/{name}/preview")
def preview_draft(name: str, draft: PreviewDraft) -> dict:
    """The same, built from unsaved text — refused exactly as Save would refuse it."""
    variables = _extract_variables(draft.prompt)
    _check_variables(name, variables)
    text = {"system": draft.system or None, "prompt": draft.prompt, "variables": variables}
    return _preview(name, draft.model_dump(exclude={"system", "prompt"}), text)


def _preview(name: str, choices: dict, draft: dict | None = None) -> dict:
    try:
        out = skill_preview.preview(name, choices, draft)
    except skill_preview.BadChoice as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if out is None:
        raise HTTPException(status_code=404, detail=f"unknown skill {name!r}")
    return out
