# Pipeline B — Stage 1 (B1): Schema & Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give Pipeline B the two inputs a clip engine needs — *what footage to feed it* (`content_bank_url` / `target_creator`) and *at what specs* (`clip_min/max_len_s`, `caption_rules`, `banned_content`, `target_platforms`) — extracted per campaign, **honestly provenance-flagged**, from the ingested `description` **plus** the campaign's Whop product page. Land the Pipeline B schema (migration `0004`) at the same time.

**Architecture:** A **deterministic, CI-tested extraction core** (regex floor + merge/provenance logic) behind a `BaseExtractor` protocol, plus a **thin LLM adapter** and a **Whop-page fetcher** that are **manual-acceptance-only** (real key / real network, never in CI) — mirroring exactly how Stage 4 split the tested bot core from the `discord.py` adapter. Extraction can **never break Pipeline A's ingest**: no key, an LLM error, or a blocked Whop fetch all degrade gracefully to the regex/description-only floor and log.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x, Alembic, pydantic, httpx (Whop fetch), `anthropic` (new dep, LLM adapter only), structlog, pytest.

## Context

This is **Phase B1** of `PIPELINE_B_CLIP_FACTORY.md` (source of truth — see its **Empirical grounding (2026-07-14)** section and the **build-order note** under Phases). Pipeline A Stages 1–4 are merged. **Build B1 before B0** — B0's price quote is an operator procurement task, and there is no point proving the clip engine until we can determine what to feed it.

**Empirically-grounded decisions this plan encodes** (from the DB audit of 405 real `clipping`/`both` campaigns + web validation):
- **Footage is usually brand-provided** (Whop docs: *"the brand … usually [provides] the footage. You bring the cut,"* via Google Drive). `content_bank_url` is the **primary** acquisition input; `target_creator` matters only for VOD-type campaigns.
- **Extraction must be LLM-based, not regex.** Only 4% of descriptions carry an `@handle`, but creator names appear in prose in ~half the sample, and descriptions are **multilingual** (ES/AR/FR) — regex is a floor, not a solution.
- **Specs live on the Whop product page, not the ingested blurb** (length 10%, caption rules 6% in `description`). `campaigns.url` (fixed 2026-07-14) now points at the real `whop.com` product page; its `robots.txt` is `Allow: /` (only `/api/`, `/discover/search/*` disallowed) → fetchable under drop-don't-evade.

## Existing code this builds on

- `src/clipscore/db/models.py` — `Campaign` (`.url`, `.allowed_socials`, `.campaign_type`, `.requirements_raw`, `.status`). **Add new columns** + the four Pipeline B tables.
- `src/clipscore/ingest/extract.py` — `extract_requirements(description)` regex over free text; the **provenance discipline to mirror** (`'absent'`, not `'uncapped'`, on no match). Reuse its `money_to_float`/`views_to_int` helpers from `ingest/coerce.py`.
- `src/clipscore/ingest/contentrewards.py` + `ingest/detect.py` — the **fetch + robots + `classify_response` + `SourceHalted` (drop-don't-evade)** pattern to mirror for the Whop-page fetcher.
- `src/clipscore/config.py` — `Settings` (pydantic-settings, prefix `CLIPSCORE_`, has `user_agent`, `http_timeout_s`, `whop_base_url`). **Add extraction settings.**
- Alembic head is **`0003`** (alerts); new revision **`0004`** with `down_revision = "0003"`.
- `tests/test_migration_0003.py` — the migration-test pattern that WORKS here (subprocess + `CLIPSCORE_DB_URL` env; `alembic/env.py` overrides `sqlalchemy.url` from settings, so `Config.set_main_option` is a no-op — do NOT use it).
- `tests/conftest.py` — `session` fixture (in-memory SQLite, all tables from ORM).

## Global Constraints

Every task's requirements implicitly include these.

- **Honest coverage (the core discipline).** Every extracted field is nullable and carries its **source** in `extract_provenance` (JSON: field → `"description" | "whop_page" | "allowed_socials" | "absent"`). Provenance records **where the value came from, not which extractor found it** — a value read from the brief is `description` whether regex or the LLM pulled it (the regex-vs-LLM floor/ceiling comparison is a coverage-report concern, Task 4, not a per-field label). `allowed_socials` specifically marks a field **defaulted from A's ingested `allowed_socials` field, NOT read from brief text** — do not mislabel a default as `description` (CLAUDE.md: "track observed vs. guessed factors separately"). A field is NEVER populated without recording where it came from. **Absent ≠ empty**: "no cap found" is `absent`, not `0`. This is A's `cap_provenance` rule, generalized.
- **Extraction never breaks Pipeline A.** Extraction runs *after* A's ingest/upsert as a separate, guarded step. No API key, an LLM timeout/error, or a blocked Whop fetch → fall back to the regex/description-only floor, log, and continue. Ingest/scoring must return normally regardless. (Same "a Discord failure can never break ingest/scoring" guard as Stage 4.)
- **No new required secret.** The system runs with `CLIPSCORE_LLM_API_KEY` unset — it simply uses the regex floor. The LLM adapter is opt-in.
- **Compliance on the Whop fetch.** Honest `user_agent`; check `whop.com/robots.txt` (cached per run) before fetching a product page; a block/challenge/non-200 → `classify_response` → **log and skip** (fall back to description-only), **never circumvent**. Modest pacing; one page per campaign; short cache.
- **Scope to clippable campaigns.** Extract only for `campaign_type in ('clipping','both')`; skip `ugc` (nothing to clip).
- **Idempotent AND incremental (cost guard — the LLM is the spend).** Re-running overwrites a campaign's target/spec columns + provenance. But an LLM call per campaign is real money, and this data changes rarely, so the poll path re-extracts **only campaigns that need it** — `extract_provenance IS NULL` (never extracted) OR `requirements_raw` changed since the last extract. **Never re-extract all ~405 every 45-min cycle.** The full sweep over everything is the manual `clipscore extract --report` subcommand, not the poll.
- **`target_platforms` defaults to `allowed_socials`.** A already ingests `allowed_socials` at ~100% coverage — use it as the base; the extractor only narrows/overrides it when the brief is explicit. When defaulted, its provenance is `allowed_socials` (a guessed/inherited value), **not** `description`.
- **CI purity.** No test makes a real network call or a real LLM call. The Whop fetcher and LLM adapter are exercised only through mocks/fakes; the real adapters are manual-acceptance-only (documented, run by the operator).

---

## Task 1: Migration 0004 (campaigns columns + Pipeline B tables) + config

**Files:**
- Modify: `src/clipscore/db/models.py`
- Create: `alembic/versions/0004_pipeline_b_schema.py`
- Modify: `src/clipscore/config.py`
- Test: `tests/test_migration_0004.py`, `tests/test_pipeline_b_models.py`, `tests/test_config_extraction.py`

**Interfaces:**
- Produces: on `Campaign` — `content_bank_url: str|None`, `target_creator: str|None` (JSON array), `target_platforms: str|None` (JSON array), `clip_min_len_s: int|None`, `clip_max_len_s: int|None`, `caption_rules: str|None`, `banned_content: str|None`, `extract_provenance: str|None` (JSON). New models `ClipJob`, `SourceAsset`, `Clip`, `ClipMatch` (columns per `PIPELINE_B_CLIP_FACTORY.md` Data model). `Settings` fields `llm_api_key: str|None = None`, `llm_model: str = "claude-haiku-4-5"`, `extract_from_whop_page: bool = True`, `extract_enabled: bool = True`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config_extraction.py
from clipscore.config import Settings

def test_extraction_config_defaults():
    s = Settings(_env_file=None)  # hermetic — don't read the developer's .env
    assert s.llm_api_key is None
    assert s.llm_model == "claude-haiku-4-5"
    assert s.extract_from_whop_page is True
    assert s.extract_enabled is True
```

```python
# tests/test_pipeline_b_models.py
from sqlalchemy import select
from clipscore.db.models import Campaign, ClipJob, SourceAsset, Clip, ClipMatch

def test_campaign_new_columns_roundtrip(session):
    c = Campaign(source="contentrewards", external_id="x1", url="https://whop.com/x1",
                 status="active", content_bank_url="https://drive.google.com/abc",
                 target_creator='["@diego"]', target_platforms='["tiktok"]',
                 clip_min_len_s=15, clip_max_len_s=60, caption_rules="use #ad",
                 banned_content="no politics",
                 extract_provenance='{"content_bank_url":"whop_page"}')
    session.add(c); session.commit()
    got = session.execute(select(Campaign)).scalars().one()
    assert got.content_bank_url == "https://drive.google.com/abc"
    assert got.clip_min_len_s == 15 and got.clip_max_len_s == 60

def test_pipeline_b_tables_roundtrip(session):
    job = ClipJob(campaign_id="x1", source_type="campaign_provided",
                  source_ref="https://drive.google.com/abc", status="queued",
                  created_at="2026-07-14T00:00:00Z")
    session.add(job); session.commit()
    assert session.execute(select(ClipJob)).scalars().one().status == "queued"
```

```python
# tests/test_migration_0004.py
import subprocess, sqlite3, os, sys

def test_migration_adds_pipeline_b_schema(tmp_path):
    db = tmp_path / "m.db"
    env = {**os.environ, "CLIPSCORE_DB_URL": f"sqlite:///{db}"}
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(db)
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    ccols = {row[1] for row in con.execute("PRAGMA table_info(campaigns)")}
    con.close()
    assert {"clip_jobs", "source_assets", "clips", "clip_matches"} <= tables
    assert {"content_bank_url", "target_creator", "target_platforms", "clip_min_len_s",
            "clip_max_len_s", "caption_rules", "banned_content", "extract_provenance"} <= ccols
```

- [ ] **Step 2: Run to verify they fail** — `pytest tests/test_migration_0004.py tests/test_pipeline_b_models.py tests/test_config_extraction.py -v` (FAIL: no columns/models/config/`0004`).
- [ ] **Step 3: Implement** — add the columns + four models to `models.py` (follow the storage conventions: UUID→TEXT, money→REAL, arrays→JSON TEXT, ts→UTC ISO TEXT, serial→INTEGER PK AUTOINCREMENT, bool→INTEGER); write `0004` (additive `op.add_column` + `op.create_table`; the `campaigns` columns are all nullable so the migration is safe on the live DB); add the `Settings` fields.
- [ ] **Step 4: Verify** — the three test files pass; `pytest -q` stays green; `alembic upgrade head` then `alembic downgrade -1` round-trips.

---

## Task 2: Extraction core — regex floor + merge/provenance (CI-tested)

**Files:**
- Create: `src/clipscore/factory/__init__.py`, `src/clipscore/factory/extract.py`
- Test: `tests/test_factory_extract.py`

**Interfaces:**
- Produces: `ExtractedTargets` (pydantic: the 7 fields above + `provenance: dict[str,str]`); `BaseExtractor` protocol (`extract(description, page_text|None, base_platforms) -> ExtractedTargets`); `RegexExtractor` (deterministic — reuses `ingest/extract.py` patterns + adds a Drive/URL pattern for `content_bank_url` and an `@handle` pattern for `target_creator`); `merge_extractions(regex, llm, base_platforms) -> ExtractedTargets` (LLM wins per-field when present, else regex, else absent; provenance records the winning source); `apply_to_campaign(campaign, extracted)` (writes columns + `extract_provenance` JSON).

- [ ] **Step 1: Write the failing tests** — cover: `content_bank_url` pulled from a Google-Drive URL in text (provenance `description`); `@handle` → `target_creator`; no match → field `None` + provenance `absent`; `target_platforms` defaults to `base_platforms` (`allowed_socials`) when the brief is silent (provenance `allowed_socials`); `merge_extractions` prefers a non-null LLM field over regex and tags provenance `whop_page` when the value came only from `page_text`; `apply_to_campaign` serializes arrays to JSON and writes a provenance dict covering all 7 fields.

```python
# tests/test_factory_extract.py (representative)
from clipscore.factory.extract import RegexExtractor, merge_extractions, ExtractedTargets, apply_to_campaign
from clipscore.db.models import Campaign

def test_regex_pulls_drive_bank_and_handle():
    d = "Clip @diego content. Footage: https://drive.google.com/drive/folders/AbC"
    e = RegexExtractor().extract(d, None, ["tiktok"])
    assert e.content_bank_url == "https://drive.google.com/drive/folders/AbC"
    assert "@diego" in e.target_creator
    assert e.provenance["content_bank_url"] == "description"

def test_platforms_default_to_base_when_silent():
    e = RegexExtractor().extract("Clip our stuff.", None, ["tiktok", "instagram"])
    assert e.target_platforms == ["tiktok", "instagram"]
    assert e.provenance["target_platforms"] == "allowed_socials"  # defaulted, not read from text

def test_merge_prefers_llm_and_tags_whop_page():
    regex = ExtractedTargets(target_platforms=["tiktok"], provenance={})
    llm = ExtractedTargets(clip_min_len_s=15, clip_max_len_s=60,
                           provenance={"clip_min_len_s": "whop_page", "clip_max_len_s": "whop_page"})
    m = merge_extractions(regex, llm, ["tiktok"])
    assert m.clip_min_len_s == 15 and m.provenance["clip_min_len_s"] == "whop_page"

def test_apply_writes_json_and_provenance(session):
    c = Campaign(source="cr", external_id="x", url="u", status="active")
    apply_to_campaign(c, ExtractedTargets(target_creator=["@a"], target_platforms=["tiktok"],
                                          provenance={"target_creator": "description"}))
    assert c.target_creator == '["@a"]'
    assert '"target_creator": "description"' in c.extract_provenance
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** `factory/extract.py` — pure/deterministic; no network, no LLM import at module top. `RegexExtractor` is the floor; `merge_extractions` + `apply_to_campaign` hold the provenance logic. Multilingual note: regex only reliably catches URLs/handles — that's expected; the LLM adapter (Task 3) covers prose/other languages.
- [ ] **Step 4: Verify** — tests pass; `pytest -q` green.

---

## Task 3: Whop-page fetcher + LLM adapter (thin, manual-acceptance-only) + graceful pipeline

**Files:**
- Create: `src/clipscore/factory/whop.py` (product-page fetch), `src/clipscore/factory/extract_llm.py` (LLM adapter), `src/clipscore/factory/enrich.py` (the guarded orchestration)
- Test: `tests/test_factory_whop.py`, `tests/test_factory_enrich.py`
- Docs: add a **manual acceptance** note (how to run with a real key) to the plan's sibling doc / `docs/spikes/`.

**Interfaces:**
- `whop.py`: `fetch_page_text(url, client=None) -> str | None` — robots-checked (reuse the `contentrewards` pattern), honest UA, `classify_response`; on any block/non-200/`SourceHalted` returns `None` (log & skip, drop-don't-evade). CI tests use `httpx.MockTransport`.
- `extract_llm.py`: `LLMExtractor(BaseExtractor)` — builds one structured-output call (tool-use / JSON schema = the 7 fields + per-field provenance), model from `settings.llm_model`, key from `settings.llm_api_key`. **Manual-acceptance-only** — never invoked in CI. Raises/returns empty on no key.
- `enrich.py`: `enrich_campaign(session, campaign, settings, extractor=None, fetch=None) -> ExtractedTargets` — the guarded step: RegexExtractor always; if `extract_from_whop_page` and a key, fetch page text + run the LLM extractor; `merge_extractions`; `apply_to_campaign`; commit. Wrapped so ANY failure (no key, LLM error, blocked fetch) falls back to the regex result and never raises. `enrich_batch(session, settings, only_stale=True)` iterates `clipping`/`both` campaigns; when `only_stale` (the poll path) it selects only those with `extract_provenance IS NULL` or `requirements_raw` changed since last extract; `only_stale=False` is the full sweep (manual report path).

- [ ] **Step 1: Write the failing tests** (all with fakes — no real network/LLM):
  - `test_factory_whop.py`: MockTransport returning a product page → text returned; returning 403/challenge → `None` (drop-don't-evade); robots `Disallow: /` → `None`.
  - `test_factory_enrich.py`: with a `FakeExtractor` LLM returning richer fields → merged onto the campaign with `whop_page` provenance; with the LLM raising → campaign still gets the **regex floor** and `enrich_campaign` does not raise (the never-break-ingest guard); with `extract_enabled=False` → no-op.

```python
# tests/test_factory_enrich.py (the load-bearing guard test)
def test_llm_failure_falls_back_to_regex_and_never_raises(session, monkeypatch):
    c = Campaign(source="cr", external_id="x", url="https://whop.com/x",
                 status="active", campaign_type="clipping",
                 requirements_raw="Clip @diego. Footage https://drive.google.com/f/1",
                 allowed_socials='["tiktok"]')
    session.add(c); session.commit()
    class Boom:
        def extract(self, *a, **k): raise RuntimeError("llm down")
    from clipscore.factory import enrich
    from clipscore.config import Settings
    res = enrich.enrich_campaign(session, c, Settings(_env_file=None),
                                 extractor=Boom(), fetch=lambda *a, **k: "page text")
    assert c.content_bank_url == "https://drive.google.com/f/1"  # regex floor survived
    assert res is not None                                        # did not raise
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** the three modules. `whop.py` mirrors `contentrewards.fetch` (robots + `classify_response` + `SourceHalted`→`None`). `extract_llm.py` imports `anthropic` lazily inside the method (like the lazy `discord` import) so the package imports with the dep absent. `enrich.py` is the try/except guard. **Model-ID check:** `settings.llm_model` defaults to `claude-haiku-4-5`; if the API rejects the alias, use the dated ID (e.g. `claude-haiku-4-5-20251001`) — verify against the current Anthropic model list at implementation time.
- [ ] **Step 4: Verify** — tests pass; `pytest -q` green; confirm `import clipscore.factory.extract_llm` works with `anthropic` uninstalled (lazy import).
- [ ] **Step 5: Manual acceptance (operator, needs a real key)** — set `CLIPSCORE_LLM_API_KEY`, run `enrich_batch` against `clipscore.db` on a handful of campaigns, eyeball that `target_creator`/`content_bank_url`/specs look right and provenance is honest. Document the command. Not in CI.

---

## Task 4: Coverage calibration report (folded-in spike) + wire into poll

**Files:**
- Create: `src/clipscore/factory/coverage.py`, `docs/spikes/2026-07-14-clip-source-coverage-spike.md` (generated report)
- Modify: `src/clipscore/jobs/poll.py` (call `enrich_batch` as a guarded post-ingest step) or add a `clipscore extract` CLI subcommand
- Test: `tests/test_factory_coverage.py` (the counting logic on synthetic rows — not the LLM run)

**Interfaces:**
- `coverage.py`: `coverage_report(rows) -> dict` — pure counting over extraction results: per-field coverage %, provenance breakdown (`description`/`whop_page`/`regex`/`absent`), and footage-source distribution (`campaign_provided` vs `named_creator` vs `none`). CI-tested on synthetic inputs.
- A **manual** driver (script or `clipscore extract --report`) runs the real regex-floor vs LLM-ceiling vs +Whop-delta over a **stratified sample** (by niche + description-length bucket) of the 405 real campaigns and writes the Phase-0-style findings doc. Needs a key → operator-run.
- Wiring: `poll.run_once` calls `enrich_batch(session, settings, only_stale=True)` **after** score, guarded — so a poll re-extracts only new/changed campaigns, never all ~405. The full sweep + report is the manual `clipscore extract --report` subcommand. Extraction failures never affect the committed ingest/score.

- [ ] **Step 1: Write the failing test** — `coverage_report` over synthetic rows yields correct per-field % and provenance counts; footage-source classification buckets correctly.
- [ ] **Step 2: Run to verify it fails.**
- [ ] **Step 3: Implement** `coverage.py` + the guarded wiring + the manual report driver.
- [ ] **Step 4: Verify** — test passes; `pytest -q` green; the guarded wiring proven by a test that a raised extraction error leaves `run_once`'s ingest/score result intact.
- [ ] **Step 5: Manual acceptance (operator)** — run the report driver with a key; commit the generated `docs/spikes/2026-07-14-clip-source-coverage-spike.md` (floor/ceiling/+whop coverage tables + footage-source distribution) — the honest, numbers-backed answer to "how well can we clip these campaigns," and the calibration baseline for B3 matching.

---

## Definition of done

- `alembic upgrade head` lands `0004`; the four Pipeline B tables + eight `campaigns` columns exist; downgrade round-trips.
- The extraction **core** (regex + merge/provenance + apply) is fully CI-tested and deterministic.
- The **LLM adapter** and **Whop fetcher** are implemented, mocked in CI, and manual-acceptance verified by the operator with a real key; both degrade gracefully (no key / blocked fetch / LLM error) to the regex floor.
- Extraction **cannot break Pipeline A** — proven by a test that an extraction failure leaves `run_once`'s ingest/score result intact.
- A coverage report exists in `docs/spikes/` with real floor/ceiling/+whop numbers.
- `pytest -q` green; no real network or LLM call in CI.

## Out of scope (later phases)

Acquisition/download (B2), clip production + matching + captions (B3), the review dashboard (B4), cost/retention hardening (B5), and the Vizard adapter + price quote (B0) — see `PIPELINE_B_CLIP_FACTORY.md`.
