import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.concurrency import run_in_threadpool

from app.services import auth
from app.services.db import bootstrap
from app.api.accounts import router as accounts_router
from app.api.auth import router as auth_router
from app.api.briefing import router as briefing_router
from app.api.changes import router as changes_router
from app.api.classify import router as classify_router
from app.api.decisions import router as decisions_router
from app.api.finance import router as finance_router
from app.api.editions import router as editions_router
from app.api.frontier import router as frontier_router
from app.api.find_evidence import router as find_evidence_router
from app.api.tagging import router as tagging_router
from app.api.health import router as health_router
from app.api.imports import router as imports_router
from app.api.lists import router as lists_router
from app.api.pipeline import router as pipeline_router
from app.api.problems import router as problems_router
from app.api.recipes import router as recipes_router
from app.api.prompts import router as prompts_router
from app.api.runs import router as runs_router
from app.api.scoring import router as scoring_router
from app.api.scoring_runs import router as scoring_runs_router
from app.api.settings import router as settings_router
from app.api.signals import router as signals_router
from app.api.skills import router as skills_router
from app.api.sources import router as sources_router
from app.api.technologies import router as technologies_router
from app.api.usage import router as usage_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services import jobs

    bootstrap.run()  # ensure the database exists; abort start-up if MongoDB is down
    if jobs.in_worker():  # the worker container runs the jobs, recovers them and does the upkeep
        yield
        return
    jobs.recover()   # a job still 'running' at boot died with the last process
    jobs.upkeep()    # each technology's answers and the Briefing's days, kept ready (plan 10, rule 1)
    yield
    jobs.shutdown()  # jobs running in this process end with it, and say so


# edits to these can move any technology's answers (a list's names, the evidence floor, the
# priority grid, weights, an import): every stored answer is worked out again, in the background
# (putting one back in Setup › Changes does the same: api/changes.ANSWERS_FROM)
CONFIG_PATHS = ("/api/settings", "/api/lists", "/api/scoring/measures", "/api/scoring/config",
                "/api/scoring/fabrics", "/api/imports")


def create_app() -> FastAPI:
    # every call is checked (services/auth.guard): signed in, and allowed for the person's role. App-wide, so no
    # endpoint can be left out; the only open calls are health, sign-in and sign-out
    app = FastAPI(title="Tech Atlas", version="0.1.0", lifespan=lifespan, dependencies=[Depends(auth.guard)])

    @app.middleware("http")
    async def config_changed(request: Request, call_next):
        response = await call_next(request)
        if request.method != "GET":
            from app.api import pipeline
            from app.services import editions
            pipeline.refresh_now()  # an action may have started or ended something: the next poll is fresh
            editions.forget_since()
        if request.method != "GET" and response.status_code < 400 and request.url.path.startswith(CONFIG_PATHS):
            from app.services import tech_status
            await run_in_threadpool(tech_status.touch_all)  # off the event loop: other requests go on meanwhile
        return response

    app.include_router(health_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(accounts_router, prefix="/api")
    app.include_router(sources_router, prefix="/api")
    app.include_router(runs_router, prefix="/api")
    app.include_router(scoring_router, prefix="/api")
    app.include_router(scoring_runs_router, prefix="/api")
    app.include_router(prompts_router, prefix="/api")
    app.include_router(technologies_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(changes_router, prefix="/api")
    app.include_router(signals_router, prefix="/api")
    app.include_router(pipeline_router, prefix="/api")
    app.include_router(briefing_router, prefix="/api")
    app.include_router(problems_router, prefix="/api")
    app.include_router(usage_router, prefix="/api")
    app.include_router(skills_router, prefix="/api")
    app.include_router(recipes_router, prefix="/api")
    app.include_router(decisions_router, prefix="/api")
    app.include_router(classify_router, prefix="/api")
    app.include_router(lists_router, prefix="/api")
    app.include_router(find_evidence_router, prefix="/api")
    app.include_router(tagging_router, prefix="/api")
    app.include_router(imports_router, prefix="/api")
    app.include_router(finance_router, prefix="/api")
    app.include_router(frontier_router, prefix="/api")
    app.include_router(editions_router, prefix="/api")
    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8100")),
        reload=True,
    )


if __name__ == "__main__":
    main()
