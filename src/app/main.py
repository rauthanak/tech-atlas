import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.services.db import bootstrap
from app.api.briefing import router as briefing_router
from app.api.changes import router as changes_router
from app.api.health import router as health_router
from app.api.pipeline import router as pipeline_router
from app.api.problems import router as problems_router
from app.api.prompts import router as prompts_router
from app.api.runs import router as runs_router
from app.api.scoring import router as scoring_router
from app.api.scoring_runs import router as scoring_runs_router
from app.api.settings import router as settings_router
from app.api.signals import router as signals_router
from app.api.sources import router as sources_router
from app.api.technologies import router as technologies_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.runs import runner, store
    from app.services.signals import recheck

    from agent.analyzer import engine as scoring_engine

    bootstrap.run()  # ensure the database exists; abort start-up if MongoDB is down
    store.reconcile_stale_runs()  # a 'running' run at boot died with the last process
    scoring_engine.reconcile_stale_scoring_runs()
    recheck.reconcile_stale()  # a re-check 'running' at boot was interrupted
    yield
    runner.shutdown()  # running runs die with this process — record it
    scoring_engine.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title="Tech Atlas", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router, prefix="/api")
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
