"""Prompt endpoints. Reads feed the portal's Prompts tab; PUT is an admin edit
(version bumped, timestamped). `variables` is never edited directly — it is
recomputed from the {placeholder} slots in the prompt text on every save, so
the stored list can't drift from the template."""

from datetime import datetime, timezone
from string import Formatter

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.db.mongo import get_collection

router = APIRouter()


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
    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
    updated = get_collection("prompts").find_one_and_update(
        {"_id": name},
        {"$set": changes, "$inc": {"version": 1}},
        return_document=True,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"unknown prompt {name!r}")
    return updated
