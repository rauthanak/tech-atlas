"""Recipes: which skills one stacked call carries (seeded, read-only in the
portal for now), and what a stacked call turns into for a technology and,
for a fabric call, a fabric: built by the same functions a run uses."""

from fastapi import APIRouter, HTTPException

from agent.analyzer import stacked
from agent.analyzer.engine import build_dossier, dossier_limit
from app.services.db.mongo import get_collection

router = APIRouter()
CHARS_PER_TOKEN = 4


@router.get("/recipes")
def list_recipes() -> dict:
    return {"recipes": list(get_collection("recipes").find())}


@router.get("/recipes/{recipe_id}/preview")
def recipe_preview(recipe_id: str, technology: str | None = None, fabric: str | None = None) -> dict:
    """The stacked call for one technology (default: the one with the most
    pages) and, for the fabric call, one fabric (default: the first switched
    on): its reused parts, in order, then what's sent each time."""
    recipe = get_collection("recipes").find_one({"_id": recipe_id})
    if recipe is None or recipe_id not in ("technology", "fabric", "classify"):
        raise HTTPException(status_code=404, detail=f"no preview for recipe {recipe_id!r}")
    techs = get_collection("technologies")
    tech = (techs.find_one({"_id": technology}) if technology else
            techs.find_one({"enabled": True}, sort=[("doc_count", -1)]))
    if tech is None:
        raise HTTPException(status_code=404, detail="no technology to show it for: run a collection first")
    measures = list(get_collection("measures").find())
    fabrics = list(get_collection("fabrics").find({"enabled": True}))
    config = list(get_collection("scoring_config").find())
    dossier = build_dossier(tech["name"], dossier_limit(config), signals_first=True)["text"]
    if not dossier:
        raise HTTPException(status_code=404, detail=f"no collected pages are linked to {tech.get('label') or tech['name']}")
    if recipe_id == "classify":
        from agent.classifier.classify import classification_tasks, list_values, lists
        from agent.classifier.evidence import pack
        from app.services.prompts import recipe as recipes
        from app.services.settings_store import radar_settings
        ev = pack(tech["name"], int(radar_settings()["classify_pages_cap"]))
        built = recipes.build(recipe, classification_tasks(list_values(lists())),
                              {"technology": tech.get("label") or tech["name"], "evidence": ev["text"], "facts": ev["facts"]})
        chosen = None
    elif recipe_id == "technology":
        built = stacked.technology_built(recipe, tech["name"], dossier, measures, fabrics, stacked._lists())
        chosen = None
    else:
        chosen = next((f for f in fabrics if f["_id"] == fabric), fabrics[0] if fabrics else None)
        if chosen is None:
            raise HTTPException(status_code=404, detail="no fabric is switched on")
        built = stacked.fabric_built(recipe, tech["name"], dossier, measures, chosen)
    labels = (["The technology and its evidence: sent once, reused by its other calls",
               "The tasks: reused by the next call of this kind"] if recipe.get("cache") != "instructions"
              else ["The tasks: the same for every technology, reused"])
    parts = [{"label": labels[i] if i < len(labels) else "Reused", "reused": True, "text": b}
             for i, b in enumerate(built.blocks)]
    parts.append({"label": "Sent each time", "reused": False, "text": built.user})
    chars = sum(len(p["text"]) for p in parts)
    return {"recipe": recipe_id, "name": recipe.get("name"), "keys": built.keys, "skills": built.skills,
            "technology": {"id": tech["_id"], "label": tech.get("label") or tech["name"]},
            "fabric": {"id": chosen["_id"], "name": chosen.get("name")} if chosen else None,
            "fabrics": [{"id": f["_id"], "name": f.get("name")} for f in fabrics],
            "parts": parts, "characters": chars, "tokens_about": round(chars / CHARS_PER_TOKEN)}
