"""The summarizing step: one model call per page writes its summary,
technologies and scout's take, and calls out the signals from the run's
signal list. Never-miss signals add emphasis; a Can ignore rule sets a
qualifying page aside. A page with no signal is summarized exactly as before.

Nothing is cut: a page longer than the page-part size is split on paragraph
boundaries, the parts are summarized in parallel with the same prompt, and
the results are merged.

The prompt's opening, up to the page's address, is the same for every page
of a run, so it's sent as a block the provider reuses (split_fixed).

A page that couldn't be analysed, wholly or in part, says why:
analysis_error = {reason, detail, at}."""

import logging
import re
from concurrent.futures import ThreadPoolExecutor

from app.services.llm.context import carry, with_context
from app.services.llm import call_with_backoff, parse_json
from app.services.prompts import PromptStore
from app.services.signals.snapshot import prompt_lines
from app.services.timezone import now_utc

log = logging.getLogger(__name__)


def summarize_page(llm, url: str, text: str, snapshot: dict, cancelled=None) -> dict:
    """Analyse one page against the run's snapshot (signal_list,
    signals_hash, crawl_settings). Returns summary, technologies,
    scout_take, signals, ignored_by, signals_hash, parts, partial and
    analysis_error. signals_hash stays None when the analysis is incomplete,
    so the next re-check retries the page."""
    rows = snapshot.get("signal_list") or []
    settings = snapshot.get("crawl_settings") or {}
    prompt = PromptStore.get("article_summary")
    lines = prompt_lines(rows)

    def analyse(part_text: str) -> dict:
        return _analyse(llm, prompt, lines, rows, url, part_text, cancelled)

    parts = split_text(text, int(settings.get("page_part_chars") or 120000))
    if len(parts) == 1:
        result = analyse(text)
        if "failed" in result:
            return _unavailable(result, parts=None)
        return {**result, "signals_hash": snapshot.get("signals_hash"), "parts": None,
                "partial": False, "analysis_error": None}

    workers = max(1, int(settings.get("page_part_concurrency") or 4))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="part") as pool:
        results = [f.result() for f in [pool.submit(carry(analyse), part) for part in parts]]
    done = [r for r in results if "failed" not in r]
    if not done:
        return _unavailable(results[0], parts=len(parts))
    partial = len(done) < len(results)
    error = None
    if partial:
        failed = [r for r in results if "failed" in r]
        first = _error(failed[0])
        error = {"reason": "some parts failed",
                 "detail": f"{len(failed)} of {len(parts)} parts: {first['reason']}: {first['detail']}"[:200],
                 "at": first["at"]}

    merged = analyse("\n\n".join(f"[Part {i} of {len(parts)}] {r['summary']}"
                                 for i, r in enumerate(done, 1)))
    if "failed" in merged:  # keep what the parts said
        summary = "\n\n".join(r["summary"] for r in done)
        take = done[0]["scout_take"]
    else:
        summary, take = merged["summary"], merged["scout_take"]

    technologies: list[str] = []
    for r in done:
        technologies += [t for t in r["technologies"] if t not in technologies]
    signals = _dedupe([h for r in done for h in r["signals"]])
    ignore_rows = {r["ignored_by"] for r in done}
    ignored_by = None
    if not partial and not signals and len(ignore_rows) == 1:
        ignored_by = ignore_rows.pop()  # every part names the same rule, and no part has a hit
    return {"summary": summary, "technologies": technologies, "scout_take": take,
            "signals": signals, "ignored_by": ignored_by,
            "signals_hash": None if partial else snapshot.get("signals_hash"),
            "parts": len(parts), "partial": partial, "analysis_error": error}


def split_text(text: str, size: int) -> list[str]:
    """Parts of at most `size` characters, cut on paragraph boundaries; a
    single paragraph longer than a part is cut at the last space."""
    if len(text) <= size:
        return [text]
    parts: list[str] = []
    current = ""
    for para in re.split(r"\n\s*\n", text):
        while len(para) > size:
            if current:
                parts.append(current)
                current = ""
            cut = para.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            parts.append(para[:cut])
            para = para[cut:].lstrip()
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > size:
            parts.append(current)
            current = para
        else:
            current = candidate
    if current.strip():
        parts.append(current)
    return [p for p in parts if p.strip()]


def article_summary_values(url: str, text: str, lines: dict) -> dict:
    """The page-summary skill's blanks; `lines` is prompt_lines(signal list).
    The Skills page's preview fills them with this same function, so it shows
    exactly what a run sends."""
    return {"url": url, "text": text, "never_miss": lines["never_miss"], "can_ignore": lines["can_ignore"]}


MARK = "per-call"  # wrapped in private-use characters: no prompt or page holds it


def split_fixed(prompt, values: dict, per_call: tuple[str, ...]) -> tuple[str, str]:
    """The rendered prompt cut at the start of the line holding the first of
    the `per_call` blanks: (the fixed opening, the same for every call in a
    run, the rest). Joined, they are exactly prompt.render(**values). The
    opening (the instructions and the signal list, about 2,300 tokens) goes
    in `blocks` for the provider to reuse; it's over Anthropic's 512-token
    minimum for Haiku 5.5, below which nothing would be reused."""
    marked = prompt.render(**{**values, **{k: MARK + values[k] for k in per_call}})
    at = marked.find(MARK)
    if at < 0:  # the skill doesn't use them: nothing is fixed
        return "", prompt.render(**values)
    cut = marked.rfind("\n", 0, at) + 1
    return marked[:cut], marked[cut:].replace(MARK, "")


def _analyse(llm, prompt, lines: dict, rows: list[dict], url: str, text: str, cancelled) -> dict:
    """One call (a bad reply gets one retry). Returns the normalized result,
    or {"failed": ...} with the error or the unparseable reply."""
    fixed, rest = split_fixed(prompt, article_summary_values(url, text, lines), ("url", "text"))
    reply = ""
    for attempt in (1, 2):
        try:
            with with_context(skills=["article_summary"]):
                reply = call_with_backoff(lambda: llm.ask(rest, blocks=[fixed] if fixed.strip() else None),
                                          cancelled)
        except Exception as exc:  # a failed summary must not lose the document
            log.warning("summary failed for %s: %s", url, exc)
            return {"failed": "call", "error": str(exc)[:300]}
        try:
            data = parse_json(reply)
            if isinstance(data, dict):
                return normalise(data, rows, reply)
        except ValueError:
            pass
        log.warning("summary reply for %s was not the JSON asked for (attempt %d)", url, attempt)
    return {"failed": "reply", "reply": reply}


def _unavailable(failure: dict, parts: int | None) -> dict:
    """The page is kept exactly as before signals existed: the model's text
    when it ignored the JSON shape, otherwise a marker; analysis_error says
    why."""
    if failure.get("failed") == "reply" and failure.get("reply"):
        summary = failure["reply"]
    else:
        summary = f"(summary unavailable: {failure.get('error') or 'no usable reply'})"
    return {"summary": summary, "technologies": [], "scout_take": None, "signals": [],
            "ignored_by": None, "signals_hash": None, "parts": parts, "partial": False,
            "analysis_error": _error(failure), "failed": True}


def _error(failure: dict) -> dict:
    """Why one call failed, in a form that groups: a short reason, the
    error text (or the start of the unusable reply), and when."""
    if failure.get("failed") == "call":
        reason, detail = "model call failed", failure.get("error") or ""
    else:
        reason, detail = "reply not in the expected format", failure.get("reply") or "empty reply"
    return {"reason": reason, "detail": " ".join(detail.split())[:200],
            "at": now_utc()}


def _text(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def normalise(data: dict, rows: list[dict], reply: str = "") -> dict:
    """Plain-code clean-up of the model's reply against the signal list:
    a hit naming a never-miss row gets its id and current name; any other
    named development becomes "Other" with that name as its label; hits
    without a quote are dropped; never miss beats can ignore. A hit keeps
    its own technologies only when they're on the page's list (at most 3);
    otherwise it has none of its own and readers use the page's."""
    never = {r["name"].strip().lower(): r for r in rows if r["mode"] == "never_miss"}
    ignore = {r["name"].strip().lower(): r for r in rows if r["mode"] == "can_ignore"}
    techs = data.get("technologies")
    technologies = [str(t).strip().lower() for t in (techs if isinstance(techs, list) else []) if str(t).strip()]
    hits = []
    raw_hits = data.get("signals")
    for h in raw_hits if isinstance(raw_hits, list) else []:
        if not isinstance(h, dict):
            continue
        quote = _text(h.get("quote"))
        if not quote:
            continue
        name = _text(h.get("signal")) or ""
        row = never.get(name.lower())
        if row is not None:
            signal_id, signal_name, label = row["_id"], row["name"], None
        else:
            label = _text(h.get("label")) if name.lower() in ("other", "") else name
            if not label:
                continue
            signal_id, signal_name = "other", "Other"
        hit = {"signal_id": signal_id, "name": signal_name, "label": label,
               "headline": (_text(h.get("headline")) or "")[:160] or None,
               "what": _text(h.get("what")), "who": _text(h.get("who")),
               "when": _text(h.get("when")), "quote": quote,
               "implication": _text(h.get("implication"))}
        own = h.get("technologies")
        own = [t for t in dict.fromkeys(str(x).strip().lower() for x in (own if isinstance(own, list) else []))
               if t in technologies][:3]
        if own:
            hit["technologies"] = own
        hits.append(hit)
    hits = _dedupe(hits)
    rule = ignore.get((_text(data.get("ignore")) or "").lower())
    return {
        "summary": _text(data.get("summary")) or reply,
        "technologies": technologies,
        "scout_take": _text(data.get("scout_take")),
        "signals": hits,
        "ignored_by": rule["_id"] if rule is not None and not hits else None,
    }


def _dedupe(hits: list[dict]) -> list[dict]:
    seen, out = set(), []
    for h in hits:
        key = (h["signal_id"], (h.get("label") or "").lower(), h["quote"])
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out
