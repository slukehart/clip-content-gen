# Pipeline B — Stage B5: Cost & Retention Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Harden the (now real-Vizard-proven) clip factory: a monthly **credit** cap that blocks paid runs before they overspend, persistence of the raw `creditsUsed`, clip-file retention, an on-demand `clipscore process` command, richer Vizard virality params, and a batch of carried-over minor fixes.

**Architecture:** Vizard bills **1 credit = 1 minute of source video** (proven 2026-07-15; no API trim lever), so the cap is denominated in **credits**, not dollars. The operator enters the source length in minutes at queue time; `est_credits = ceil(minutes)` feeds a monthly projection checked in `run_clipping` immediately before the paid engine call (queue + acquire stay free). An over-budget job goes to a new terminal `blocked` status (distinct from `failed`, never retried). Real `creditsUsed` returned by Vizard is persisted onto the job and is what accumulates into the month-to-date total. Retention deletes clip files on mark-posted and on an age sweep. All new logic is CI-pure (fakes / `httpx.MockTransport` / in-memory DB); the real-network virality run is manual-acceptance-only.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x + Alembic, httpx (`MockTransport` in CI), pydantic-settings, structlog, FastAPI, pytest.

## Context

This is **Phase B5** of `PIPELINE_B_CLIP_FACTORY.md` (source of truth — see its **Phase B5** entry, committed 2026-07-15). Pipeline A Stages 1–4 and Pipeline B Stages B1–B4.5 are merged; the real Vizard integration was proven end-to-end on 2026-07-15 (see CLAUDE.md status + the `vizard-api-contract` memory). Branch `pipeline-b-stage-5-cost-retention` is checked out.

**Design decisions this plan encodes (approved 2026-07-15):**
- **Cap in CREDITS, not USD.** `$/credit` is plan-dependent and defaults to `0.0` (a dollar cap would silently never fire); `creditsUsed` is exact and 1:1 with source minutes.
- **Monthly cap only — no per-job cap.** Operator-entered minutes are the *estimate* feeding the monthly projection, not a separate ceiling.
- **`blocked` is a new status**, distinct from `failed`, NOT in `_ADVANCEABLE_STATUSES`; the operator re-queues after raising the cap or at month rollover.
- **Honest scoring:** the estimate gates; the real `creditsUsed` accounts.
- **Retention is clips-only** (passthrough keeps no source file).
- **Virality params never affect credit cost.**

## Existing code this builds on

- `src/clipscore/config.py` — `Settings` (prefix `CLIPSCORE_`, `.env`). Has `media_dir="media/"`, `vizard_usd_per_credit=0.0`, `clip_engine="vizard"`, `raw_retention_days=14`, `http_timeout_s`. **Add fields in Tasks 2, 5, 7, 8.**
- `src/clipscore/db/models.py` — `ClipJob` (`id, campaign_id, source_type, source_ref, status, est_cost_usd, error, created_at`), `Clip` (`id, source_asset_id, storage_uri, duration_s, status, created_at, cost_usd, engine, engine_clip_id, transcript, platform_variant`), `ClipMatch` (`id, clip_id, campaign_id, match_score, meets_requirements, suggested_caption, rank`), `SourceAsset` (`clip_job_id, storage_uri, source_url, creator, platform`). **Migrated + extended in Task 1.**
- `src/clipscore/time.py` — `utcnow_iso()`, `et_month_bounds_utc(now=None) -> (start_z, next_z)` (UTC ISO-`Z` strings bounding the current ET month).
- `src/clipscore/web/queries.py` — `monthly_cost_usd(session, now=None)` sums `Clip.cost_usd` over the ET month (the sibling pattern for Task 2's credits helper).
- `src/clipscore/factory/clip/produce.py` — `run_clipping` (never-raise, rollback-FIRST guard) + `_run_clipping_inner` (selects the job's `SourceAsset`, `engine.produce(source_asset.source_url, spec, dest_dir=...)`, writes `Clip` rows `status="produced"`, retention delete guarded by `if source_asset.storage_uri:`). **Cap gate + creditsUsed persistence + path fix in Tasks 3 & 8.**
- `src/clipscore/factory/clip/base.py` — `ClipSpec(min_len_s, max_len_s)`, `ProducedClip(platform_variant, storage_uri, duration_s, transcript, engine, engine_clip_id, cost_usd)`, `BaseClipEngine.produce(source_uri, spec, *, dest_dir) -> list[ProducedClip]`, `FakeClipEngine` (3 clips), `derive_specs(campaign, settings) -> ClipSpec`, `build_engine(settings)`. **`ProducedClip.credits_used` + `ClipSpec.keyword` added in Tasks 3 & 7.**
- `src/clipscore/factory/clip/vizard.py` — `VizardEngine.produce` → `_submit` (payload `{videoUrl, videoType, lang, preferLength:[0]}` + `ext` for type 1) → `_poll` → `_download` (reads `videos` + `creditsUsed`, splits `creditsUsed*rate/n`). `self._transport` MockTransport seam. **Virality params + creditsUsed exposure in Tasks 3 & 7.**
- `src/clipscore/jobs/clipfactory.py` — `create_clip_job(session, campaign_id, settings, *, source_type=None, source_ref=None, now=None)`, `process_clip_jobs(session, settings, *, registry=None, engine=None, llm=None, now=None) -> {"advanced","failed"}`, `_ADVANCEABLE_STATUSES=("queued","acquired","produced")`, `_advance`. **`est_minutes` param + per-tick cap in Tasks 4 & 8.**
- `src/clipscore/jobs/poll.py` — `build_scheduler(session_factory)` adds interval jobs; `clip_factory_job` wraps `process_clip_jobs` in a guarded tick. **Retention job wired in Task 5.**
- `src/clipscore/web/actions.py` — `create_manual_campaign(session, *, title, niche, content_bank_url, target_creator, settings, now=None)`, `mark_posted(session, match_id, *, now=None)`, `create_clip_job` reuse. **`est_minutes` + retention-on-post in Tasks 4 & 5.**
- `src/clipscore/web/app.py` — FastAPI routes; every handler calls `templates.TemplateResponse("name.html", {"request": request, ...})`. `/manual` GET+POST. **TemplateResponse arg order in Task 8; `/manual` form field in Task 4.**
- `src/clipscore/web/templates/manual.html` — the manual-entry form. **Field added in Task 4.**
- `src/clipscore/cli.py` — argparse; `_clip`, `build_parser`. **`--source-minutes`, `process`, `prune` in Tasks 4, 5, 6.**
- `src/clipscore/factory/enrich.py` — `enrich_campaign` never-raise (falls back to regex floor). **Rollback-FIRST alignment in Task 8.**
- `alembic/versions/0006_add_outcome_clip_id.py` — the newest migration (format template for Task 1).
- `tests/conftest.py` — `session` fixture (in-memory SQLite, all ORM tables). `tests/test_clip_vizard.py` — `_engine(handler, tmp_path, **over)` builds a `VizardEngine` with a `MockTransport`.

## Global Constraints

Every task's requirements implicitly include these (verbatim from the approved design):

- **Cap is in CREDITS, not USD.** 1 credit = 1 source minute. There is **no per-job cap**; operator-entered minutes feed the monthly projection only.
- **Cap gate lives in `run_clipping`, right before the paid Vizard call.** Queue + acquire stay free. The gate runs inside the existing never-raise guard.
- **`blocked` is distinct from `failed`**, is NOT in `_ADVANCEABLE_STATUSES`, and is never auto-retried.
- **Honest scoring:** the pre-flight estimate gates; the real `creditsUsed` is what accumulates into month-to-date.
- **No stage crashes the scheduler.** Every guard keeps its rollback-FIRST never-raise contract; new scheduler jobs (retention) are wrapped like `clip_factory_job`.
- **CI purity.** No real network / Vizard / LLM in tests — fakes, `httpx.MockTransport`, in-memory DB. Operator-entered minutes need no network. The real-Vizard virality run is manual-acceptance-only.
- **Small footprint.** No new dependencies (httpx, alembic already present).
- **Retention is clips-only + guarded `os.remove`** (file may already be gone).
- **Migration `0007` is the ONLY schema change.**

---

## Task 1: Migration 0007 — `est_minutes`, `credits_used`, `clip_matches` unique constraint

**Files:**
- Create: `alembic/versions/0007_b5_cost_retention.py`
- Modify: `src/clipscore/db/models.py` (`ClipJob`, `ClipMatch`)
- Test: `tests/test_migration_0007.py`

**Interfaces:**
- Produces: `ClipJob.est_minutes: int | None`, `ClipJob.credits_used: int | None`; `ClipMatch` gains `UniqueConstraint("clip_id", "campaign_id", name="uq_clipmatch_clip_campaign")`. Consumed by Tasks 2, 3, 4.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration_0007.py
import pytest
from sqlalchemy.exc import IntegrityError

from clipscore.db.models import ClipJob, ClipMatch


def test_clip_job_has_est_minutes_and_credits_used(session):
    job = ClipJob(campaign_id="c1", source_type="passthrough", source_ref="u",
                  status="queued", est_minutes=14, credits_used=None, created_at="2026-07-15T00:00:00Z")
    session.add(job)
    session.commit()
    assert job.est_minutes == 14 and job.credits_used is None


def test_clip_matches_unique_clip_campaign(session):
    session.add(ClipMatch(clip_id=1, campaign_id="c1", rank=1))
    session.commit()
    session.add(ClipMatch(clip_id=1, campaign_id="c1", rank=1))
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_migration_0007.py -v`
Expected: FAIL — `TypeError: 'est_minutes' is an invalid keyword argument for ClipJob` (and the unique test errors on the same import/attr).

- [ ] **Step 3: Update the ORM models**

In `src/clipscore/db/models.py`, add two columns to `ClipJob` (after `created_at`'s siblings, keep `created_at` last is fine — add before it or after; order is cosmetic):

```python
class ClipJob(Base):
    __tablename__ = "clip_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(String, index=True)
    source_type: Mapped[str] = mapped_column(String)
    source_ref: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    est_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    est_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credits_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String)
```

Add a `__table_args__` unique constraint to `ClipMatch`:

```python
class ClipMatch(Base):
    __tablename__ = "clip_matches"
    __table_args__ = (UniqueConstraint("clip_id", "campaign_id", name="uq_clipmatch_clip_campaign"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_id: Mapped[int] = mapped_column(Integer, index=True)
    campaign_id: Mapped[str] = mapped_column(String, index=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    meets_requirements: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggested_caption: Mapped[str | None] = mapped_column(String, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

(`UniqueConstraint` is already imported at the top of `models.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_migration_0007.py -v`
Expected: PASS (conftest builds tables from the ORM, so both new columns and the constraint are live).

- [ ] **Step 5: Write the Alembic migration**

```python
# alembic/versions/0007_b5_cost_retention.py
"""B5: clip_jobs.est_minutes + credits_used; clip_matches unique(clip_id, campaign_id)

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clip_jobs", sa.Column("est_minutes", sa.Integer(), nullable=True))
    op.add_column("clip_jobs", sa.Column("credits_used", sa.Integer(), nullable=True))
    # SQLite cannot ALTER ADD CONSTRAINT -> batch mode rebuilds the table.
    with op.batch_alter_table("clip_matches") as b:
        b.create_unique_constraint("uq_clipmatch_clip_campaign", ["clip_id", "campaign_id"])


def downgrade():
    with op.batch_alter_table("clip_matches") as b:
        b.drop_constraint("uq_clipmatch_clip_campaign", type_="unique")
    op.drop_column("clip_jobs", "credits_used")
    op.drop_column("clip_jobs", "est_minutes")
```

- [ ] **Step 6: Verify the migration applies to a throwaway DB**

Run: `CLIPSCORE_DB_URL=sqlite:///_b5_migtest.db alembic upgrade head && rm -f _b5_migtest.db`
Expected: exits 0, ending at revision `0007` (no error). (`alembic.ini`/`env.py` read `CLIPSCORE_DB_URL`.)

- [ ] **Step 7: Commit**

```bash
git add alembic/versions/0007_b5_cost_retention.py src/clipscore/db/models.py tests/test_migration_0007.py
git commit -m "feat(b5): migration 0007 — est_minutes, credits_used, clip_matches unique"
```

---

## Task 2: Config + credit accounting helpers

**Files:**
- Create: `src/clipscore/factory/clip/cost.py`
- Modify: `src/clipscore/config.py` (add `monthly_cap_credits`)
- Test: `tests/test_clip_cost.py`

**Interfaces:**
- Produces: `Settings.monthly_cap_credits: int` (default `0` = uncapped).
- Produces: `est_credits(minutes: int | None) -> int` — `int(minutes)` if truthy, else `0`.
- Produces: `month_credits_used(session, now=None) -> int` — sum of `ClipJob.credits_used` for jobs whose `created_at` falls in the current ET month (reuses `et_month_bounds_utc`). Consumed by Task 3. Lives in `factory/clip/` (not `web/`) so `produce.py` imports it without a factory→web dependency.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clip_cost.py
from datetime import datetime, timezone

from clipscore.db.models import ClipJob
from clipscore.factory.clip.cost import est_credits, month_credits_used


def test_est_credits():
    assert est_credits(14) == 14
    assert est_credits(0) == 0
    assert est_credits(None) == 0


def test_month_credits_used_sums_current_et_month(session):
    session.add_all([
        ClipJob(campaign_id="c", source_type="passthrough", source_ref="u",
                status="produced", credits_used=14, created_at="2026-07-10T12:00:00Z"),
        ClipJob(campaign_id="c", source_type="passthrough", source_ref="u",
                status="produced", credits_used=6, created_at="2026-07-20T12:00:00Z"),
        ClipJob(campaign_id="c", source_type="passthrough", source_ref="u",
                status="produced", credits_used=99, created_at="2026-06-15T12:00:00Z"),  # prior month
        ClipJob(campaign_id="c", source_type="passthrough", source_ref="u",
                status="queued", credits_used=None, created_at="2026-07-11T12:00:00Z"),  # no credits yet
    ])
    session.commit()
    now = datetime(2026, 7, 25, tzinfo=timezone.utc)
    assert month_credits_used(session, now=now) == 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_clip_cost.py -v`
Expected: FAIL — `ModuleNotFoundError: clipscore.factory.clip.cost`.

- [ ] **Step 3: Add the config field**

In `src/clipscore/config.py`, add after `vizard_usd_per_credit`:

```python
    monthly_cap_credits: int = 0  # 0 = uncapped; else block paid jobs projected over this in the ET month
```

- [ ] **Step 4: Implement the cost helpers**

```python
# src/clipscore/factory/clip/cost.py
"""Credit accounting for the B5 monthly cap. Vizard bills 1 credit = 1 minute
of SOURCE video, so the cap is denominated in credits (not USD, which is
plan-dependent and defaults to 0.0). `month_credits_used` sums the REAL
`creditsUsed` persisted on completed jobs this ET month; `est_credits`
converts an operator-entered source length (minutes) into a pre-flight
estimate. Lives in factory/ so produce.py needs no web import."""
from sqlalchemy import select

from clipscore.db.models import ClipJob
from clipscore.time import et_month_bounds_utc


def est_credits(minutes: int | None) -> int:
    """Pre-flight credit estimate from an operator-entered source length."""
    return int(minutes) if minutes else 0


def month_credits_used(session, now=None) -> int:
    """Sum of actual `credits_used` across clip_jobs created in the current
    ET calendar month. Jobs that have not yet run (credits_used IS NULL) add
    nothing."""
    start, nxt = et_month_bounds_utc(now)
    rows = session.execute(
        select(ClipJob.credits_used).where(
            ClipJob.created_at >= start, ClipJob.created_at < nxt
        )
    ).scalars().all()
    return int(sum(c or 0 for c in rows))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_clip_cost.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/clipscore/config.py src/clipscore/factory/clip/cost.py tests/test_clip_cost.py
git commit -m "feat(b5): monthly_cap_credits config + credit accounting helpers"
```

---

## Task 3: Cost-cap gate + `blocked` status + persist `creditsUsed`

**Files:**
- Modify: `src/clipscore/factory/clip/base.py` (add `ProducedClip.credits_used`; `FakeClipEngine` sets it)
- Modify: `src/clipscore/factory/clip/vizard.py` (`_download` sets `credits_used` on each `ProducedClip`)
- Modify: `src/clipscore/factory/clip/produce.py` (`_run_clipping_inner`: cap gate + persist)
- Modify: `src/clipscore/jobs/clipfactory.py` (docstring note — `blocked` already excluded since it's not in `_ADVANCEABLE_STATUSES`)
- Test: `tests/test_clip_cost_gate.py`

**Interfaces:**
- Consumes: `est_credits`, `month_credits_used` (Task 2); `ClipJob.est_minutes`, `ClipJob.credits_used` (Task 1).
- Produces: `ProducedClip.credits_used: int | None` (project-level `creditsUsed`, identical on every clip of one run). `run_clipping` sets a job to `status="blocked"` when `settings.monthly_cap_credits > 0 and month_credits_used(session) + est_credits(job.est_minutes) > cap`, WITHOUT calling the engine; otherwise persists `clip_job.credits_used = produced[0].credits_used`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clip_cost_gate.py
from clipscore.config import Settings
from clipscore.db.models import Campaign, Clip, ClipJob, SourceAsset
from clipscore.factory.clip.base import BaseClipEngine, ClipSpec, ProducedClip
from clipscore.factory.clip.produce import run_clipping
from clipscore.time import utcnow_iso


def _seed(session, *, est_minutes, credits_used_prior=0):
    # run_clipping calls month_credits_used(session) with the REAL now, so the
    # current-month rows must be stamped with utcnow_iso() (NOT a hardcoded
    # date) or the test breaks outside July 2026.
    now = utcnow_iso()
    session.add(Campaign(id="c1", source="manual", external_id="c1",
                         campaign_type="clipping", status="active",
                         access_status="ingestable", first_seen_at=now,
                         last_seen_at=now))
    if credits_used_prior:
        session.add(ClipJob(campaign_id="c1", source_type="passthrough", source_ref="u",
                            status="produced", credits_used=credits_used_prior,
                            created_at=now))
    job = ClipJob(campaign_id="c1", source_type="passthrough", source_ref="u",
                  status="acquired", est_minutes=est_minutes, created_at=now)
    session.add(job)
    session.flush()
    session.add(SourceAsset(clip_job_id=job.id, source_url="https://youtu.be/abc",
                            platform="passthrough", storage_uri=None))
    session.commit()
    return job


class _BoomEngine(BaseClipEngine):
    name = "boom"
    def produce(self, source_uri, spec, *, dest_dir):
        raise AssertionError("engine must NOT be called when over the cap")


class _StubEngine(BaseClipEngine):
    name = "stub"
    def produce(self, source_uri, spec, *, dest_dir):
        return [ProducedClip(storage_uri=f"{dest_dir}/clip-0.mp4", duration_s=30,
                             engine="stub", engine_clip_id="s0", cost_usd=0.0, credits_used=14)]


def test_over_cap_blocks_without_calling_engine(session):
    job = _seed(session, est_minutes=20)
    settings = Settings(_env_file=None, monthly_cap_credits=10)
    run_clipping(session, job, settings, engine=_BoomEngine())
    session.refresh(job)
    assert job.status == "blocked"
    assert session.query(Clip).count() == 0


def test_projection_includes_prior_spend(session):
    job = _seed(session, est_minutes=5, credits_used_prior=8)  # 8 (spent) + 5 (est) = 13 > 10
    settings = Settings(_env_file=None, monthly_cap_credits=10)
    run_clipping(session, job, settings, engine=_BoomEngine())
    session.refresh(job)
    assert job.status == "blocked"


def test_under_cap_runs_and_persists_credits_used(session):
    job = _seed(session, est_minutes=5)
    settings = Settings(_env_file=None, monthly_cap_credits=0)  # uncapped
    run_clipping(session, job, settings, engine=_StubEngine())
    session.refresh(job)
    assert job.status == "produced"
    assert job.credits_used == 14
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_clip_cost_gate.py -v`
Expected: FAIL — `ProducedClip` has no `credits_used` field / job never becomes `blocked`.

- [ ] **Step 3: Add `credits_used` to `ProducedClip` and `FakeClipEngine`**

In `src/clipscore/factory/clip/base.py`, add the field to `ProducedClip`:

```python
class ProducedClip(BaseModel):
    platform_variant: str | None = None
    storage_uri: str
    duration_s: int | None = None
    transcript: str | None = None
    engine: str
    engine_clip_id: str | None = None
    cost_usd: float | None = None
    credits_used: int | None = None  # project-level creditsUsed (same on every clip of one run)
```

In `FakeClipEngine.produce`, add `credits_used=0` to each `ProducedClip(...)`.

- [ ] **Step 4: Expose `creditsUsed` from the Vizard adapter**

In `src/clipscore/factory/clip/vizard.py`, `_download`, set `credits_used=credits_used` on each `ProducedClip(...)` it appends (the raw project value is already in scope as `credits_used`):

```python
                produced.append(ProducedClip(
                    platform_variant=None,
                    storage_uri=dest_path,
                    duration_s=ms // 1000 if ms else None,
                    transcript=clip.get("transcript"),
                    engine="vizard",
                    engine_clip_id=str(clip.get("videoId")) if clip.get("videoId") else None,
                    cost_usd=per_clip_cost,
                    credits_used=credits_used,
                ))
```

- [ ] **Step 5: Add the cap gate + persist to `_run_clipping_inner`**

In `src/clipscore/factory/clip/produce.py`: import the helpers at the top, and add the gate as the FIRST thing in `_run_clipping_inner` (before selecting the source asset — it must run before any paid work), then persist `credits_used` after the produce loop.

```python
from clipscore.factory.clip.cost import est_credits, month_credits_used
```

At the top of `_run_clipping_inner`, before the `source_asset = ...` select:

```python
    cap = settings.monthly_cap_credits
    if cap > 0:
        projected = month_credits_used(session) + est_credits(clip_job.est_minutes)
        if projected > cap:
            clip_job.status = "blocked"
            clip_job.error = f"monthly_cap_reached: projected {projected} credits > cap {cap}"
            session.commit()
            log.warning("clip_job_blocked_over_cap", clip_job_id=clip_job.id,
                        projected=projected, cap=cap)
            return
```

Immediately after the `for p in produced:` loop's `session.commit()` (the one that writes the Clip rows), persist the raw credits onto the job (do it alongside the existing `clip_job.status = "produced"` block near the end):

```python
    clip_job.credits_used = produced[0].credits_used if produced else None
    clip_job.status = "produced"
    clip_job.error = None
    session.commit()
```

(The `blocked` early-return happens inside `_run_clipping_inner`, i.e. still within `run_clipping`'s never-raise guard — a bug in the gate can never crash the scheduler.)

- [ ] **Step 6: Note `blocked` exclusion in `clipfactory.py`**

`_ADVANCEABLE_STATUSES = ("queued", "acquired", "produced")` already excludes `blocked`, so a blocked job is never re-picked. Add a one-line comment on that tuple in `src/clipscore/jobs/clipfactory.py` documenting that `blocked` (B5 cap) is intentionally excluded and re-queued manually.

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_clip_cost_gate.py tests/test_clip_produce.py tests/test_clip_vizard.py -v`
Expected: PASS (cost-gate tests green; existing produce/vizard tests still green — `credits_used` is an additive optional field).

- [ ] **Step 8: Commit**

```bash
git add src/clipscore/factory/clip/base.py src/clipscore/factory/clip/vizard.py src/clipscore/factory/clip/produce.py src/clipscore/jobs/clipfactory.py tests/test_clip_cost_gate.py
git commit -m "feat(b5): monthly-credit cap gate + blocked status + persist creditsUsed"
```

---

## Task 4: Operator-entered source minutes

**Files:**
- Modify: `src/clipscore/jobs/clipfactory.py` (`create_clip_job` gains `est_minutes`)
- Modify: `src/clipscore/web/actions.py` (`create_manual_campaign` gains `est_minutes`)
- Modify: `src/clipscore/web/app.py` (`/manual` POST reads `source_minutes`)
- Modify: `src/clipscore/web/templates/manual.html` (add the field)
- Modify: `src/clipscore/cli.py` (`clip --source-minutes`)
- Test: `tests/test_clip_est_minutes.py`

**Interfaces:**
- `create_clip_job(session, campaign_id, settings, *, source_type=None, source_ref=None, est_minutes=None, now=None)` — persists `est_minutes` onto the `ClipJob`.
- `create_manual_campaign(session, *, title, niche, content_bank_url, target_creator, settings, est_minutes=None, now=None)` — threads `est_minutes` into `create_clip_job`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clip_est_minutes.py
from clipscore.config import Settings
from clipscore.db.models import Campaign, ClipJob
from clipscore.jobs.clipfactory import create_clip_job


def test_create_clip_job_persists_est_minutes(session):
    session.add(Campaign(id="c1", source="manual", external_id="c1", campaign_type="clipping",
                         status="active", access_status="ingestable", content_bank_url="https://youtu.be/abc",
                         first_seen_at="2026-07-01T00:00:00Z", last_seen_at="2026-07-01T00:00:00Z"))
    session.commit()
    job = create_clip_job(session, "c1", Settings(_env_file=None), est_minutes=14)
    assert job.est_minutes == 14
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_clip_est_minutes.py -v`
Expected: FAIL — `create_clip_job() got an unexpected keyword argument 'est_minutes'`.

- [ ] **Step 3: Thread `est_minutes` through `create_clip_job`**

In `src/clipscore/jobs/clipfactory.py`, add the param to the signature and the `ClipJob(...)` construction:

```python
def create_clip_job(
    session: Session, campaign_id: str, settings: Settings, *,
    source_type: str | None = None, source_ref: str | None = None,
    est_minutes: int | None = None, now: str | None = None,
) -> ClipJob:
```

```python
    job = ClipJob(
        campaign_id=campaign_id,
        source_type=source_type,
        source_ref=source_ref,
        status="queued",
        est_cost_usd=settings.clip_est_cost_usd,
        est_minutes=est_minutes,
        created_at=now or utcnow_iso(),
    )
```

- [ ] **Step 4: Thread `est_minutes` through `create_manual_campaign`**

In `src/clipscore/web/actions.py`, add `est_minutes: int | None = None` to `create_manual_campaign`'s signature and pass it: `job = create_clip_job(session, cid, settings, est_minutes=est_minutes)`.

- [ ] **Step 5: Add the `/manual` form field + POST handler wiring**

In `src/clipscore/web/templates/manual.html`, add before the submit button:

```html
  <p><label>Source length (minutes) <input name="source_minutes" type="number" min="1"></label></p>
```

In `src/clipscore/web/app.py`, `manual_submit`: add the form param and parse (empty string → `None`, never a 422):

```python
    @app.post("/manual", response_class=HTMLResponse)
    def manual_submit(request: Request, db: Session = Depends(get_db),
                      title: str = Form(...), niche: str = Form(""),
                      content_bank_url: str = Form(""), target_creator: str = Form(""),
                      source_minutes: str = Form("")):
        est_minutes = int(source_minutes) if source_minutes.strip() else None
        result = actions.create_manual_campaign(
            db, title=title, niche=niche or None,
            content_bank_url=content_bank_url or None,
            target_creator=target_creator or None, est_minutes=est_minutes, settings=settings,
        )
        return templates.TemplateResponse(request, "manual.html", {"result": result})
```

(Note: this handler is also updated for the TemplateResponse arg order — see Task 8; if Task 8 runs first, keep the new order.)

- [ ] **Step 6: Add the CLI flag**

In `src/clipscore/cli.py`, `_clip`: pass `est_minutes=args.source_minutes` into `create_clip_job`; in `build_parser`, add to the `clip` subparser:

```python
    cp.add_argument("--source-minutes", dest="source_minutes", type=int, default=None,
                    help="source video length in minutes (feeds the monthly credit cap)")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_clip_est_minutes.py tests/test_web_e2e.py -v`
Expected: PASS (new test green; the web e2e still green with the extra optional form field).

- [ ] **Step 8: Commit**

```bash
git add src/clipscore/jobs/clipfactory.py src/clipscore/web/actions.py src/clipscore/web/app.py src/clipscore/web/templates/manual.html src/clipscore/cli.py tests/test_clip_est_minutes.py
git commit -m "feat(b5): operator-entered source minutes (/manual field + clip --source-minutes)"
```

---

## Task 5: Retention — delete-on-post + age sweep + `clipscore prune`

**Files:**
- Create: `src/clipscore/factory/clip/retention.py`
- Modify: `src/clipscore/config.py` (`clip_retention_days`)
- Modify: `src/clipscore/web/actions.py` (`mark_posted` deletes the clip file)
- Modify: `src/clipscore/jobs/poll.py` (guarded retention job)
- Modify: `src/clipscore/cli.py` (`clipscore prune`)
- Test: `tests/test_clip_retention.py`

**Interfaces:**
- Produces: `Settings.clip_retention_days: int` (default `14`).
- Produces: `delete_clip_file(clip) -> bool` — guarded `os.remove`; sets `clip.storage_uri = None`; returns whether a file was removed. Never raises on a missing file.
- Produces: `sweep_clip_retention(session, settings, now=None) -> dict` — deletes files of clips older than `clip_retention_days` (by `Clip.created_at`), returns `{"pruned": n}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clip_retention.py
from datetime import datetime, timezone

from clipscore.config import Settings
from clipscore.db.models import Clip
from clipscore.factory.clip.retention import delete_clip_file, sweep_clip_retention


def _clip(session, path, created_at):
    c = Clip(source_asset_id=1, storage_uri=str(path), status="ready", created_at=created_at)
    session.add(c)
    session.commit()
    return c


def test_delete_clip_file_removes_and_nulls(session, tmp_path):
    f = tmp_path / "clip-0.mp4"
    f.write_bytes(b"x")
    c = _clip(session, f, "2026-07-15T00:00:00Z")
    assert delete_clip_file(c) is True
    assert not f.exists() and c.storage_uri is None


def test_delete_clip_file_missing_is_safe(session, tmp_path):
    c = _clip(session, tmp_path / "gone.mp4", "2026-07-15T00:00:00Z")
    assert delete_clip_file(c) is False  # no crash on a missing file


def test_sweep_prunes_only_aged_clips(session, tmp_path):
    old = tmp_path / "old.mp4"; old.write_bytes(b"x")
    new = tmp_path / "new.mp4"; new.write_bytes(b"x")
    _clip(session, old, "2026-06-01T00:00:00Z")   # >14d before now
    _clip(session, new, "2026-07-14T00:00:00Z")   # within 14d
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    result = sweep_clip_retention(session, Settings(_env_file=None, clip_retention_days=14), now=now)
    assert result == {"pruned": 1}
    assert not old.exists() and new.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_clip_retention.py -v`
Expected: FAIL — `ModuleNotFoundError: clipscore.factory.clip.retention`.

- [ ] **Step 3: Add the config field**

In `src/clipscore/config.py`, after `raw_retention_days`:

```python
    clip_retention_days: int = 14  # age sweep for produced clip files (clips-only; passthrough keeps no source)
```

- [ ] **Step 4: Implement retention**

```python
# src/clipscore/factory/clip/retention.py
"""Clip-file retention for B5. Clips-only (passthrough keeps no source file).
`delete_clip_file` is the guarded single-file delete reused by mark-posted;
`sweep_clip_retention` prunes clip files older than `clip_retention_days`.
Both tolerate an already-missing file (never raise)."""
import os
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from clipscore.config import Settings
from clipscore.db.models import Clip

log = structlog.get_logger()


def delete_clip_file(clip: Clip) -> bool:
    """Remove a clip's on-disk file if present, and null its storage_uri.
    Returns True iff a file was actually removed. Never raises."""
    uri = clip.storage_uri
    removed = False
    if uri and os.path.isfile(uri):
        try:
            os.remove(uri)
            removed = True
        except OSError:
            log.warning("clip_file_delete_failed", clip_id=clip.id, storage_uri=uri)
    clip.storage_uri = None
    return removed


def _cutoff_iso(days: int, now: datetime | None) -> str:
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def sweep_clip_retention(session, settings: Settings, now=None) -> dict:
    """Delete files of clips older than `clip_retention_days` (by created_at)."""
    cutoff = _cutoff_iso(settings.clip_retention_days, now)
    clips = session.execute(
        select(Clip).where(Clip.created_at < cutoff, Clip.storage_uri.is_not(None))
    ).scalars().all()
    pruned = 0
    for c in clips:
        if delete_clip_file(c):
            pruned += 1
    session.commit()
    return {"pruned": pruned}
```

- [ ] **Step 5: Delete the clip file on mark-posted**

In `src/clipscore/web/actions.py`, `mark_posted`, after the outcome upsert and before the final `session.commit()`, delete the posted clip's file:

```python
    from clipscore.factory.clip.retention import delete_clip_file
    clip = session.get(Clip, match.clip_id)
    if clip is not None:
        delete_clip_file(clip)
    session.commit()
    return ClipResult(ok=True, status="posted")
```

(`Clip` is already imported in `actions.py` via `from clipscore.db.models import Campaign, ClipMatch, Outcome` — add `Clip` to that import.)

- [ ] **Step 6: Wire a guarded retention job into the scheduler**

In `src/clipscore/jobs/poll.py`, `build_scheduler`, add after the `clip_factory` job:

```python
    def retention_job():
        with session_factory() as s:
            try:
                from clipscore.factory.clip.retention import sweep_clip_retention
                result = sweep_clip_retention(s, get_settings())
                log.info("clip_retention", **result)
            except Exception:
                log.error("clip_retention_tick_failed", exc_info=True)
    sched.add_job(retention_job, "interval", minutes=minutes, id="clip_retention")
```

- [ ] **Step 7: Add the `clipscore prune` command**

In `src/clipscore/cli.py`: add `_prune` and register it.

```python
def _prune(args) -> None:
    get_engine()
    from clipscore.factory.clip.retention import sweep_clip_retention
    with SessionLocal() as s:
        print(sweep_clip_retention(s, get_settings()))
```

```python
    sub.add_parser("prune", help="delete clip files older than CLIPSCORE_CLIP_RETENTION_DAYS").set_defaults(fn=_prune)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_clip_retention.py tests/test_web_actions.py -v`
Expected: PASS (retention tests green; mark-posted still green — it now also nulls the posted clip's file).

- [ ] **Step 9: Commit**

```bash
git add src/clipscore/factory/clip/retention.py src/clipscore/config.py src/clipscore/web/actions.py src/clipscore/jobs/poll.py src/clipscore/cli.py tests/test_clip_retention.py
git commit -m "feat(b5): clip retention — delete-on-post + age sweep + clipscore prune"
```

---

## Task 6: `clipscore process` — on-demand job drain

**Files:**
- Create: `src/clipscore/jobs/drain.py`
- Modify: `src/clipscore/cli.py` (`process` subcommand)
- Test: `tests/test_jobs_drain.py`

**Interfaces:**
- Produces: `drain_clip_jobs(session, settings, *, once=False, engine=None, registry=None, llm=None, now=None) -> dict` — repeatedly calls `process_clip_jobs` until a pass reports `advanced == 0` (all in-flight jobs reached a terminal/`blocked` status); `once=True` runs a single pass. Returns `{"passes": p, "advanced": total_advanced, "failed": total_failed}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_jobs_drain.py
from clipscore.config import Settings
from clipscore.db.models import Campaign, ClipJob, SourceAsset
from clipscore.factory.acquire.registry import build_registry
from clipscore.factory.clip.base import FakeClipEngine
from clipscore.jobs.drain import drain_clip_jobs


def test_drain_drives_queued_job_to_terminal(session):
    session.add(Campaign(id="c1", source="manual", external_id="c1", campaign_type="clipping",
                         status="active", access_status="ingestable", target_creator="@x",
                         first_seen_at="2026-07-01T00:00:00Z", last_seen_at="2026-07-01T00:00:00Z"))
    session.add(ClipJob(campaign_id="c1", source_type="passthrough",
                        source_ref="https://youtu.be/abc", status="queued",
                        created_at="2026-07-15T00:00:00Z"))
    session.commit()
    result = drain_clip_jobs(session, Settings(_env_file=None, clip_engine="fake"),
                             engine=FakeClipEngine(), registry=build_registry())
    assert result["passes"] >= 3           # queued->acquired->produced->matched
    job = session.query(ClipJob).one()
    assert job.status in ("matched", "failed", "blocked")
    assert job.status == "matched"


def test_drain_once_single_pass(session):
    session.add(ClipJob(campaign_id="c1", source_type="passthrough",
                        source_ref="https://youtu.be/abc", status="queued",
                        created_at="2026-07-15T00:00:00Z"))
    session.commit()
    result = drain_clip_jobs(session, Settings(_env_file=None, clip_engine="fake"),
                             engine=FakeClipEngine(), registry=build_registry(), once=True)
    assert result["passes"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_jobs_drain.py -v`
Expected: FAIL — `ModuleNotFoundError: clipscore.jobs.drain`.

- [ ] **Step 3: Implement the drain loop**

```python
# src/clipscore/jobs/drain.py
"""On-demand clip-job drain (`clipscore process`). `process_clip_jobs`
advances each in-flight job by one stage; draining loops it until a pass
advances nothing (every job reached matched/failed/blocked). This is the
operator's manual alternative to waiting for the bot scheduler's interval
tick -- `clipscore web`/`clip` only ENQUEUE jobs."""
import structlog

from clipscore.config import Settings
from clipscore.jobs.clipfactory import process_clip_jobs

log = structlog.get_logger()


def drain_clip_jobs(session, settings: Settings, *, once: bool = False,
                    engine=None, registry=None, llm=None, now=None) -> dict:
    passes = 0
    total_advanced = 0
    total_failed = 0
    while True:
        result = process_clip_jobs(session, settings, registry=registry,
                                   engine=engine, llm=llm, now=now)
        passes += 1
        total_advanced += result["advanced"]
        total_failed += result["failed"]
        if once or result["advanced"] == 0:
            break
    log.info("clip_drain", passes=passes, advanced=total_advanced, failed=total_failed)
    return {"passes": passes, "advanced": total_advanced, "failed": total_failed}
```

- [ ] **Step 4: Add the `process` CLI command**

In `src/clipscore/cli.py`:

```python
def _process(args) -> None:
    get_engine()
    from clipscore.jobs.drain import drain_clip_jobs
    with SessionLocal() as s:
        print(drain_clip_jobs(s, get_settings(), once=args.once))
```

```python
    pp = sub.add_parser("process", help="run in-flight clip jobs to completion (drain)")
    pp.add_argument("--once", action="store_true", help="single pass instead of draining to terminal")
    pp.set_defaults(fn=_process)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_jobs_drain.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/clipscore/jobs/drain.py src/clipscore/cli.py tests/test_jobs_drain.py
git commit -m "feat(b5): clipscore process — on-demand job drain"
```

---

## Task 7: Vizard virality params

**Files:**
- Modify: `src/clipscore/config.py` (virality toggles)
- Modify: `src/clipscore/factory/clip/base.py` (`ClipSpec.keyword`; `derive_specs` sets it)
- Modify: `src/clipscore/factory/clip/vizard.py` (`_submit` sends the params)
- Test: `tests/test_clip_vizard.py` (extend)

**Interfaces:**
- Produces: `Settings` toggles — `vizard_ratio_of_clip: int = 1`, `vizard_subtitle: bool = True`, `vizard_highlight: bool = True`, `vizard_headline: bool = True`, `vizard_emoji: bool = True`, `vizard_broll: bool = True`, `vizard_remove_silence: bool = True`.
- Produces: `ClipSpec.keyword: str | None`; `derive_specs` sets `keyword = (campaign.niche or "").strip() or None`.
- `_submit` adds to its payload: `ratioOfClip`, `subtitleSwitch`, `highlightSwitch`, `headlineSwitch`, `emojiSwitch`, `autoBrollSwitch`, `removeSilenceSwitch` (bools mapped to `1`/`0`), and `keyword` only when non-empty.

- [ ] **Step 1: Write the failing test (extend `test_clip_vizard.py`)**

```python
def test_produce_sends_virality_params(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/project/create"):
            body = json.loads(request.content)
            seen.update(body)
            return httpx.Response(200, json={"code": 2000, "projectId": 7})
        if "/project/query/" in request.url.path:
            return httpx.Response(200, json={"code": 2000, "creditsUsed": 3,
                                             "videos": [{"videoUrl": "https://cdn/v0.mp4",
                                                         "videoMsDuration": 30000, "videoId": "v0"}]})
        return httpx.Response(200, content=b"MP4")

    eng = _engine(handler, tmp_path)
    spec = ClipSpec(min_len_s=0, max_len_s=0, keyword="fitness")
    eng.produce("https://youtu.be/abc", spec, dest_dir=str(tmp_path))
    assert seen["ratioOfClip"] == 1
    assert seen["subtitleSwitch"] == 1 and seen["headlineSwitch"] == 1
    assert seen["removeSilenceSwitch"] == 1
    assert seen["keyword"] == "fitness"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_clip_vizard.py::test_produce_sends_virality_params -v`
Expected: FAIL — `KeyError: 'ratioOfClip'` (and `ClipSpec` rejects `keyword` if base.py isn't updated yet).

- [ ] **Step 3: Add the config toggles**

In `src/clipscore/config.py`, after `monthly_cap_credits`:

```python
    vizard_ratio_of_clip: int = 1   # 1=9:16, 2=1:1, 3=4:5, 4=16:9
    vizard_subtitle: bool = True
    vizard_highlight: bool = True
    vizard_headline: bool = True
    vizard_emoji: bool = True
    vizard_broll: bool = True
    vizard_remove_silence: bool = True
```

- [ ] **Step 4: Add `keyword` to `ClipSpec` + `derive_specs`**

In `src/clipscore/factory/clip/base.py`:

```python
class ClipSpec(BaseModel):
    min_len_s: int
    max_len_s: int
    keyword: str | None = None
```

In `derive_specs`, set the keyword from the campaign niche on both return paths:

```python
def derive_specs(campaign, settings: Settings) -> ClipSpec:
    kw = (getattr(campaign, "niche", None) or "").strip() or None
    lo = getattr(campaign, "clip_min_len_s", None)
    hi = getattr(campaign, "clip_max_len_s", None)
    if lo is not None and hi is not None:
        return ClipSpec(min_len_s=lo, max_len_s=hi, keyword=kw)
    return ClipSpec(min_len_s=0, max_len_s=0, keyword=kw)
```

- [ ] **Step 5: Send the params from `_submit`**

In `src/clipscore/factory/clip/vizard.py`, change `produce` to pass `spec` into `_submit`, and build the extended payload. Update `_submit`'s signature to `_submit(self, client, source_uri, video_type, ext, spec)` and the `produce` call site to `self._submit(client, source_uri, video_type, ext, spec)`. Then:

```python
    def _submit(self, client, source_uri, video_type, ext, spec):
        s = self.settings
        payload = {"videoUrl": source_uri, "videoType": video_type,
                   "lang": "en", "preferLength": [0],
                   "ratioOfClip": s.vizard_ratio_of_clip,
                   "subtitleSwitch": int(s.vizard_subtitle),
                   "highlightSwitch": int(s.vizard_highlight),
                   "headlineSwitch": int(s.vizard_headline),
                   "emojiSwitch": int(s.vizard_emoji),
                   "autoBrollSwitch": int(s.vizard_broll),
                   "removeSilenceSwitch": int(s.vizard_remove_silence)}
        if video_type == 1:
            payload["ext"] = ext or "mp4"
        if spec.keyword:
            payload["keyword"] = spec.keyword
        resp = client.post("/project/create", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 2000 or "projectId" not in data:
            raise RuntimeError(f"Vizard create rejected: {data}")
        return data["projectId"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_clip_vizard.py tests/test_clip_base.py -v`
Expected: PASS (new virality test green; existing vizard tests still green — the earlier `test_produce_submits_videotype_polls_and_downloads` only asserts `videoType`/`videoUrl`/`preferLength`, which are unchanged).

- [ ] **Step 7: Commit**

```bash
git add src/clipscore/config.py src/clipscore/factory/clip/base.py src/clipscore/factory/clip/vizard.py tests/test_clip_vizard.py
git commit -m "feat(b5): Vizard virality params (ratio/subtitle/highlight/headline/emoji/broll/silence + keyword)"
```

---

## Task 8: Minor fixes bundle

**Files:**
- Modify: `src/clipscore/factory/enrich.py` (rollback-FIRST in the hard-fallback)
- Modify: `src/clipscore/jobs/clipfactory.py` (per-tick job cap)
- Modify: `src/clipscore/config.py` (`clip_jobs_per_tick`)
- Modify: `src/clipscore/web/app.py` (TemplateResponse arg order — all handlers)
- Modify: `src/clipscore/factory/clip/produce.py` (`media//` path join)
- Test: `tests/test_b5_minors.py`

**Interfaces:**
- Produces: `Settings.clip_jobs_per_tick: int = 5` — max jobs advanced per `process_clip_jobs` call.
- The `dest_dir` in `_run_clipping_inner` uses `os.path.join` (no `//`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_b5_minors.py
import os

from clipscore.config import Settings
from clipscore.db.models import Campaign, ClipJob, SourceAsset
from clipscore.factory.acquire.registry import build_registry
from clipscore.jobs.clipfactory import process_clip_jobs


def _queued(session, n):
    session.add(Campaign(id="c1", source="manual", external_id="c1", campaign_type="clipping",
                         status="active", access_status="ingestable", target_creator="@x",
                         first_seen_at="2026-07-01T00:00:00Z", last_seen_at="2026-07-01T00:00:00Z"))
    for _ in range(n):
        session.add(ClipJob(campaign_id="c1", source_type="passthrough",
                            source_ref="https://youtu.be/abc", status="queued",
                            created_at="2026-07-15T00:00:00Z"))
    session.commit()


def test_per_tick_job_cap(session):
    _queued(session, 8)
    result = process_clip_jobs(session, Settings(_env_file=None, clip_jobs_per_tick=3),
                               registry=build_registry())
    assert result["advanced"] == 3   # capped, not 8


def test_media_dir_path_has_no_double_slash():
    # media_dir default ends in "/"; the join must not produce "media//clips"
    got = os.path.join("media/", "clips", "1")
    assert "//" not in got and got.endswith(os.path.join("clips", "1"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_b5_minors.py::test_per_tick_job_cap -v`
Expected: FAIL — `assert 8 == 3` (no cap applied yet).

- [ ] **Step 3: Per-tick job cap**

In `src/clipscore/config.py`, after `clip_retention_days`:

```python
    clip_jobs_per_tick: int = 5  # max clip jobs advanced per process_clip_jobs pass
```

In `src/clipscore/jobs/clipfactory.py`, `process_clip_jobs`, cap the selected jobs:

```python
    jobs = session.execute(
        select(ClipJob).where(ClipJob.status.in_(_ADVANCEABLE_STATUSES))
        .limit(settings.clip_jobs_per_tick)
    ).scalars().all()
```

- [ ] **Step 4: `media//` double-slash fix**

In `src/clipscore/factory/clip/produce.py`, `_run_clipping_inner`, replace the f-string dest_dir with `os.path.join` (os is already imported):

```python
    dest_dir = os.path.join(settings.media_dir, "clips", str(clip_job.id))
```

- [ ] **Step 5: `enrich_campaign` rollback-FIRST alignment**

In `src/clipscore/factory/enrich.py`, `enrich_campaign`'s `except` branch, roll back BEFORE the regex-floor fallback touches the session (mirrors `run_clipping`'s guard — a failed commit inside the inner leaves the transaction deactivated):

```python
    try:
        return _enrich_campaign_inner(session, campaign, settings, extractor, fetch)
    except Exception:
        log.error("enrich_campaign_failed_hard", campaign_id=getattr(campaign, "id", None))
        try:
            session.rollback()
            regex_result = _regex_floor(campaign, None)
            apply_to_campaign(campaign, regex_result)
            session.commit()
            return regex_result
        except Exception:
            log.error("enrich_campaign_regex_floor_also_failed",
                      campaign_id=getattr(campaign, "id", None))
            return ExtractedTargets()
```

- [ ] **Step 6: TemplateResponse arg order (Starlette deprecation)**

In `src/clipscore/web/app.py`, change every `templates.TemplateResponse("name.html", {"request": request, ...})` to the current signature `templates.TemplateResponse(request, "name.html", {...})` — drop `"request": request` from each context dict since `request` is now the first positional arg. There are 6 call sites: `approval`, `clip`, `review_list`, `review`, `manual_form`, `manual_submit`. Example:

```python
    @app.get("/", response_class=HTMLResponse)
    def approval(request: Request, db: Session = Depends(get_db)):
        return templates.TemplateResponse(request, "approval.html", {
            "rows": queries.approval_rows(db, settings),
            "monthly_cost": queries.monthly_cost_usd(db),
        })
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_b5_minors.py tests/test_web_e2e.py tests/test_enrich.py -v`
Expected: PASS (per-tick cap + path tests green; web e2e green with the new TemplateResponse order; enrich tests green).

- [ ] **Step 8: Run the full suite**

Run: `pytest -q`
Expected: all green (349 pre-B5 + the new B5 tests), 0 failed.

- [ ] **Step 9: Commit**

```bash
git add src/clipscore/factory/enrich.py src/clipscore/jobs/clipfactory.py src/clipscore/config.py src/clipscore/web/app.py src/clipscore/factory/clip/produce.py tests/test_b5_minors.py
git commit -m "fix(b5): per-tick job cap, media// path join, enrich rollback-first, TemplateResponse arg order"
```

---

## Notes for the implementer

- **`Settings(_env_file=None, ...)`** is the established test idiom (see `tests/test_clip_vizard.py`) — it ignores any real `.env` so tests are hermetic. Use it in every test that constructs `Settings`.
- **Do not** call the real Vizard API or network anywhere in tests. The virality assertions go through the existing `MockTransport` seam.
- **The cap gate is the one cross-cutting change**: it lives inside `_run_clipping_inner`, so it is already covered by `run_clipping`'s never-raise guard. Do not add a second guard.
- **Task order matters** where files overlap: Task 4 and Task 8 both edit `web/app.py`'s `manual_submit` (form field vs. TemplateResponse order) and `produce.py`. If you implement out of order, keep BOTH changes — they don't conflict semantically.
- After all tasks: hand off to `superpowers:finishing-a-development-branch` (the user merges to `main` locally and pushes themselves — never push for them; never delete the merged stage branch).
