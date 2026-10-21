"""Prompt access. Prompts live in the `prompts` collection and are fetched at
runtime by name — never hardcoded in application code.

Usage:

    from app.services.prompts import PromptStore

    p = PromptStore.get("source_summary")
    reply = llm.ask(p.render(name="Google Research", url="...", horizon="H1"))

render() returns one final string: system + blank line + the filled prompt.
"""

from dataclasses import dataclass

from app.services.db.mongo import get_collection


@dataclass(frozen=True)
class Prompt:
    name: str
    description: str
    system: str | None
    prompt: str  # the actual prompt text, with {placeholder} slots
    variables: list[str]  # the placeholder names render() requires
    version: int
    reasoning: str = "off"  # "on": the model reasons before it answers (services/llm)
    title: str = ""

    def render(self, **values: str) -> str:
        """Return the actual prompt as one string — system, a blank line, then the
        prompt text with its {placeholder} slots filled. Raises KeyError naming
        any missing variables."""
        missing = [v for v in self.variables if v not in values]
        if missing:
            raise KeyError(f"prompt {self.name!r} is missing variables: {missing}")
        filled = self.prompt.format(**values)
        return f"{self.system}\n\n{filled}" if self.system else filled


class PromptStore:
    @staticmethod
    def get(name: str) -> Prompt:
        """Fetch one enabled prompt by name; raises KeyError if absent or disabled."""
        doc = get_collection("prompts").find_one({"_id": name, "enabled": True})
        if doc is None:
            raise KeyError(f"unknown or disabled prompt {name!r}")
        return Prompt(
            name=doc["name"],
            description=doc.get("description", ""),
            system=doc.get("system"),
            prompt=doc["prompt"],
            variables=doc.get("variables", []),
            version=doc.get("version", 1),
            reasoning=doc.get("reasoning", "off"),
            title=doc.get("title") or doc["name"],
        )
