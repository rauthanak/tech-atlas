"""Frontier, for leaders: the latest published edition (services/editions),
never live data. Its placements (people's overrides applied, each one that
moved since the edition before saying why), what isn't placed yet with the
reason, the assumptions in force and the evidence behind it; and each
technology's Point of View as it stood when the edition was published.
Read-only: the executive address passes on only these reads (proxy.ts)."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import editions

router = APIRouter()


@router.get("/frontier")
def frontier(fabric: str | None = None) -> dict:
    e = editions.latest()
    if e is None:
        return {"edition": None}
    return {"edition": editions.summary(e), "placed": editions.with_why(e, fabric), "held": editions.rows(e, "held", fabric),
            **{k: e.get(k) for k in ("fabrics", "stages", "cutpoints", "near_band", "assumptions", "evidence")}}


class Seen(BaseModel):
    kind: Literal["opened", "printed"]


@router.post("/frontier/pov/{tech_id}/seen", status_code=204)
def seen(tech_id: str, body: Seen) -> None:
    """Counted when a leader opens or prints a Point of View (the one write
    the leaders' address passes on)."""
    editions.record_view(tech_id, body.kind)


@router.get("/frontier/pov/{tech_id}")
def frozen_pov(tech_id: str) -> dict:
    """A technology's Point of View in the latest edition, as it stood then."""
    edition, pov = editions.frozen_pov(tech_id)
    if edition is None:
        raise HTTPException(status_code=404, detail="No edition is published yet: Points of View show here once one is.")
    if pov is None:
        raise HTTPException(status_code=404, detail=f"The edition {edition['label']} has no Point of View of this "
                                                    "technology: none was written when it was published.")
    return {**pov, "edition": edition}
