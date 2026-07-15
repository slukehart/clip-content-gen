# Pipeline B — Stage 3 (B3): Clip Production + Matching + Captions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Turn an approved campaign into review-ready clips: acquire footage (B2) → send it to a clip engine → match finished clips back to live campaigns → suggest a compliant caption — wired as guarded, idempotent APScheduler jobs, plus a `clipscore clip` operator trigger.

**Architecture:** A **provider-agnostic OpenAI-compatible LLM client** (`factory/llm.py`, httpx-only) that B1's extractor and B3's captioner both use — so the model is pure config (default OpenRouter + Kimi). A **`BaseClipEngine`** with a CI **`FakeClipEngine`** and a manual-acceptance **Vizard** adapter. A **status-driven job runner** (`process_clip_jobs`) that advances each `clip_job` one stage per tick, every stage wrapped so a failure marks the job `failed` and never crashes the scheduler. Matching and captioning are pure/CI-tested; real Vizard + real OpenRouter runs are manual-acceptance-only.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x, httpx (LLM + clip-engine HTTP — **no new SDKs**), pydantic, APScheduler, structlog, pytest.

## Context

This is **Phase B3** of `PIPELINE_B_CLIP_FACTORY.md` (source of truth — see its **Phase B3** entry, **Data flow**, **Matching / categorization logic**, and **Clip output spec**). Pipeline A (Stages 1–4) and Pipeline B Stages B1 (schema+extraction) and B2 (acquisition) are merged. The Vizard API key is now in `.env` (`CLIPSCORE_VIZARD_API_KEY`), so B0b (the real adapter) is built here as a manual-acceptance module.

**Design decisions this plan encodes** (approved 2026-07-15):
- **LLM is provider-agnostic** via an OpenAI-compatible `/chat/completions` client over httpx. Default `llm_base_url=https://openrouter.ai/api/v1`, `llm_model=moonshotai/kimi-k2` (both overridable). This replaces B1's hardcoded `anthropic` SDK usage — extraction stays behavior-identical (tested against a fake client).
- **Clip engine behind `BaseClipEngine`**; `FakeClipEngine` for CI, real `VizardEngine` manual-acceptance-only.
- **Captions always carry an FTC `#ad` disclosure**, injected by a deterministic floor regardless of whether the campaign's `caption_rules` mention it; optional LLM enrichment on top.
- **`clipscore clip <campaign_id>` CLI trigger** ships now (operable before the B4 dashboard).

## Existing code this builds on

- `src/clipscore/factory/extract_llm.py` — `LLMExtractor(BaseExtractor)` (currently Anthropic tool-use). **Retrofit** to `factory/llm.py`; keep the class name + `extract(description, page_text, base_platforms)` signature so `factory/enrich.py` is untouched.
- `src/clipscore/factory/enrich.py` — the **never-raise guard** pattern (`try/except` → fallback, `session.commit()`) to mirror in every B3 job stage. Constructs `LLMExtractor(settings)` — must keep working.
- `src/clipscore/factory/acquire/run.py` — `acquire_job(session, clip_job, settings, *, registry=None, client=None, now=None) -> ClipJob` (B2), the `queued`→`acquired` stage the runner calls.
- `src/clipscore/scoring/board.py` — `eligible_latest_scores(session) -> list[tuple[Campaign, CampaignScore]]` (latest score per active/ingestable/non-ugc campaign). **Reuse for matching** — `CampaignScore.cvs_niche_percentile` is the CVS niche-percentile.
- `src/clipscore/db/models.py` — `ClipJob` (`status` ∈ `queued|acquiring|acquired|clipping|produced|matched|failed`), `SourceAsset` (`creator`, `platform`, `storage_uri`, `duration_s`), `Clip` (`source_asset_id`, `platform_variant`, `storage_uri`, `duration_s`, `transcript`, `engine`, `engine_clip_id`, `cost_usd`, `status` ∈ `produced|ready|posted|discarded`, `created_at`), `ClipMatch` (`clip_id`, `campaign_id`, `match_score`, `meets_requirements`, `suggested_caption`, `rank`). **No new schema.**
- `src/clipscore/config.py` — `Settings` (prefix `CLIPSCORE_`; has `llm_api_key`, `llm_model`, `http_timeout_s`, `raw_retention_days`). **Add fields.** `get_settings()` is `lru_cache`d.
- `src/clipscore/cli.py` — argparse subparsers → `main()`; `_extract` shows the pattern for a DB-backed subcommand (`get_engine()` + `SessionLocal()`).
- `src/clipscore/jobs/poll.py` — `build_scheduler(session_factory)` (APScheduler); extend it to also schedule the clip-factory tick.
- `tests/conftest.py` — `session` fixture (in-memory SQLite, all ORM tables).

## Global Constraints

Every task's requirements implicitly include these.

- **No stage crashes the scheduler.** Every job stage (`acquire`/`clipping`/`matching`/`caption`) and the `process_clip_jobs` loop are wrapped so any exception sets `clip_job.status="failed"` + `clip_job.error`, commits, and is swallowed — never propagated. Mirror `enrich_campaign` / `acquire_job`.
- **Idempotent & retryable.** `process_clip_jobs` selects only jobs in an advanceable status (`queued`, `acquired`, `produced`); a `matched`/`failed`/in-flight job is never re-picked. Re-running is safe (no duplicate `clips`/`clip_matches` for an already-advanced job).
- **No new schema.** Fill `clips`/`clip_matches` from migration `0004`. `clip_job.status` stays within its enum; the terminal success status for a job is `matched` (its clips become `ready`).
- **CI purity.** No test makes a real network / LLM / Vizard call. The LLM client, clip engine, and captioner are exercised through fakes/DI seams. Real `VizardEngine` and real OpenRouter/Kimi calls are **manual-acceptance-only**.
- **Small footprint.** HTTP via `httpx` (already a dep). **Do not add `anthropic`, `openai`, or any vendor SDK.** Task 1 removes the lazy `anthropic` import.
- **Compliance.** Every suggested caption contains an FTC `#ad` disclosure, guaranteed by the deterministic floor even when the LLM enrichment omits it and even when the campaign's `caption_rules` don't mention it. The **duplicate-deliverable warning** (don't post one clip to multiple campaigns for pay) is a **B4 dashboard** concern — B3 matching only ranks; it does not enforce single-post.
- **Honest scoring.** `match_score` is a screening signal (CVS niche-percentile × a spec-fit multiplier), not a payout guarantee — same discipline as A's CVS. `cvs_niche_percentile` missing → treated as `0.0`.

---

## Task 1: Provider-agnostic LLM client + retrofit B1 extractor (drop `anthropic`)

**Files:**
- Create: `src/clipscore/factory/llm.py`
- Modify: `src/clipscore/factory/extract_llm.py`, `src/clipscore/config.py`, `.env.example`
- Test: `tests/test_llm_client.py`, `tests/test_extract_llm_retrofit.py`

**Interfaces:**
- Produces `factory/llm.py`:
  - `LLMClient(base_url: str, model: str, api_key: str, timeout_s: int = 60, client: httpx.Client | None = None)`.
  - `LLMClient.chat_json(system: str, user: str) -> dict` — POST `{base_url}/chat/completions` with `response_format={"type": "json_object"}`, `temperature=0`; returns `json.loads(choices[0].message.content)`. Raises `LLMError` on missing key, non-200, or unparseable JSON.
  - `LLMClient.chat_text(system: str, user: str) -> str` — same call without `response_format`; returns the message content string.
  - `class LLMError(Exception)`.
  - `FakeLLMClient(json_result: dict | None = None, text_result: str | None = None)` — a test double with the same `chat_json`/`chat_text` methods returning the canned values.
- Produces on `Settings`: `llm_base_url: str = "https://openrouter.ai/api/v1"`; **changes** `llm_model` default to `"moonshotai/kimi-k2"`.
- `LLMExtractor` gains a `client=None` DI seam; its `extract(...)` signature and return type are unchanged.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_client.py
import httpx
from clipscore.factory.llm import LLMClient, LLMError, FakeLLMClient

def _mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))

def test_chat_json_posts_and_parses():
    seen = {}
    def h(req: httpx.Request):
        seen["url"] = str(req.url); seen["auth"] = req.headers.get("authorization")
        import json as _j; seen["body"] = _j.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"a": 1}'}}]})
    c = LLMClient("https://x.test/v1", "some/model", "KEY", client=_mock(h))
    assert c.chat_json("sys", "usr") == {"a": 1}
    assert seen["url"] == "https://x.test/v1/chat/completions"
    assert seen["auth"] == "Bearer KEY"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["model"] == "some/model"

def test_chat_text_returns_content():
    def h(req): return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})
    assert LLMClient("https://x.test/v1", "m", "K", client=_mock(h)).chat_text("s", "u") == "hello"

def test_non_200_raises_llmerror():
    def h(req): return httpx.Response(500, text="boom")
    import pytest
    with pytest.raises(LLMError):
        LLMClient("https://x.test/v1", "m", "K", client=_mock(h)).chat_text("s", "u")

def test_missing_key_raises():
    import pytest
    with pytest.raises(LLMError):
        LLMClient("https://x.test/v1", "m", "", client=_mock(lambda r: httpx.Response(200))).chat_text("s", "u")

def test_fake_client_returns_canned():
    assert FakeLLMClient(json_result={"k": "v"}).chat_json("s", "u") == {"k": "v"}
    assert FakeLLMClient(text_result="cap").chat_text("s", "u") == "cap"
```

```python
# tests/test_extract_llm_retrofit.py
from clipscore.factory.extract_llm import LLMExtractor
from clipscore.factory.llm import FakeLLMClient
from clipscore.config import Settings

def test_llm_extractor_parses_json_client_result():
    fake = FakeLLMClient(json_result={
        "content_bank_url": "https://drive.google.com/x",
        "target_creator": ["@diego"], "target_platforms": ["tiktok"],
        "clip_min_len_s": 15, "clip_max_len_s": 60,
        "caption_rules": "use #ad", "banned_content": None,
        "provenance": {"content_bank_url": "whop_page", "target_creator": "description",
                       "target_platforms": "description", "clip_min_len_s": "whop_page",
                       "clip_max_len_s": "whop_page", "caption_rules": "whop_page",
                       "banned_content": "absent"},
    })
    e = LLMExtractor(Settings(_env_file=None, llm_api_key="KEY"), client=fake)
    r = e.extract("Clip @diego", "page", ["tiktok"])
    assert r.content_bank_url == "https://drive.google.com/x"
    assert r.target_creator == ["@diego"]
    assert r.clip_min_len_s == 15
    assert r.provenance["content_bank_url"] == "whop_page"

def test_llm_extractor_no_key_raises():
    import pytest
    with pytest.raises(RuntimeError):
        LLMExtractor(Settings(_env_file=None)).extract("d", None, ["tiktok"])

def test_no_anthropic_import_anywhere():
    import pathlib
    src = pathlib.Path("src/clipscore/factory/extract_llm.py").read_text()
    assert "anthropic" not in src
```

- [ ] **Step 2: Run to verify they fail** — `pytest tests/test_llm_client.py tests/test_extract_llm_retrofit.py -v`.
- [ ] **Step 3: Implement.**
  - `factory/llm.py`: `LLMClient` owns/creates an `httpx.Client` (accept an injected one for tests; if it created its own, close it in a `finally`). `chat_json`/`chat_text` build the payload, send headers `{"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}`, and on any `httpx.HTTPError`, non-200, missing `choices`, or `json.JSONDecodeError` raise `LLMError`. Guard: empty `api_key` → `LLMError` before any request. `FakeLLMClient` implements the two methods returning canned values.
  - `extract_llm.py`: delete the lazy `import anthropic` and the `_TOOL_SCHEMA`/tool-use code. Add a `_SYSTEM_PROMPT` variant instructing a **JSON object** reply with exactly the 7 fields + a `provenance` object (each value `'description'|'whop_page'|'absent'`). In `extract`, build the client (`self._client or LLMClient(settings.llm_base_url, settings.llm_model, settings.llm_api_key, settings.http_timeout_s)`), call `chat_json`, and map the dict into `ExtractedTargets` exactly as the current code maps `tool_use.input` (reuse the `FIELDS`-based provenance defaulting). Keep the no-key `RuntimeError`.
  - `config.py`: add `llm_base_url`; change `llm_model` default to `"moonshotai/kimi-k2"`.
  - `.env.example`: add `CLIPSCORE_LLM_API_KEY=` (OpenRouter key), `CLIPSCORE_LLM_BASE_URL=https://openrouter.ai/api/v1`, `CLIPSCORE_LLM_MODEL=moonshotai/kimi-k2`.
- [ ] **Step 4: Verify** — new tests pass; `pytest -q` green (the existing `tests/test_config_extraction.py` asserts `llm_model == "claude-haiku-4-5"` — **update that assertion** to `"moonshotai/kimi-k2"`; it is the only test that pins the old default). Confirm `grep -rn anthropic src/` returns nothing.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(b3): provider-agnostic OpenAI-compatible LLM client; retrofit extractor off anthropic"`

---

## Task 2: `BaseClipEngine` + `FakeClipEngine` + variant-spec derivation + Vizard adapter (manual-acceptance) + config

**Files:**
- Create: `src/clipscore/factory/clip/__init__.py`, `src/clipscore/factory/clip/base.py`, `src/clipscore/factory/clip/vizard.py`
- Modify: `src/clipscore/config.py`, `.env.example`
- Test: `tests/test_clip_base.py`

**Interfaces:**
- Produces `clip/base.py`:
  - `ClipSpec(BaseModel)` — `platform_variant: str` (`"tiktok"|"reels"|"shorts"`), `min_len_s: int`, `max_len_s: int`.
  - `ProducedClip(BaseModel)` — `platform_variant: str`, `storage_uri: str`, `duration_s: int | None = None`, `transcript: str | None = None`, `engine: str`, `engine_clip_id: str | None = None`, `cost_usd: float | None = None`.
  - `BaseClipEngine(ABC)` — `name: str`; abstract `produce(self, source_uri: str, specs: list[ClipSpec], *, dest_dir: str) -> list[ProducedClip]`.
  - `derive_specs(campaign, settings) -> list[ClipSpec]` — one `ClipSpec` per platform the campaign accepts (`target_platforms` mapped via `{"tiktok":"tiktok","instagram":"reels","youtube":"shorts"}`; if `target_platforms` is empty/absent → all three variants). Lengths = the campaign's `[clip_min_len_s, clip_max_len_s]` when set, else the per-variant fallback: tiktok `(60,180)`, reels `(15,90)`, shorts `(15,60)`.
  - `FakeClipEngine(BaseClipEngine)` — `name="fake"`; `produce()` returns one `ProducedClip` per spec (`storage_uri=f"{dest_dir}/{spec.platform_variant}.mp4"`, `duration_s=spec.min_len_s`, `transcript="fake transcript"`, `engine="fake"`, `engine_clip_id=f"fake-{i}"`, `cost_usd=0.0`) — no I/O.
  - `build_engine(settings) -> BaseClipEngine` — returns `FakeClipEngine()` when `settings.clip_engine == "fake"`, else `VizardEngine(settings)`.
- Produces `clip/vizard.py`: `VizardEngine(BaseClipEngine)` — `name="vizard"`; `produce()` uses `httpx` against the Vizard REST API (submit → poll `clip_poll_interval_s` up to `clip_poll_timeout_s` → download files to `dest_dir`), reading `settings.vizard_api_key`. **Manual-acceptance-only; never invoked in CI.** Raises if no key.
- Produces on `Settings`: `vizard_api_key: str | None = None`, `clip_engine: str = "vizard"`, `clip_poll_interval_s: float = 10.0`, `clip_poll_timeout_s: float = 1800.0`, `clip_est_cost_usd: float = 0.0`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_clip_base.py
from clipscore.factory.clip.base import ClipSpec, ProducedClip, FakeClipEngine, derive_specs, build_engine
from clipscore.db.models import Campaign
from clipscore.config import Settings

def test_derive_specs_maps_platforms_and_uses_campaign_lengths():
    c = Campaign(source="cr", external_id="x", status="active",
                 target_platforms='["tiktok", "instagram"]', clip_min_len_s=20, clip_max_len_s=45)
    specs = derive_specs(c, Settings(_env_file=None))
    variants = {s.platform_variant for s in specs}
    assert variants == {"tiktok", "reels"}
    assert all(s.min_len_s == 20 and s.max_len_s == 45 for s in specs)

def test_derive_specs_defaults_all_variants_with_fallback_lengths_when_silent():
    c = Campaign(source="cr", external_id="y", status="active", target_platforms=None,
                 clip_min_len_s=None, clip_max_len_s=None)
    specs = {s.platform_variant: s for s in derive_specs(c, Settings(_env_file=None))}
    assert set(specs) == {"tiktok", "reels", "shorts"}
    assert (specs["tiktok"].min_len_s, specs["tiktok"].max_len_s) == (60, 180)
    assert (specs["shorts"].min_len_s, specs["shorts"].max_len_s) == (15, 60)

def test_fake_engine_produces_one_clip_per_spec():
    specs = [ClipSpec(platform_variant="tiktok", min_len_s=60, max_len_s=180),
             ClipSpec(platform_variant="reels", min_len_s=15, max_len_s=90)]
    clips = FakeClipEngine().produce("s3://src.mp4", specs, dest_dir="/m/clips/abc")
    assert [c.platform_variant for c in clips] == ["tiktok", "reels"]
    assert all(c.engine == "fake" and c.cost_usd == 0.0 for c in clips)
    assert clips[0].storage_uri == "/m/clips/abc/tiktok.mp4"

def test_build_engine_selects_fake():
    assert build_engine(Settings(_env_file=None, clip_engine="fake")).name == "fake"
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** `clip/base.py` (pydantic models, `derive_specs`, `FakeClipEngine`, `build_engine`) and `clip/vizard.py` (lazy nothing — plain `httpx`; reads `settings.vizard_api_key`, raises `RuntimeError` if absent; submit/poll/download with backoff+timeout, mapping Vizard clip results → `ProducedClip`). Add the `Settings` fields. `.env.example`: add `CLIPSCORE_VIZARD_API_KEY=`, `CLIPSCORE_CLIP_ENGINE=vizard`.
- [ ] **Step 4: Verify** — `tests/test_clip_base.py` passes; `pytest -q` green. Confirm `VizardEngine` is imported by nothing in the CI test path.
- [ ] **Step 5: Manual acceptance (operator, needs the key)** — with `CLIPSCORE_VIZARD_API_KEY` set and `CLIPSCORE_CLIP_ENGINE=vizard`, run `VizardEngine.produce()` on one real source video; confirm spec-compliant 9:16 clips download and cost is recorded. Document the command. Not in CI.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(b3): BaseClipEngine + FakeClipEngine + variant derivation + Vizard adapter (manual)"`

---

## Task 3: Clipping job — produce clips, write rows, delete source (never-raise)

**Files:**
- Create: `src/clipscore/factory/clip/produce.py`
- Test: `tests/test_clip_produce.py`

**Interfaces:**
- Consumes: `build_engine`/`FakeClipEngine`/`derive_specs`/`ProducedClip` (Task 2); `ClipJob`, `SourceAsset`, `Clip`, `Campaign` models; `clipscore.time.utcnow_iso`.
- Produces `produce.py`: `run_clipping(session, clip_job, settings, *, engine=None, now=None) -> ClipJob` — for an `acquired` `clip_job`: load its `SourceAsset` (the one with `clip_job_id == clip_job.id` and non-null `storage_uri`); derive specs from `clip_job`'s `Campaign`; call `(engine or build_engine(settings)).produce(source_asset.storage_uri, specs, dest_dir=<media_dir>/clips/<clip_job.id>)`; write a `Clip` row per `ProducedClip` (`status="produced"`, `created_at=now`); **delete the source file** (`os.remove(source_asset.storage_uri)` best-effort) and null `source_asset.storage_uri`; set `clip_job.status="produced"`, `error=None`; commit. Wrapped so any failure → `status="failed"` + `error`, commit, never raises.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_clip_produce.py
import os, uuid
from sqlalchemy import select
from clipscore.db.models import ClipJob, SourceAsset, Clip, Campaign
from clipscore.factory.clip.produce import run_clipping
from clipscore.factory.clip.base import FakeClipEngine, BaseClipEngine
from clipscore.config import Settings
from clipscore.time import utcnow_iso

def _setup(session, tmp_path, **camp):
    now = utcnow_iso()
    c = Campaign(id="c1", source="cr", external_id="e1", status="active",
                 first_seen_at=now, last_seen_at=now, target_platforms='["tiktok"]', **camp)
    j = ClipJob(campaign_id="c1", source_type="campaign_provided", source_ref="ref",
                status="acquired", created_at=now)
    session.add_all([c, j]); session.commit()
    src = tmp_path / "src.mp4"; src.write_bytes(b"x" * 50)
    sa = SourceAsset(clip_job_id=j.id, creator="diego", platform="campaign_provided",
                     source_url="ref", storage_uri=str(src), duration_s=600, downloaded_at=now)
    session.add(sa); session.commit()
    return j, src

def _settings(tmp_path): return Settings(_env_file=None, media_dir=str(tmp_path))

def test_clipping_writes_clips_and_deletes_source(session, tmp_path):
    j, src = _setup(session, tmp_path)
    run_clipping(session, j, _settings(tmp_path), engine=FakeClipEngine())
    assert j.status == "produced"
    clips = session.execute(select(Clip)).scalars().all()
    assert len(clips) == 1 and clips[0].platform_variant == "tiktok" and clips[0].status == "produced"
    assert not src.exists()  # immediate post-clip retention
    sa = session.execute(select(SourceAsset)).scalars().one()
    assert sa.storage_uri is None

def test_clipping_engine_error_marks_failed_never_raises(session, tmp_path):
    j, src = _setup(session, tmp_path)
    class Boom(BaseClipEngine):
        name = "boom"
        def produce(self, *a, **k): raise RuntimeError("engine down")
    out = run_clipping(session, j, _settings(tmp_path), engine=Boom())
    assert out.status == "failed" and out.error
    assert src.exists()  # source not deleted on failure
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** `produce.py` with an inner function doing the work and an outer `try/except` guard (mirror `enrich_campaign`). Use `storage.ensure_parent`/`os.makedirs` for the clips dir; source deletion is best-effort (`try/except OSError`), and only happens **after** the clip rows are written and before the final `produced` status commit.
- [ ] **Step 4: Verify** — tests pass; `pytest -q` green.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(b3): clipping job — produce clips, persist rows, delete source (guarded)"`

---

## Task 4: Matching — candidate campaigns, `match_score`, ranked `clip_matches`

**Files:**
- Create: `src/clipscore/factory/clip/match.py`
- Test: `tests/test_clip_match.py`

**Interfaces:**
- Consumes: `eligible_latest_scores` (`scoring/board.py`); `Clip`, `SourceAsset`, `ClipMatch`, `Campaign`, `CampaignScore` models.
- Produces `match.py`:
  - `_VARIANT_PLATFORM = {"tiktok": "tiktok", "reels": "instagram", "shorts": "youtube"}`.
  - `match_clip(session, clip) -> list[dict]` — pure computation (no writes). Load `clip`'s `SourceAsset` for `creator` + the clip's `platform_variant`. For each `(campaign, score)` from `eligible_latest_scores(session)`: **candidate iff** `target_creator` overlaps `creator` (normalized: lowercase, strip leading `@`/spaces; any entry equals the creator) **AND** the campaign's `target_platforms` (lowercased) contains `_VARIANT_PLATFORM[clip.platform_variant]` **AND** the clip length passes the window (`clip.duration_s` within `[clip_min_len_s, clip_max_len_s]` when both set; pass if unset). Hard failures **exclude**. For each candidate compute `spec_fit = 1.0` if the campaign has an explicit length window (`clip_min_len_s` or `clip_max_len_s` not None) else `0.9`; `match_score = (score.cvs_niche_percentile or 0.0) * spec_fit`. Sort candidates by `match_score` descending, assign `rank` `1..n`, `meets_requirements = 1` for all (candidacy already required the hard pass). Return list of dicts `{campaign_id, match_score, meets_requirements, rank}`.
  - `run_matching(session, clip_job, *, now=None) -> ClipJob` — for every `Clip` whose `SourceAsset.clip_job_id == clip_job.id` and `status == "produced"`: compute `match_clip`, write a `ClipMatch` row per candidate; set `clip_job.status="matched"`; commit. (Captioning is applied in Task 5, invoked by the runner right after matching.) Guarded — any failure → `failed` + error, commit, never raises.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_clip_match.py
from sqlalchemy import select
from clipscore.db.models import Clip, SourceAsset, ClipMatch, Campaign, CampaignScore, ClipJob
from clipscore.factory.clip.match import match_clip, run_matching
from clipscore.time import utcnow_iso

def _camp(session, cid, pct, **kw):
    now = utcnow_iso()
    c = Campaign(id=cid, source="cr", external_id=cid, status="active", access_status="ingestable",
                 campaign_type="clipping", first_seen_at=now, last_seen_at=now,
                 target_creator='["@diego"]', target_platforms='["tiktok"]', **kw)
    session.add(c)
    session.add(CampaignScore(campaign_id=cid, scored_at=now, cvs_niche_percentile=pct))
    session.commit()

def _clip(session, variant="tiktok", dur=90, creator="diego"):
    now = utcnow_iso()
    j = ClipJob(campaign_id="c1", source_type="url", source_ref="u", status="produced", created_at=now)
    session.add(j); session.commit()
    sa = SourceAsset(clip_job_id=j.id, creator=creator, platform="url", downloaded_at=now)
    session.add(sa); session.commit()
    clip = Clip(source_asset_id=sa.id, platform_variant=variant, duration_s=dur,
                storage_uri="x.mp4", engine="fake", status="produced", created_at=now)
    session.add(clip); session.commit()
    return j, clip

def test_match_ranks_by_cvs_percentile_times_specfit(session):
    _camp(session, "c1", 0.9, clip_min_len_s=60, clip_max_len_s=120)   # windowed -> spec_fit 1.0
    _camp(session, "c2", 0.95, clip_min_len_s=None, clip_max_len_s=None)  # no window -> spec_fit 0.9
    _, clip = _clip(session, dur=90)
    rows = match_clip(session, clip)
    ids = [r["campaign_id"] for r in rows]
    assert ids == ["c1", "c2"]  # 0.9*1.0=0.90 > 0.95*0.9=0.855
    assert rows[0]["rank"] == 1 and rows[0]["match_score"] == 0.9

def test_length_out_of_window_excludes(session):
    _camp(session, "c1", 0.9, clip_min_len_s=60, clip_max_len_s=80)
    _, clip = _clip(session, dur=200)  # too long
    assert match_clip(session, clip) == []

def test_platform_mismatch_excludes(session):
    _camp(session, "c1", 0.9)  # target_platforms tiktok
    _, clip = _clip(session, variant="shorts")  # -> youtube, not accepted
    assert match_clip(session, clip) == []

def test_run_matching_writes_rows_and_sets_status(session):
    _camp(session, "c1", 0.9, clip_min_len_s=60, clip_max_len_s=120)
    j, clip = _clip(session, dur=90)
    run_matching(session, j)
    assert j.status == "matched"
    m = session.execute(select(ClipMatch)).scalars().all()
    assert len(m) == 1 and m[0].campaign_id == "c1" and m[0].rank == 1 and m[0].meets_requirements == 1
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** `match.py`. Parse JSON array columns with a small helper (`json.loads` guarded to `[]`, mirroring `enrich._platforms`). `run_matching` wrapped in the never-raise guard.
- [ ] **Step 4: Verify** — tests pass; `pytest -q` green.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(b3): clip→campaign matching (CVS-percentile × spec-fit, ranked, hard-exclude)"`

---

## Task 5: Captioning — deterministic `#ad` floor + optional LLM enrichment

**Files:**
- Create: `src/clipscore/factory/clip/caption.py`
- Test: `tests/test_clip_caption.py`

**Interfaces:**
- Consumes: `LLMClient`/`FakeLLMClient` (Task 1); `Campaign`, `Clip`, `ClipMatch` models.
- Produces `caption.py`:
  - `AD_TAG = "#ad"`.
  - `caption_floor(campaign) -> str` — deterministic: start from `campaign.caption_rules` text (or `""`); **guarantee** `AD_TAG` is present (append `" #ad"` if not already present, case-insensitive). Never empty — if `caption_rules` is absent, the floor is just `"#ad"`.
  - `suggest_caption(campaign, clip, settings, *, llm=None) -> str` — compute the floor. If `settings.llm_api_key` is set, call `(llm or LLMClient(settings.llm_base_url, settings.llm_model, settings.llm_api_key, settings.http_timeout_s)).chat_text(system, user)` where `user` includes `clip.transcript` + `campaign.caption_rules`; take the returned text, then **re-enforce `AD_TAG`** (append if missing). On any `LLMError`/exception, fall back to the floor. Return value **always contains `#ad`**.
  - `run_caption(session, clip_job, settings, *, llm=None) -> ClipJob` — for each `Clip` of the job's `SourceAsset`(s) with `status=="produced"`: **always** set `clip.status="ready"` (a clip with no matches still reaches the review queue, just uncaptioned); **if** the clip has a rank-1 `ClipMatch`, resolve its campaign (`session.get(Campaign, match.campaign_id)`) and set `match.suggested_caption = suggest_caption(campaign, clip, settings, llm=llm)`. Commit. Guarded — never raises (a caption failure leaves the floor caption / logs, does not fail the job).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_clip_caption.py
from clipscore.db.models import Campaign, Clip
from clipscore.factory.clip.caption import caption_floor, suggest_caption
from clipscore.factory.llm import FakeLLMClient
from clipscore.config import Settings

def _camp(**kw): return Campaign(source="cr", external_id="x", status="active", **kw)
def _clip(): return Clip(source_asset_id=1, platform_variant="tiktok", transcript="great moment",
                         engine="fake", status="produced", created_at="2026-07-15T00:00:00Z")

def test_floor_injects_ad_when_rules_silent():
    assert caption_floor(_camp(caption_rules=None)) == "#ad"

def test_floor_preserves_rules_and_ensures_ad():
    out = caption_floor(_camp(caption_rules="Tag @brand"))
    assert "Tag @brand" in out and "#ad" in out

def test_floor_does_not_double_ad():
    out = caption_floor(_camp(caption_rules="cool #ad"))
    assert out.lower().count("#ad") == 1

def test_llm_enrichment_still_forces_ad():
    # LLM returns a caption WITHOUT #ad -> final must still contain it
    s = Settings(_env_file=None, llm_api_key="KEY")
    out = suggest_caption(_camp(caption_rules="Tag @brand"), _clip(), s,
                          llm=FakeLLMClient(text_result="An epic clip you have to see"))
    assert "#ad" in out and "epic clip" in out

def test_no_key_uses_floor():
    out = suggest_caption(_camp(caption_rules="Tag @brand"), _clip(), Settings(_env_file=None))
    assert out.strip().startswith("Tag @brand") and "#ad" in out
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** `caption.py`. Case-insensitive `#ad` presence check. `run_caption` guarded.
- [ ] **Step 4: Verify** — tests pass; `pytest -q` green.
- [ ] **Step 5: Manual acceptance (operator, needs the OpenRouter key)** — with `CLIPSCORE_LLM_API_KEY` set, run `suggest_caption` on a real clip; confirm the enrichment reads well AND `#ad` is present. Not in CI.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(b3): captioning — deterministic #ad floor + optional LLM enrichment"`

---

## Task 6: Job runner + idempotency + scheduler wiring + `clipscore clip` CLI

**Files:**
- Create: `src/clipscore/jobs/clipfactory.py`
- Modify: `src/clipscore/jobs/poll.py`, `src/clipscore/cli.py`
- Test: `tests/test_clipfactory.py`, `tests/test_cli_clip.py`

**Interfaces:**
- Consumes: `acquire_job` (`factory/acquire/run.py`); `run_clipping` (Task 3); `run_matching` (Task 4); `run_caption` (Task 5); `build_engine` (Task 2); `ClipJob`, `Campaign` models; `utcnow_iso`.
- Produces `jobs/clipfactory.py`:
  - `create_clip_job(session, campaign_id, settings, *, source_type=None, source_ref=None, now=None) -> ClipJob` — resolve the campaign (`session.get(Campaign, campaign_id)`; `None` → `ValueError`). If `source_type`/`source_ref` not given: prefer `campaign.content_bank_url` → `("campaign_provided", content_bank_url)`; else the first `target_creator` entry → `("youtube", entry)`; else `ValueError("no acquirable source for campaign")`. Write `ClipJob(status="queued", est_cost_usd=settings.clip_est_cost_usd, created_at=now)`; commit; return it.
  - `process_clip_jobs(session, settings, *, registry=None, engine=None, llm=None, now=None) -> dict` — select `ClipJob`s with `status in ("queued", "acquired", "produced")`; for each, call `_advance` inside a per-job `try/except` that on failure sets `status="failed"` + `error` and commits (the loop never raises). Returns a count dict (`{"advanced": n, "failed": m}`).
  - `_advance(session, job, settings, *, registry, engine, llm, now)` — dispatch by status: `queued` → `acquire_job(session, job, settings, registry=registry, now=now)`; `acquired` → `run_clipping(session, job, settings, engine=engine, now=now)`; `produced` → `run_matching(session, job, now=now)` then `run_caption(session, job, settings, llm=llm)`.
- Produces (poll.py): `build_scheduler` also adds an interval job calling `process_clip_jobs` (guarded), id `"clip_factory"`.
- Produces (cli.py): `clipscore clip <campaign_id> [--source-type T] [--source-ref R]` → `create_clip_job` and print the new job id + status.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_clipfactory.py
from sqlalchemy import select
from clipscore.db.models import ClipJob, SourceAsset, Clip, Campaign
from clipscore.jobs import clipfactory
from clipscore.factory.clip.base import BaseClipEngine, FakeClipEngine
from clipscore.factory.acquire.base import BaseAcquirer, AcquisitionResult
from clipscore.config import Settings
from clipscore.time import utcnow_iso

def _settings(tmp_path): return Settings(_env_file=None, media_dir=str(tmp_path))

def test_create_clip_job_from_content_bank(session):
    now = utcnow_iso()
    session.add(Campaign(id="c1", source="cr", external_id="e1", status="active",
                         first_seen_at=now, last_seen_at=now,
                         content_bank_url="https://drive.google.com/uc?id=A")); session.commit()
    j = clipfactory.create_clip_job(session, "c1", Settings(_env_file=None))
    assert j.status == "queued" and j.source_type == "campaign_provided"
    assert j.source_ref == "https://drive.google.com/uc?id=A"

def test_create_clip_job_unknown_campaign_raises(session):
    import pytest
    with pytest.raises(ValueError):
        clipfactory.create_clip_job(session, "nope", Settings(_env_file=None))

def test_process_advances_queued_through_matched(session, tmp_path):
    now = utcnow_iso()
    session.add(Campaign(id="c1", source="cr", external_id="e1", status="active",
                         access_status="ingestable", campaign_type="clipping",
                         first_seen_at=now, last_seen_at=now,
                         target_platforms='["tiktok"]', target_creator='["@diego"]')); session.commit()
    j = ClipJob(campaign_id="c1", source_type="campaign_provided", source_ref="ref",
                status="queued", created_at=now); session.add(j); session.commit()
    # fake acquirer writes a file + sets acquired; fake engine produces a clip
    class _Acq(BaseAcquirer):
        source_type = "campaign_provided"; requires_authorization = False
        def acquire(self, source_ref, dest_path, **kw):
            import os; os.makedirs(dest_path.rsplit("/",1)[0], exist_ok=True)
            open(dest_path + ".mp4","wb").write(b"x"*30)
            return AcquisitionResult(status="acquired", storage_uri=dest_path+".mp4", bytes=30,
                                     creator="diego", platform="campaign_provided", duration_s=90)
    reg = {"campaign_provided": _Acq()}
    s = _settings(tmp_path)
    # queued -> acquired
    clipfactory.process_clip_jobs(session, s, registry=reg, engine=FakeClipEngine())
    # acquired -> produced
    clipfactory.process_clip_jobs(session, s, registry=reg, engine=FakeClipEngine())
    # produced -> matched (+captions)
    clipfactory.process_clip_jobs(session, s, registry=reg, engine=FakeClipEngine())
    session.refresh(j)
    assert j.status == "matched"
    assert session.execute(select(Clip)).scalars().first().status == "ready"

def test_matched_job_is_not_repicked(session, tmp_path):
    now = utcnow_iso()
    j = ClipJob(campaign_id="c1", source_type="url", source_ref="u", status="matched", created_at=now)
    session.add(j); session.commit()
    res = clipfactory.process_clip_jobs(session, _settings(tmp_path), engine=FakeClipEngine())
    assert res["advanced"] == 0

def test_stage_crash_marks_failed_never_raises(session, tmp_path):
    now = utcnow_iso()
    j = ClipJob(campaign_id="c1", source_type="campaign_provided", source_ref="ref",
                status="acquired", created_at=now); session.add(j); session.commit()
    class Boom(BaseClipEngine):
        name="boom"
        def produce(self, *a, **k): raise RuntimeError("boom")
    clipfactory.process_clip_jobs(session, _settings(tmp_path), engine=Boom())
    session.refresh(j)
    assert j.status == "failed" and j.error
```

```python
# tests/test_cli_clip.py
from clipscore.cli import build_parser

def test_clip_subcommand_parses():
    args = build_parser().parse_args(["clip", "c1", "--source-type", "url", "--source-ref", "http://x/v.mp4"])
    assert args.cmd == "clip" and args.campaign_id == "c1"
    assert args.source_type == "url" and args.source_ref == "http://x/v.mp4"
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** `jobs/clipfactory.py`, the `build_scheduler` edit (add the guarded `process_clip_jobs` interval job; a session per tick via `session_factory`), and the `clip` subparser + `_clip` handler in `cli.py` (mirror `_extract`: `get_engine()`, `SessionLocal()`, call `create_clip_job`, print result; catch `ValueError` and print a friendly message).
- [ ] **Step 4: Verify** — both test files pass; `pytest -q` green.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(b3): clip-factory job runner (idempotent, guarded) + scheduler wiring + clipscore clip CLI"`

---

## Definition of done

- `factory/llm.py` is the single OpenAI-compatible LLM client; `extract_llm.py` uses it and `anthropic` is gone; extraction behavior is unchanged (fake-client tested).
- `clipscore clip <campaign_id>` queues a job; `process_clip_jobs` drives it `queued→acquired→produced→matched` on the `FakeClipEngine`, producing `clips` (→ `ready`) with ranked `clip_matches` and `#ad`-bearing captions.
- Every stage is guarded (a crash → `failed`+error, scheduler never dies) and idempotent (no re-pick of `matched`/`failed`).
- The clipping stage deletes the source file after producing clips.
- Real `VizardEngine` and real OpenRouter/Kimi caption enrichment are implemented, mocked in CI, and manual-acceptance-verified with the keys in `.env`.
- `pytest -q` green; no real network/LLM/Vizard call in CI; no new SDK dependency.

## Out of scope (later phases)

The review dashboard + duplicate-deliverable warning UI + "mark posted" → `outcomes` (B4), cost/retention hardening beyond the immediate post-clip source delete (B5). A Klap adapter / self-host engine remain config-switch stubs.
