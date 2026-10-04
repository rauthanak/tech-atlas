"""Every skill in the seeding data uses exactly the placeholders its stage
fills in. A mismatch breaks that stage with a KeyError at run time, so it is
caught here, before anything is deployed."""

from app.api.prompts import EXPECTED_VARIABLES, _extract_variables
from app.services.db import seeding


def test_seeded_skills_match_their_placeholders():
    for skill in seeding.read_list("prompts"):
        found = set(_extract_variables(skill["prompt"]))
        assert found == set(skill.get("variables") or []), skill["name"]
        if skill["name"] in EXPECTED_VARIABLES:
            assert found == EXPECTED_VARIABLES[skill["name"]], skill["name"]
