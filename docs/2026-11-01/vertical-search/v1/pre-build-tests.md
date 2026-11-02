# Pre-build tests for S3 (1 Nov, read-only, nothing stored)

## 1. Web search limited to the radar's websites

- 123 switched-on, collectable website hosts.
- One Anthropic web search (`web_search_20250305`, `max_uses` 1) for "post-quantum cryptography", with `allowed_domains` set to all 123 hosts: **accepted, 10 results**, all from radar websites (arxiv.org, gsma.com, nature.com, ncbi.nlm.nih.gov, microsoft.com, image-ppubs.uspto.gov).
- With the first 50 hosts: accepted, 10 results. With the first 20: accepted, 0 results (none of those 20 sites had a match).
- **Result:** the whole list goes in one search. No splitting into groups is needed (K = all).

## 2. OpenAlex with the key

- One request each, most-cited first, last three years, 5 per page:

  | Name | Total papers | Top citations |
  |---|---|---|
  | post-quantum cryptography | 5,796 | 150, 140, 135, 98, 90 |
  | quantum key distribution | 5,935 | 198, 183, 155, 136, 120 |
  | quantum random number generation | 183 | 85, 44, 28, 19, 18 |

- OpenAlex's own headers: each request costs **$0.001** of a **$1.00** daily allowance (`x-ratelimit-cost-usd`, `x-ratelimit-limit-usd`), so about 1,000 requests a day. The allowance resets daily.
- A vertical search uses about 6 OpenAlex requests (papers, grants, counts), about $0.006.
- Without a key the allowance is $0.10 (about 100 requests). The 1 Nov collection's 20 paper searches page through up to 2,000 results each, which is why OpenAlex refused 18 searches that night.

## 3. Espacenet

Skipped: the EPO keys are not set. The place shows greyed out with why.
