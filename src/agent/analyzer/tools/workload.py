"""The analyzer agent's tools — thin closures over the deterministic engine,
bound to one scoring run."""

from concurrent.futures import ThreadPoolExecutor

from agent.analyzer import engine
from app.services.db.mongo import get_collection


def make_workload_tool(run_id: str):
    def get_workload() -> str:
        """List the technologies awaiting assessment in this scoring run, with
        their document counts. Returns 'tech_id — name (n docs)' lines; assess
        each tech_id with assess_technology."""
        run = get_collection("scoring_runs").find_one({"_id": run_id})
        if run is None:
            return "unknown scoring run"
        done = {a["tech_id"] for a in get_collection("assessments")
                .find({"scoring_run_id": run_id}, {"tech_id": 1})}
        lines = [f"{t['tech_id']} — {t['name']} ({t.get('doc_count', 0)} docs)"
                 + (" [assessed]" if t["tech_id"] in done else "")
                 for t in run["technologies"]]
        return "\n".join(lines) or "nothing to assess"
    return get_workload


def make_assess_tool(run_id: str, llm, executor: ThreadPoolExecutor):
    def assess_technology(tech_id: str) -> str:
        """Assess one technology from the workload: builds its evidence
        dossier, gates the relevant fabrics, scores every measure per fabric,
        rolls up TORA, and stores the assessment. Pass the tech_id exactly as
        listed by get_workload."""
        return engine.assess_technology(run_id, tech_id, llm, executor)
    return assess_technology
