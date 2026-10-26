"""Builds install exactly the tested versions (code review CR19):
requirements.txt is exported from uv.lock, so the two must agree, and every
dependency in pyproject.toml must be pinned there."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _name(n: str) -> str:
    return re.sub(r"[-_.]+", "-", n).lower()


def test_requirements_match_the_lock():
    locked = {_name(p["name"]): p["version"] for p in tomllib.loads((ROOT / "uv.lock").read_text())["package"]}
    pinned = dict((_name(n), v) for n, v in re.findall(r"^([A-Za-z0-9_.\-]+)==([^\s;\\]+)",
                                                        (ROOT / "requirements.txt").read_text(), re.M))
    assert pinned and all(locked.get(n) == v for n, v in pinned.items()), \
        "requirements.txt is out of step with uv.lock: run uv export (see README)"
    wanted = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    assert {_name(re.split(r"[<>=!~\[ ]", d)[0]) for d in wanted} <= set(pinned)
