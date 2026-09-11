from fastapi import APIRouter
from pymongo.errors import PyMongoError

from app.services.db import mongo

router = APIRouter()


@router.get("/health")
def health() -> dict:
    try:
        mongo_ok = mongo.ping()
    except PyMongoError:
        mongo_ok = False
    return {"status": "ok" if mongo_ok else "degraded", "mongo": mongo_ok}
