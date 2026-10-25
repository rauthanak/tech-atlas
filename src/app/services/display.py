"""How a technology is named on screen and in prompts: its label (the name
as a person or the organizer wrote it, with capitals), else its stored name."""


def display_name(t: dict, fallback: str | None = None) -> str:
    """"QUIC", not "quic"; `fallback` (usually its id) when it has neither."""
    return t.get("label") or t.get("name") or fallback or ""
