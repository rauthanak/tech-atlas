"""The scout — a deep agent that collects its assigned batch of sources
(SOURCES_PER_SCOUT each) through the deterministic collect_source tool:
websites are crawled, data sources run their saved searches. After the
agent finishes, a deterministic sweep collects any source the LLM skipped,
so coverage never depends on model behaviour."""

import logging

from deepagents import create_deep_agent

from agent.scout.tools.collect import make_collect_tool, page_budget, recorded_snapshot
from app.services.llm.context import with_context
from app.services.db.mongo import get_collection
from app.services.prompts import PromptStore
from app.services.runs import store
from app.settings import get_settings

log = logging.getLogger(__name__)


def scout_values(category: str, sources: list[dict], max_depth: int, max_pages: int) -> dict:
    """The scout skill's blanks. The Skills page's preview fills them with
    this same function, so it shows exactly what a run sends."""
    return {
        "category": category,
        "sources": "\n".join(f"- {s['source_id']}: {s['name']} ({s['url']})" for s in sources),
        "max_depth": str(max_depth),
        "max_pages": str(max_pages),
    }


def run_scout(run_id: str, category: str, sources: list[dict], llm,
              max_pages_override: int | None = None) -> str:
    with with_context(run_kind="collection", run_id=run_id, skills=["scout"]):
        return _run_scout(run_id, category, sources, llm, max_pages_override)


def _run_scout(run_id: str, category: str, sources: list[dict], llm,
               max_pages_override: int | None = None) -> str:
    settings = get_settings()
    collect_source = make_collect_tool(run_id, category, sources, llm, max_pages_override)

    prompt = PromptStore.get("scout").render(**scout_values(
        category, sources, settings.scrape_max_depth,
        page_budget(recorded_snapshot(run_id), max_pages_override)))
    agent = create_deep_agent(
        model=llm.chat_model(),
        tools=[collect_source],
        system_prompt=prompt,
        name="scout",
    )

    report = ""
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": "Collect your assigned sources now."}]},
            {"recursion_limit": 10 + 4 * len(sources)},
        )
        content = result["messages"][-1].content
        report = content if isinstance(content, str) else str(content)
    except Exception as exc:  # the sweep below still guarantees coverage
        log.exception("scout agent failed for %s batch", category)
        report = f"scout agent error: {exc}"

    if store.cancelled(run_id):
        return report

    # Deterministic coverage sweep: collect anything the agent did not.
    run = get_collection("runs").find_one({"_id": run_id}, {"sources.source_id": 1}) or {}
    covered = {s["source_id"] for s in run.get("sources", [])}
    for source in sources:
        if source["source_id"] not in covered and not store.cancelled(run_id):
            log.warning("scout skipped %s — collecting deterministically", source["source_id"])
            report += "\n" + collect_source(source["source_id"])
    return report
