"""The supervisor — a fixed class instantiated once per category by the
runner (n categories → n supervisors, deterministic). It works only its own
category: fetches its sources via its tool and spins off one scout per
SOURCES_PER_SCOUT sources; scouts execute on the runner's bounded pool."""

import logging
from concurrent.futures import Executor

from deepagents import create_deep_agent

from agent.scout.agent import run_scout
from agent.supervisor.tools.sources import fetch_sources, make_sources_tool
from app.services.prompts import PromptStore
from app.services.runs import store
from app.settings import get_settings

log = logging.getLogger(__name__)


class Supervisor:
    def __init__(self, category: str, llm):
        self.category = category
        self.llm = llm

    def build_agent(self):
        return create_deep_agent(
            model=self.llm.chat_model(),
            tools=[make_sources_tool(self.category)],
            system_prompt=PromptStore.get("supervisor").render(category=self.category),
            name=f"supervisor-{self.category.lower()}",
        )

    def run(self, run_id: str, executor: Executor, params: dict) -> None:
        try:
            self.build_agent().invoke(
                {"messages": [{"role": "user", "content": "Survey your category's sources."}]},
                {"recursion_limit": 20},
            )
        except Exception:  # placeholder-prompt agent; scouting proceeds regardless
            log.exception("supervisor agent failed for %s", self.category)

        sources = fetch_sources(self.category)
        if params.get("max_sources_per_category"):
            sources = sources[: params["max_sources_per_category"]]
        if not sources:
            log.info("supervisor %s: no sources to scout", self.category)
            return

        per_scout = get_settings().sources_per_scout
        batches = [sources[i:i + per_scout] for i in range(0, len(sources), per_scout)]
        log.info("supervisor %s: %d sources → %d scouts", self.category, len(sources), len(batches))

        futures = [
            executor.submit(run_scout, run_id, self.category, batch, self.llm,
                            params.get("max_pages_per_source"))
            for batch in batches
        ]
        for future in futures:
            if store.cancelled(run_id):
                break
            try:
                future.result()
            except Exception:  # one scout failing must not sink the category
                log.exception("scout batch failed in %s", self.category)
