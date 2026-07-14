# Manual Acceptance — LLM Extractor (Pipeline B, Stage 1 Task 3)

**Date:** 2026-07-14
**Scope:** `clipscore.factory.extract_llm.LLMExtractor` + `clipscore.factory.enrich.enrich_batch`.
Not exercised in CI — every CI test uses a fake extractor / fake fetch. This adapter needs a
real Anthropic API key, network access, and incurs billing per call.

## Prerequisites

- `pip install anthropic` (not a base dependency — installed only for manual runs).
- Set `CLIPSCORE_LLM_API_KEY` in `.env` (or the shell environment). Optionally override
  `CLIPSCORE_LLM_MODEL` (defaults to `claude-haiku-4-5`; if the API rejects the alias, use
  the dated ID, e.g. `claude-haiku-4-5-20251001` — check the current Anthropic model list).
- A populated `clipscore.db` with some `clipping`/`both` campaigns ingested (`clipscore poll`).

## Running it

```bash
python3 -c "
from clipscore.config import get_settings
from clipscore.db.session import get_engine, SessionLocal
from clipscore.factory.enrich import enrich_batch

settings = get_settings()
get_engine()  # binds SessionLocal as a side effect
with SessionLocal() as session:
    result = enrich_batch(session, settings, only_stale=True)
    print(result)
"
```

For a first eyeball pass on a handful of campaigns rather than the full stale set, filter the
query in a throwaway script (e.g. `select(Campaign).where(...).limit(5)`) and call
`enrich_campaign` directly per row instead of `enrich_batch`.

## First thing to check — `fetch_page_text` actually returns text

`whop.py` reuses `clipscore.ingest.detect.classify_response()` verbatim (per the Task 3
brief). That classifier's `"ok"` verdict requires the body to contain the literal
`self.__next_f.push` marker and be over 1000 bytes — both tuned for the
`contentrewards.com/discover` **listing** payload (Next.js RSC stream), not verified against
a real Whop **product page**. Before trusting any `whop_page`-provenance field from a live
run:

```bash
python3 -c "
from clipscore.factory.whop import fetch_page_text
print(fetch_page_text('https://whop.com/<some-real-product-route>'))
"
```

If this returns `None` for a page you can confirm loads fine in a browser, `classify_response`'s
criteria don't fit product pages (e.g. no RSC marker present, or a `/login` link on the page
trips the `_LOGIN` regex → `login_wall`) and need a Whop-specific verdict function before the
LLM path can ever see page text — until then `enrich_campaign` silently and correctly falls
back to the regex floor (never breaks), but every `whop_page`-sourced field will be empty.

## What to check

- `target_creator` / `content_bank_url` / `clip_min_len_s` / `clip_max_len_s` /
  `caption_rules` / `banned_content` look right against the campaign's actual
  `requirements_raw` and the live Whop product page.
- `extract_provenance` (JSON on the campaign row) is honest: fields sourced from the page
  are tagged `whop_page`, fields sourced from the description are tagged `description`, and
  anything not explicitly stated is `absent` — never a guessed value with a confident tag.
- Multilingual briefs (non-English `requirements_raw`) still extract sensibly.
- No exceptions bubble out even when a Whop page fetch is blocked/robots-disallowed for a
  given campaign (`enrich_campaign` must fall back to the regex floor silently either way).

Not automated because it requires a paid API key and live network access to Whop; this is a
one-time (or occasional, on model/prompt change) human spot-check, not a CI gate.
