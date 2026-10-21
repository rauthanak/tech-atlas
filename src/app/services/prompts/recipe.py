"""Stacked calls ("recipes"): several skills answered in one model call.

Each skill stays its own prompt, edited and versioned on its own; a recipe
(seeded in `recipes`) only lists which skills one call carries, in order, and
the material they share. A call is built as:

  preamble   what the call is, and the reply's shape: ONE JSON object, one key
             per task
  one block per task, headed "### <key>: <name>": the skill's own system and
             text, its own blanks filled, each shared blank replaced by a
             pointer to where it is given once
  the shared parts (TECHNOLOGY, EVIDENCE, FABRIC, TCL TODAY ...), given once

The parts that repeat from call to call go first, as `blocks` the provider is
asked to reuse (services/llm): with `cache: evidence` the technology and its
evidence lead, so a technology's fabric calls reuse what its technology call
sent (the evidence is by far the biggest part); with `cache: instructions`
the tasks lead, for calls whose evidence is small and whose instructions are
the same for every technology (Classify).

The reply is split by key and each value checked by its own skill's rules
(`validators`); what's missing or fails comes back as a Failure. ask() makes
the call under one rule: a reply that isn't JSON at all is asked again once,
whole; each task that still failed is asked alone with its skill's normal
single call; one that fails alone too takes its skill's default, or stays a
Failure, its reason kept either way.
"""

import logging
from dataclasses import dataclass, field

from app.services.llm.context import with_context
from app.services.llm.llm import call_with_backoff, parse_json
from app.services.prompts.store import PromptStore

log = logging.getLogger(__name__)

# the shared blanks, and the section each is given once under
SECTIONS = {"technology": "TECHNOLOGY", "evidence": "EVIDENCE", "facts": "FACTS", "fabric_name": "FABRIC",
            "fabric_definition": "FABRIC", "tcl_today": "TCL TODAY"}


@dataclass
class Task:
    key: str                 # the reply key: the skill's name, or "measure:<id>"
    skill: str               # the skill (prompt) it renders
    heading: str             # "Score one measure: Addressable market"
    values: dict = field(default_factory=dict)  # its own blanks; shared ones come from `shared`


@dataclass
class Built:
    recipe_id: str
    blocks: list[str]        # fixed text, sent first and marked for reuse
    user: str                # the rest of the call
    keys: list[str]
    skills: list[str]        # every skill the call carries (for recording and reasoning)
    tasks: list[Task]
    shared: dict             # the blanks given once, which a task asked alone fills in full


@dataclass
class Failure:
    reason: str              # why this key can't be used, in plain words


def _pointer(blank: str) -> str:
    return f"(given once, under {SECTIONS[blank]})"


def _block(task: Task, shared: dict) -> str:
    prompt = PromptStore.get(task.skill)
    values = {**{b: _pointer(b) for b in shared if b in SECTIONS}, **task.values}
    filled = prompt.prompt.format(**{v: values.get(v, "") for v in prompt.variables})
    head = f"### {task.key}: {task.heading}"
    return "\n".join(p for p in (head, prompt.system or "", filled) if p)


def _sections(shared: dict, names: list[str]) -> str:
    """The shared material, once, each under its section heading."""
    out, done = [], set()
    for blank in names:
        section = SECTIONS[blank]
        if section in done or blank not in shared:
            continue
        done.add(section)
        if section == "FABRIC":
            out.append(f"FABRIC ({shared.get('fabric_name', '')}): {shared.get('fabric_definition', '')}")
        else:
            out.append(f"{section}:\n{shared[blank]}" if section in ("EVIDENCE", "TCL TODAY", "FACTS")
                       else f"{section}: {shared[blank]}")
    return "\n\n".join(out)


def build(recipe: dict, tasks: list[Task], shared: dict) -> Built:
    """One stacked call for `tasks`, under `recipe` (its `cache` order).
    `shared` holds the blanks given once: technology, evidence, and for a
    fabric call fabric_name, fabric_definition and tcl_today."""
    keys = [t.key for t in tasks]
    preamble = (
        "You are working for Tata Communications' emerging-technology radar. This one call carries "
        f"{len(tasks)} tasks about the same technology. Each task is a block below, headed "
        "\"### <key>: <name>\", and keeps its own rules. What the tasks share is given once, under its "
        "heading (TECHNOLOGY, EVIDENCE, and where given FACTS, or FABRIC and TCL TODAY).\n"
        "Reply with ONE JSON object and nothing else, no code fences. Its keys are exactly: "
        + ", ".join(keys) + ". Under each key put exactly the JSON that task asks for: where a task says "
        "\"reply with only a JSON object\" or \"array\", that object or array goes under its key. Answer every task.")
    instructions = "\n\n".join([preamble, *(_block(t, shared) for t in tasks)])
    tech_part = _sections(shared, ["technology", "facts", "evidence"])
    fabric_part = _sections(shared, ["fabric_name", "tcl_today"])
    closing = "Now answer every task, as one JSON object keyed as listed above."
    if recipe.get("cache") == "instructions":
        blocks, user = [instructions], "\n\n".join(p for p in (tech_part, fabric_part, closing) if p)
    else:  # evidence first: a technology's later calls reuse it
        blocks, user = [tech_part, instructions], "\n\n".join(p for p in (fabric_part, closing) if p)
    return Built(recipe_id=recipe["_id"], blocks=blocks, user=user, keys=keys,
                 skills=list(dict.fromkeys(t.skill for t in tasks)), tasks=tasks, shared=shared)


def parse(reply: str, built: Built, validators: dict) -> dict:
    """Each key's value checked by its skill's validator (skill name → fn(value,
    task) returning the clean value, or raising ValueError with the reason);
    a key that's missing or fails comes back as a Failure."""
    try:
        data = parse_json(reply)
    except ValueError as exc:
        return {k: Failure(f"the reply wasn't JSON: {exc}") for k in built.keys}
    if not isinstance(data, dict):
        return {k: Failure("the reply wasn't one JSON object") for k in built.keys}
    out: dict = {}
    for task in built.tasks:
        if task.key not in data:
            out[task.key] = Failure("the reply left this task out")
            continue
        check = validators.get(task.skill)
        try:
            out[task.key] = check(data[task.key], task) if check else data[task.key]
        except (ValueError, TypeError, KeyError) as exc:
            out[task.key] = Failure(str(exc) or "the answer didn't fit this task's rules")
    return out


def alone(llm, task: Task, shared: dict, check=None, on_call=None, cancelled=None):
    """One task asked on its own, with its skill's normal single call (the
    shared blanks and its own filled in): the answer as `check` cleans it, or
    a Failure saying why not."""
    rendered = PromptStore.get(task.skill).render(**{**shared, **task.values})

    def call() -> str:
        if on_call:
            on_call()
        return llm.ask(rendered)

    with with_context(skills=[task.skill], recipe=None):
        reply = call_with_backoff(call, cancelled)
    try:
        value = parse_json(reply)
        return check(value, task) if check else value
    except (ValueError, TypeError, KeyError) as exc:
        return Failure(str(exc) or "the answer didn't fit this task's rules")


def ask(llm, built: Built, validators: dict, defaults: dict | None = None, *, prefix: str = "",
        not_again=(), on_call=None, cancelled=None) -> tuple[dict, int]:
    """The stacked call, under the one rule (see the top): `prefix` goes before
    what's sent each time; `not_again` names skills whose failure isn't asked
    alone; `defaults` maps a skill to fn(reason) → the value a task that still
    failed takes. `on_call` runs before every call (to count it); `cancelled`
    stops the waits between tries of a call that errors. Returns (answers by
    key, how many tasks were asked alone)."""
    def call() -> str:
        if on_call:
            on_call()
        return llm.ask(f"{prefix}{built.user}", blocks=built.blocks)

    with with_context(recipe=built.recipe_id, skills=built.skills):
        out = parse(call_with_backoff(call, cancelled), built, validators)
        if out and all(isinstance(v, Failure) and v.reason.startswith("the reply wasn't") for v in out.values()):
            log.warning("stacked call %s returned no JSON; asking again", built.recipe_id)
            out = parse(call_with_backoff(call, cancelled), built, validators)
    retries = 0
    for task in built.tasks:
        if isinstance(out[task.key], Failure) and task.skill not in not_again:
            retries += 1
            log.info("%s · %s asked again alone: %s", built.shared.get("technology"), task.key, out[task.key].reason)
            out[task.key] = alone(llm, task, built.shared, validators.get(task.skill), on_call, cancelled)
        if isinstance(out[task.key], Failure) and task.skill in (defaults or {}):
            log.warning("%s · %s takes its default: %s",
                        built.shared.get("technology"), task.key, out[task.key].reason)
            out[task.key] = defaults[task.skill](out[task.key].reason)
    return out, retries
