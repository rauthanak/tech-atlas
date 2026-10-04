"""Prompt endpoints. Reads feed the portal's Prompts tab; PUT is an admin edit
(version bumped, timestamped). `variables` is never edited directly — it is
recomputed from the {placeholder} slots in the prompt text on every save, so
the stored list can't drift from the template. A save whose placeholders
differ from what the stage fills in is refused (422), so an edit can never
break a stage at run time."""

from datetime import datetime, timezone
from string import Formatter

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.db.mongo import get_collection

router = APIRouter()

# the placeholders each stage fills in when it renders its prompt
EXPECTED_VARIABLES: dict[str, set[str]] = {
    "orchestrator": set(),
    "supervisor": {"category"},
    "scout": {"category", "sources", "max_depth", "max_pages"},
    "article_summary": {"url", "text", "never_miss", "can_ignore"},
    "link_selection": {"budget", "links", "never_miss_names"},
    "technology_resolve": {"known_list", "tech_list"},
    "analyzer": set(),
    "measure_scoring": {"measure_name", "definition", "anchors", "required_evidence",
                        "technology", "fabric_name", "fabric_definition", "tcl_today", "evidence"},
    "watch_metrics": {"technology", "evidence"},
    "fabric_relevance": {"technology", "fabrics", "evidence"},
    "pov": {"technology", "assessment_data"},
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


@router.get("/prompts")
def list_prompts() -> dict:
    return {"prompts": list(get_collection("prompts").find().sort("_id", 1))}


@router.put("/prompts/{name}")
def update_prompt(name: str, edit: PromptEdit) -> dict:
    changes = edit.model_dump()
    changes["variables"] = _extract_variables(changes["prompt"])
    _check_variables(name, changes["variables"])
    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
    updated = get_collection("prompts").find_one_and_update(
        {"_id": name},
        {"$set": changes, "$inc": {"version": 1}},
        return_document=True,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"unknown prompt {name!r}")
    return updated
