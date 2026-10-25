# tech-atlas: standing rules

This is the API, worker and agents of the Emerging Technology Radar. Its portal is `../tech-lens`.

## Keep the client documents in step

Some changes alter what the product does or how people use it. That covers:
- an endpoint the portal uses;
- a job, an agent or a skill (`seeds/prompts.json`, `seeds/recipes.json`);
- a setting;
- a checkpoint or gate rule;
- a decision kind, or what a person can undo;
- what reaches the Point of View;
- a container or deployment step.

For any of these, update in the same piece of work, without being asked:
- the business process;
- the technical architecture;
- the Product Guide;
- the Administrator's Training Manual. Part 4 of the manual explains each skill and how each blank is filled, so update it whenever a skill's text, blanks or fill functions change.

These documents live outside this repo, in `../final_deliverable/` and `../artifacts/`. `../AGENTS.md` lists every source file and how to re-render each one. Also add an entry to the client change log (`docs/2026-10-20/1/make_change_log.py`).

When you finish, say which documents changed. If none needed to, say why in one line.
