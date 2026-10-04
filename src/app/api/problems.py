"""Problems that need a person, and coverage (websites that reached their
page limit), for Operations (services/problems)."""

from fastapi import APIRouter

from app.services.problems import coverage, problems

router = APIRouter()


@router.get("/problems")
def list_problems() -> dict:
    found = problems()
    return {"count": len(found), "problems": found, "coverage": coverage()}
