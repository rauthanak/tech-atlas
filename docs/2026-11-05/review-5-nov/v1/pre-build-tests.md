# Pre-build tests (read-only, nothing stored)

Run before any code, on the live database through `docker compose exec -T mongo mongosh tech_atlas` and the signed-in API client. Nothing is written, no button is pressed, and no job is started. Test 4 is the only one that calls the model, and it doesn't save its result.

## 1. Are today's market figures on their page? (spec decision 1)

- For every latest assessment whose Addressable market measure has a `figure`:
  - find the cited page (its latest visit by `page_key`);
  - search its full text and its summary for the amount in the usual written forms ("312.4 million", "$312M", "0.31 billion", "USD 312").
- Report:
  - figures found on their page;
  - figures not found;
  - pages with no text kept.
- Look at five of the not-found cases by hand to see why.
- **Decides:** keep showing older figures until re-assessed (most found), or hide them now (many not found).

## 2. Does a Point of View quote a score after it was changed by hand? (S1's rewrite prompt)

- For every active `hand_score`, `tata_entry` and `override` decision:
  - compare its `at` with the technology's latest Point of View `composed_at`;
  - where the Point of View is older, search its text for the radar's old score or the old priority.
- Also check what the Point of View page shows for that score today: the live value or the old one.
- **Decides:** the exact wording of the row's note.

## 3. How many are "too early to place"? (S2)

- Count the catalog technologies by effective evidence verdict (thin, not credible, enough, strong, not judged), and by assessed or not.
- Expected from the 5 Nov count: about 251 thin and 14 not credible, all unassessed.
- List the 14 not-credible ones with their reasons, to check that the wording reads well to a leader.

## 4. What do the five new parts cost, and are they any good? (S5)

- On two technologies with Points of View (federated learning, plus one with thin evidence), run the v12 prompt through the skill preview (`services/prompts/preview.py`), which doesn't save.
- Report for each:
  - tokens in and out, and cost, against its current Point of View;
  - the five parts as written;
  - how many bullets the citation check would drop.
- Compare federated learning's parts with Tata's slide (customer need, alternatives, value chain, risks, current developments).
- **Decides:** whether the page summaries are enough input, before step 5 is built.
