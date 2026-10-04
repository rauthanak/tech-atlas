import pytest

from app.services.llm import parse_json


def test_plain():
    assert parse_json('{"a": 1}') == {"a": 1}


def test_fenced():
    assert parse_json('```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}
    assert parse_json("```\n[1, 2]\n```") == [1, 2]


def test_wrapped_in_prose():
    assert parse_json('Here you go:\n{"a": {"b": 2}}\nHope that helps.') == {"a": {"b": 2}}
    assert parse_json("Result: [1, 2, 3] done") == [1, 2, 3]


def test_invalid():
    for bad in ("", "no json here", "{broken", "```json\n{oops\n```"):
        with pytest.raises(ValueError):
            parse_json(bad)
