"""The orchestrator — the top-level deep agent. It learns the categories via
its tool; the runner then dispatches one supervisor per category
(deterministic fan-out, never an LLM decision)."""

import logging

from deepagents import create_deep_agent

from agent.orchestrator.tools.categories import get_h_categories
from app.services.prompts import PromptStore

log = logging.getLogger(__name__)


def build_orchestrator(llm):
    return create_deep_agent(
        model=llm.chat_model(),
        tools=[get_h_categories],
        system_prompt=PromptStore.get("orchestrator").render(),
        name="orchestrator",
    )


def run_orchestrator(llm) -> str:
    """Invoke the orchestrator once; returns its report."""
    result = build_orchestrator(llm).invoke(
        {"messages": [{"role": "user", "content": "Determine the categories for this run."}]},
        {"recursion_limit": 20},
    )
    report = result["messages"][-1].content
    return report if isinstance(report, str) else str(report)
