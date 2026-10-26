"""Read-only framework/configuration probes for the sign-in design review.

Uses the installed FastAPI and a synthetic application, not Tech Atlas.
No database, credentials, application HTTP requests or Docker operations.
"""
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
import json
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

observations = []
checks = []


async def refuse():
    checks.append("guard")
    raise HTTPException(status_code=401, detail="Sign in to continue")


app = FastAPI(dependencies=[Depends(refuse)])


class Input(BaseModel):
    name: str


@app.get("/api/example")
def read():
    return {"ok": True}


@app.post("/api/example")
def write(body: Input):
    return {"ok": True}


client = TestClient(app)
for method, path, kwargs in [
    ("GET", "/api/example", {}),
    ("GET", "/docs", {}),
    ("GET", "/openapi.json", {}),
    ("POST", "/api/example", {"content": "{", "headers": {"Content-Type": "application/json"}}),
]:
    checks.clear()
    response = client.request(method, path, **kwargs)
    observations.append({"case": "app dependency boundary", "method": method, "path": path,
                         "status": response.status_code, "guard_ran": bool(checks)})

CURRENT = ContextVar("sign_in_review_actor", default=None)


async def actor(request: Request):
    token = CURRENT.set(request.headers.get("x-test-actor"))
    try:
        yield
    finally:
        CURRENT.reset(token)


with_actor = FastAPI(dependencies=[Depends(actor)])


@with_actor.get("/example")
def context_example():
    context = copy_context()
    with ThreadPoolExecutor(max_workers=1) as pool:
        plain = pool.submit(CURRENT.get).result()
        carried = pool.submit(context.run, CURRENT.get).result()
    return {"sync_endpoint_actor": CURRENT.get(), "plain_nested_pool_actor": plain,
            "copied_nested_pool_actor": carried}


observations.append({"case": "actor propagation", "actual": TestClient(with_actor).get(
    "/example", headers={"x-test-actor": "synthetic-admin"}).json()})

target = Path(__file__).with_name("review-observations.json")
target.write_text(json.dumps(observations, indent=2) + "\n")
print(json.dumps(observations, indent=2))
