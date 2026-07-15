# Pipeline B — Stage 4 (B4): Review Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give the operator a local, single-user **review dashboard** — a FastAPI app that surfaces Pipeline A's top clippable campaigns for approval ("Clip this" → enqueue a clip job), presents finished clips for review (inline video, ranked campaign matches, requirements, suggested caption, download), lets the operator **mark a clip posted** (writing the `outcomes` row that closes the A↔B learning loop), accepts **manual campaign entry**, and shows a **monthly cost readout** plus **advisory duplicate-deliverable warnings**.

**Architecture:** Server-rendered **FastAPI + Jinja2**, progressively enhanced with a single vendored `htmx.min.js` (no CDN, no build step). Every action is a real `<form method="post">` that works with JS disabled (full-page reload) and is enhanced by `hx-*` attributes for an in-place swap — so HTMX is pure enhancement and its absence never breaks a route or a test. The app is split into **pure, CI-testable cores** (`web/queries.py` reads, `web/warnings.py` dup-warnings) and a thin **guarded write layer** (`web/actions.py`) that reuses the existing `create_clip_job` and B3 runner rather than rebuilding them. Routes are thin adapters over those cores. **Localhost-only, no auth** (single local user). One short-lived DB session per request.

**Tech Stack:** Python 3.11+, FastAPI + Starlette, Jinja2, uvicorn (run only), `python-multipart` (form parsing), SQLAlchemy 2.x, pydantic, structlog, pytest. CI uses Starlette's `TestClient` — **no running server, no network, no real video**.

## Context

This is **Phase B4** of `PIPELINE_B_CLIP_FACTORY.md` (source of truth — see its **Phase B4** entry). Pipeline A Stages 1–4 and Pipeline B Stages 1–3 are merged. B4 reads/writes tables that already exist (`campaigns`, `campaign_scores`, `clip_jobs`, `source_assets`, `clips`, `clip_matches`, `outcomes`) and adds **one additive column** via migration `0006`.

**Design decisions this plan encodes** (approved 2026-07-15):
- **Jinja2 + HTMX server-rendered**, vendored `htmx.min.js`, no CDN/build step — smallest footprint that still feels like an app.
- **Duplicate-deliverable = both checks** (source-asset reused across a different campaign; this campaign already has an outcome), and it is **advisory** (displays; never blocks a post — a hard cap/pause is B5).
- **`outcomes.clip_id` (nullable)** is added: the footage-reuse warning must join `outcome → clip → source_asset_id → sibling clips' outcomes`, which is only computable with `clip_id` on the outcome. Nothing writes `Outcome` today, so this is safe; Pipeline A's future campaign-level writes leave it NULL.
- **"Clip this" only enqueues** a `queued` clip job (reuses `create_clip_job`). The web layer never produces clips — the scheduler's B3 `process_clip_jobs` does. The e2e acceptance test invokes that runner explicitly to reach `ready`.
- **mark-posted is idempotent** — an upsert on `(clip_id, campaign_id)`, never an append.
- **Localhost-only, no auth; read-only cost panel** (no cap/pause — that's B5).

## Existing code this builds on

- `src/clipscore/db/models.py` — `Outcome` (`campaign_id`, `clips_posted`, `clips_approved`, `actual_views`, `actual_payout_usd`, `payout_days`, `logged_at`) — **B4 adds `clip_id`**. `Campaign`, `CampaignScore`, `ClipJob` (`campaign_id`, `source_type`, `source_ref`, `status`, `est_cost_usd`, `error`, `created_at`), `Clip` (`source_asset_id`, `platform_variant`, `storage_uri`, `duration_s`, `transcript`, `cost_usd`, `status`, `created_at`), `ClipMatch` (`clip_id`, `campaign_id`, `match_score`, `meets_requirements`, `suggested_caption`, `rank`), `SourceAsset` (`clip_job_id`, `storage_uri`, …).
- `src/clipscore/scoring/board.py` — `eligible_latest_scores(session) -> list[tuple[Campaign, CampaignScore]]` (latest score per campaign; already excludes non-active / non-ingestable / `ugc`). **Reuse for the approval list**, then filter to `campaign_type in ("clipping","both")`.
- `src/clipscore/jobs/clipfactory.py` — `create_clip_job(session, campaign_id, settings, *, source_type=None, source_ref=None, now=None) -> ClipJob` (resolves source from `content_bank_url` → first `target_creator` → **raises `ValueError`**; writes a `queued` job with `est_cost_usd`). `process_clip_jobs(session, settings, *, engine=None, now=None)` (the B3 runner — used only by the e2e test here). **Reuse `create_clip_job` for both "Clip this" and manual entry.**
- `src/clipscore/factory/clip/produce.py` — clips are written under `f"{settings.media_dir}/clips/{clip_job.id}/…"`; `Clip.storage_uri` is that full path. **Media serving resolves the path from the DB, never from the client.**
- `src/clipscore/config.py` — `Settings` (prefix `CLIPSCORE_`, `.env`): has `media_dir="media/"`, `clip_est_cost_usd=0.0`, `summary_hour_et=9`. **Add nothing** unless a task says so.
- `src/clipscore/time.py` — `utcnow_iso()` → `"%Y-%m-%dT%H:%M:%SZ"` (UTC, lexicographically sortable). **B4 adds `et_month_bounds_utc`.**
- `src/clipscore/bot/discord_bot.py` — uses `zoneinfo.ZoneInfo("America/New_York")` for ET. **Mirror that zone for the monthly cost boundary.**
- `src/clipscore/cli.py` — argparse subcommands via `sub.add_parser(...).set_defaults(fn=…)`; `main(argv=None)`. **Add the `web` subcommand.**
- `tests/conftest.py` — `session` fixture: fresh in-memory SQLite engine per test, all ORM tables, yields a `Session`.
- `pyproject.toml` — `dependencies`, `[project.optional-dependencies]`, `[project.scripts] clipscore`.

## Global Constraints

Every task's requirements implicitly include these.

- **No new deps beyond four web libs.** Add exactly `fastapi`, `uvicorn`, `jinja2`, `python-multipart` to `dependencies`. No frontend toolchain, no ORM/templating alternative, no CDN.
- **CI purity.** Every test runs against `TestClient` over an in-memory SQLite session — **no real network, no uvicorn process, no real video files** (media tests write a tiny temp file and point a `Clip.storage_uri` at it). HTMX is never exercised by a test (it is client-side); routes are tested as plain form POSTs / GETs.
- **Progressive enhancement.** Every mutating control is a real `<form method="post" action="...">` that works without JavaScript; `hx-*` attributes only add an in-place swap. A route must return correct results whether called by a browser form post or by `TestClient`.
- **Localhost-only, no auth.** `clipscore web` defaults to host `127.0.0.1`. No login, no API keys, no CORS for third-party origins.
- **One short-lived session per request.** Routes depend on a `get_db` dependency that yields a session and closes it after the request. Never hold a transaction open across a request. (SQLite `busy_timeout=5000` — already set in `db/session.py` — covers the web↔scheduler two-writer case.)
- **Reuse, don't rebuild.** Approval ranking via `eligible_latest_scores`; job creation via `create_clip_job`; clip production via the B3 `process_clip_jobs` (e2e test only). Do not re-implement ranking, source resolution, or clip production.
- **Duplicate-deliverable warning is advisory.** It returns display strings; it never prevents a post. No monthly cap / pause / alert (that is B5).
- **mark-posted is idempotent.** Upsert on `(clip_id, campaign_id)`; a repeated post updates the existing row, never inserts a second.
- **Media serving is traversal-safe.** `GET /media/{clip_id}` resolves the file path **only** from `Clip.storage_uri` in the DB; it 404s if the clip is unknown, `storage_uri` is NULL, the file is missing, or the resolved real path is not under `settings.media_dir`. It never accepts a client-supplied path.
- **No schema beyond `0006`.** The only migration is `0006_add_outcome_clip_id` (additive nullable column). Everything else fills existing tables.

---

## Task 1: Web package scaffold — deps, `create_app`, `get_db`, `clipscore web` CLI, health route, base template + vendored HTMX

**Files:**
- Create: `src/clipscore/web/__init__.py`, `src/clipscore/web/app.py`, `src/clipscore/web/templates/base.html`, `src/clipscore/web/static/.gitkeep`
- Modify: `pyproject.toml`, `src/clipscore/cli.py`
- Test: `tests/test_web_app.py`

**Interfaces:**
- Produces `web/app.py`:
  - `def get_db()` — module-level FastAPI dependency: `db = SessionLocal(); try: yield db finally: db.close()`. (Tests override it.)
  - `def create_app(settings: Settings | None = None) -> FastAPI` — builds the app, stores `settings` on `app.state.settings`, mounts `StaticFiles` at `/static` from `web/static`, configures a `Jinja2Templates(directory=web/templates)` on `app.state.templates`, registers routes (only `/healthz` in Task 1; later tasks add more), returns `app`.
  - `GET /healthz` → `{"status": "ok"}`.
- Produces `web/app.py` test seam: tests call `create_app(settings)` then set `app.dependency_overrides[get_db] = lambda: iter_once(test_session)` where the override yields the shared fixture session and does **not** close it.
- Produces CLI: `clipscore web [--host 127.0.0.1] [--port 8000]` runs `uvicorn.run(create_app(get_settings()), host=..., port=...)`.

- [ ] **Step 1: Add deps.** In `pyproject.toml`, append to `dependencies` (after `"discord.py>=2.3,<3.0",`):

```toml
    "fastapi>=0.110,<0.116",
    "uvicorn>=0.29,<0.35",
    "jinja2>=3.1,<4.0",
    "python-multipart>=0.0.9,<0.1",
```

Then reinstall: `python3 -m pip install -e ".[dev]"`.

- [ ] **Step 2: Write the failing test** `tests/test_web_app.py`:

```python
from fastapi.testclient import TestClient
from clipscore.config import Settings
from clipscore.web.app import create_app


def test_healthz_ok(session):
    app = create_app(Settings(db_url="sqlite:///:memory:"))
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_static_mount_exists(session):
    app = create_app(Settings(db_url="sqlite:///:memory:"))
    client = TestClient(app)
    # /static is mounted; a missing asset 404s (mount present, file absent is fine)
    assert client.get("/static/nonexistent.js").status_code == 404
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_web_app.py -v`
Expected: FAIL — `ModuleNotFoundError: clipscore.web`.

- [ ] **Step 4: Write `web/__init__.py`** (empty) and `web/app.py`:

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from clipscore.config import Settings, get_settings
from clipscore.db.session import SessionLocal, get_engine

_HERE = Path(__file__).resolve().parent
_TEMPLATES = _HERE / "templates"
_STATIC = _HERE / "static"


def get_db():
    """One short-lived session per request. Tests override this."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # Bind SessionLocal to the configured engine (idempotent side effect).
    get_engine()
    app = FastAPI(title="clipscore review")
    app.state.settings = settings
    app.state.templates = Jinja2Templates(directory=str(_TEMPLATES))
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
```

- [ ] **Step 5: Write `web/templates/base.html`** (referenced by later tasks) and `web/static/.gitkeep` (empty):

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}clipscore{% endblock %}</title>
  <script src="/static/htmx.min.js" defer></script>
  <style>
    body { font: 15px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 900px; padding: 0 1rem; }
    nav a { margin-right: 1rem; }
    .warn { color: #b45309; background: #fffbeb; padding: .5rem .75rem; border-radius: 6px; }
    table { border-collapse: collapse; width: 100%; }
    th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #eee; }
    .muted { color: #6b7280; }
  </style>
</head>
<body>
  <nav><a href="/">Approve</a><a href="/review">Review</a><a href="/manual">Manual entry</a></nav>
  {% block body %}{% endblock %}
</body>
</html>
```

> **Vendoring HTMX:** `web/static/htmx.min.js` is a browser-only enhancement, never touched by CI. Fetch it once for manual runs: `curl -fsSL -o src/clipscore/web/static/htmx.min.js https://unpkg.com/htmx.org@2.0.3/dist/htmx.min.js`. If the environment has no network, leave the file absent — every control still works as a plain form post (progressive enhancement). Do not add a CDN `<script>` fallback.

- [ ] **Step 6: Add the `web` CLI subcommand.** In `src/clipscore/cli.py`, add a handler near the others:

```python
def _web(args):
    import uvicorn
    from clipscore.config import get_settings
    from clipscore.web.app import create_app
    uvicorn.run(create_app(get_settings()), host=args.host, port=args.port)
```

and register it in `build_parser()` (after the `clip` subparser):

```python
    wp = sub.add_parser("web", help="run the local review dashboard")
    wp.add_argument("--host", default="127.0.0.1")
    wp.add_argument("--port", type=int, default=8000)
    wp.set_defaults(fn=_web)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_web_app.py -v && pytest -q`
Expected: PASS; full suite green (287 + new).

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/clipscore/web/ src/clipscore/cli.py tests/test_web_app.py
git commit -m "feat(b4): web package scaffold — FastAPI create_app, get_db, clipscore web CLI, base template"
```

---

## Task 2: Migration `0006` + `Outcome.clip_id`

**Files:**
- Create: `alembic/versions/0006_add_outcome_clip_id.py`
- Modify: `src/clipscore/db/models.py`
- Test: `tests/test_outcome_clip_id.py`

**Interfaces:**
- Produces `Outcome.clip_id: Mapped[int | None]` (nullable). No other column changes.

- [ ] **Step 1: Write the failing test** `tests/test_outcome_clip_id.py`:

```python
from clipscore.db.models import Outcome


def test_outcome_has_nullable_clip_id(session):
    o = Outcome(campaign_id="c1", clip_id=None, clips_posted=1, logged_at="2026-07-15T00:00:00Z")
    session.add(o)
    session.commit()
    got = session.get(Outcome, o.id)
    assert got.clip_id is None

    o2 = Outcome(campaign_id="c2", clip_id=42, clips_posted=1, logged_at="2026-07-15T00:00:00Z")
    session.add(o2)
    session.commit()
    assert session.get(Outcome, o2.id).clip_id == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_outcome_clip_id.py -v`
Expected: FAIL — `TypeError: 'clip_id' is an invalid keyword argument for Outcome`.

- [ ] **Step 3: Add the column to the model.** In `src/clipscore/db/models.py`, inside `class Outcome`, add after `campaign_id`:

```python
    clip_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 4: Write the migration** `alembic/versions/0006_add_outcome_clip_id.py`:

```python
"""add outcomes.clip_id (nullable) for Pipeline B4 duplicate-deliverable warning

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("outcomes", sa.Column("clip_id", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("outcomes", "clip_id")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_outcome_clip_id.py -v && pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/0006_add_outcome_clip_id.py src/clipscore/db/models.py tests/test_outcome_clip_id.py
git commit -m "feat(b4): migration 0006 — outcomes.clip_id (nullable) for dup-deliverable warning"
```

---

## Task 3: Pure read queries — `web/queries.py`

**Files:**
- Create: `src/clipscore/web/queries.py`
- Modify: `src/clipscore/time.py`
- Test: `tests/test_web_queries.py`

**Interfaces:**
- Produces `time.py`:
  - `et_month_bounds_utc(now: datetime | None = None) -> tuple[str, str]` — returns `(start_z, next_start_z)`: UTC ISO-Z strings for the first instant of the current ET calendar month and of the next ET month. `now` (if given) is treated as an aware UTC datetime for testability.
- Produces `web/queries.py`:
  - `ApprovalRow(BaseModel)` — `campaign_id: str`, `title: str | None`, `niche: str | None`, `campaign_type: str | None`, `cvs_niche_percentile: float | None`, `est_cost_usd: float`, `job_status: str | None` (latest clip_job status for this campaign, or `None`), `clippable: bool` (has a `content_bank_url` or a `target_creator`).
  - `approval_rows(session, settings) -> list[ApprovalRow]` — from `eligible_latest_scores`, keep `campaign_type in ("clipping","both")`, sort by `cvs_niche_percentile` descending (None last), attach est-cost (`settings.clip_est_cost_usd`) and the latest clip_job status.
  - `ReviewClip(BaseModel)` — `clip_id: int`, `platform_variant: str | None`, `duration_s: int | None`, `status: str`, `cost_usd: float | None`, `campaign_id_of_job: str | None`.
  - `ready_clips(session) -> list[ReviewClip]` — clips with `status == "ready"`, newest first (by `id` desc).
  - `MatchRow(BaseModel)` — `match_id: int`, `campaign_id: str`, `campaign_title: str | None`, `match_score: float | None`, `meets_requirements: int | None`, `suggested_caption: str | None`, `rank: int | None`.
  - `ReviewDetail(BaseModel)` — `clip: ReviewClip`, `matches: list[MatchRow]` (rank asc, None last), `requirements: dict` (the campaign requirement fields for the rank-1 match's campaign: `caption_rules`, `banned_content`, `clip_min_len_s`, `clip_max_len_s`, `target_platforms`), `download_url: str` (`/media/{clip_id}`).
  - `review_detail(session, clip_id) -> ReviewDetail | None` — `None` if the clip does not exist.
  - `monthly_cost_usd(session, now=None) -> float` — sum of `Clip.cost_usd` for clips whose `created_at` falls in the current ET calendar month (`created_at` compared lexicographically against `et_month_bounds_utc(now)`), treating NULL cost as 0.

- [ ] **Step 1: Write the failing test** `tests/test_web_queries.py`:

```python
from datetime import datetime, timezone

from clipscore.config import Settings
from clipscore.db.models import Campaign, CampaignScore, ClipJob, Clip, SourceAsset, ClipMatch
from clipscore.time import et_month_bounds_utc
from clipscore.web import queries


def _camp(session, cid, ctype="clipping", pct=0.5, bank="https://drive.google.com/x"):
    session.add(Campaign(
        id=cid, source="s", external_id=cid, campaign_type=ctype, niche="gaming",
        title=f"T {cid}", status="active", access_status="ingestable",
        first_seen_at="2026-01-01T00:00:00Z", last_seen_at="2026-01-01T00:00:00Z",
        content_bank_url=bank,
    ))
    session.add(CampaignScore(campaign_id=cid, scored_at="2026-01-01T00:00:00Z",
                              cvs_niche_percentile=pct))
    session.commit()


def test_approval_rows_filters_and_sorts(session):
    _camp(session, "a", "clipping", pct=0.4)
    _camp(session, "b", "both", pct=0.9)
    _camp(session, "u", "ugc", pct=0.99)          # excluded by eligible_latest_scores
    rows = queries.approval_rows(session, Settings(clip_est_cost_usd=1.25))
    ids = [r.campaign_id for r in rows]
    assert ids == ["b", "a"]                        # ugc dropped, sorted desc by pct
    assert rows[0].est_cost_usd == 1.25
    assert rows[0].clippable is True


def test_approval_row_job_status(session):
    _camp(session, "a")
    session.add(ClipJob(campaign_id="a", source_type="campaign_provided", source_ref="x",
                        status="queued", created_at="2026-01-02T00:00:00Z"))
    session.commit()
    rows = queries.approval_rows(session, Settings())
    assert rows[0].job_status == "queued"


def test_review_detail_and_ready_clips(session):
    _camp(session, "a", pct=0.7)
    sa = SourceAsset(clip_job_id=1, storage_uri="media/x.mp4")
    session.add(sa); session.commit()
    clip = Clip(source_asset_id=sa.id, platform_variant="tiktok", duration_s=60,
                status="ready", cost_usd=0.5, created_at="2026-07-10T00:00:00Z")
    session.add(clip); session.commit()
    session.add(ClipMatch(clip_id=clip.id, campaign_id="a", match_score=0.7,
                          meets_requirements=1, suggested_caption="hi #ad", rank=1))
    session.commit()

    assert [c.clip_id for c in queries.ready_clips(session)] == [clip.id]
    detail = queries.review_detail(session, clip.id)
    assert detail.matches[0].campaign_id == "a"
    assert detail.download_url == f"/media/{clip.id}"
    assert queries.review_detail(session, 9999) is None


def test_monthly_cost_uses_et_month(session):
    sa = SourceAsset(clip_job_id=1, storage_uri="media/x.mp4"); session.add(sa); session.commit()
    now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    start, nxt = et_month_bounds_utc(now)
    # in-month clip counts; a clip stamped before the month start does not
    session.add(Clip(source_asset_id=sa.id, status="ready", cost_usd=2.0,
                     created_at="2026-07-10T00:00:00Z"))
    session.add(Clip(source_asset_id=sa.id, status="ready", cost_usd=5.0,
                     created_at="2026-06-01T00:00:00Z"))
    session.add(Clip(source_asset_id=sa.id, status="ready", cost_usd=None,
                     created_at="2026-07-11T00:00:00Z"))     # NULL cost -> 0
    session.commit()
    assert queries.monthly_cost_usd(session, now=now) == 2.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_queries.py -v`
Expected: FAIL — `ModuleNotFoundError: clipscore.web.queries` (and `ImportError` for `et_month_bounds_utc`).

- [ ] **Step 3: Add `et_month_bounds_utc` to `src/clipscore/time.py`:**

```python
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")


def et_month_bounds_utc(now: datetime | None = None) -> tuple[str, str]:
    """(start, next_start) as UTC ISO-8601 'Z' strings bounding the current
    ET calendar month. `now` is an aware datetime (defaults to real UTC now)."""
    now = now or datetime.now(timezone.utc)
    et = now.astimezone(_ET)
    start_et = et.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start_et.month == 12:
        next_et = start_et.replace(year=start_et.year + 1, month=1)
    else:
        next_et = start_et.replace(month=start_et.month + 1)

    def _z(d: datetime) -> str:
        return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return _z(start_et), _z(next_et)
```

- [ ] **Step 4: Write `web/queries.py`:**

```python
"""Pure, read-only queries backing the B4 dashboard. No writes, no network,
no request objects -- takes a Session, returns pydantic view models, and is
fully unit-testable. Reuses A's ranking (`eligible_latest_scores`)."""
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from clipscore.config import Settings
from clipscore.db.models import Campaign, ClipJob, Clip, ClipMatch
from clipscore.scoring.board import eligible_latest_scores
from clipscore.time import et_month_bounds_utc
from pydantic import BaseModel

_CLIPPING = ("clipping", "both")


class ApprovalRow(BaseModel):
    campaign_id: str
    title: str | None = None
    niche: str | None = None
    campaign_type: str | None = None
    cvs_niche_percentile: float | None = None
    est_cost_usd: float = 0.0
    job_status: str | None = None
    clippable: bool = False


class ReviewClip(BaseModel):
    clip_id: int
    platform_variant: str | None = None
    duration_s: int | None = None
    status: str
    cost_usd: float | None = None
    campaign_id_of_job: str | None = None


class MatchRow(BaseModel):
    match_id: int
    campaign_id: str
    campaign_title: str | None = None
    match_score: float | None = None
    meets_requirements: int | None = None
    suggested_caption: str | None = None
    rank: int | None = None


class ReviewDetail(BaseModel):
    clip: ReviewClip
    matches: list[MatchRow]
    requirements: dict
    download_url: str


def _latest_job_status(session: Session, campaign_id: str) -> str | None:
    jid = session.execute(
        select(func.max(ClipJob.id)).where(ClipJob.campaign_id == campaign_id)
    ).scalar_one_or_none()
    if jid is None:
        return None
    return session.get(ClipJob, jid).status


def approval_rows(session: Session, settings: Settings) -> list[ApprovalRow]:
    rows: list[ApprovalRow] = []
    for camp, score in eligible_latest_scores(session):
        if camp.campaign_type not in _CLIPPING:
            continue
        rows.append(ApprovalRow(
            campaign_id=camp.id, title=camp.title, niche=camp.niche,
            campaign_type=camp.campaign_type,
            cvs_niche_percentile=score.cvs_niche_percentile,
            est_cost_usd=settings.clip_est_cost_usd,
            job_status=_latest_job_status(session, camp.id),
            clippable=bool(camp.content_bank_url or camp.target_creator),
        ))
    rows.sort(key=lambda r: (r.cvs_niche_percentile is None,
                             -(r.cvs_niche_percentile or 0.0)))
    return rows


def _to_review_clip(session: Session, clip: Clip) -> ReviewClip:
    return ReviewClip(
        clip_id=clip.id, platform_variant=clip.platform_variant,
        duration_s=clip.duration_s, status=clip.status, cost_usd=clip.cost_usd,
    )


def ready_clips(session: Session) -> list[ReviewClip]:
    clips = session.execute(
        select(Clip).where(Clip.status == "ready").order_by(Clip.id.desc())
    ).scalars().all()
    return [_to_review_clip(session, c) for c in clips]


def review_detail(session: Session, clip_id: int) -> ReviewDetail | None:
    clip = session.get(Clip, clip_id)
    if clip is None:
        return None
    matches_q = session.execute(
        select(ClipMatch).where(ClipMatch.clip_id == clip_id)
    ).scalars().all()
    rows: list[MatchRow] = []
    for m in matches_q:
        camp = session.get(Campaign, m.campaign_id)
        rows.append(MatchRow(
            match_id=m.id, campaign_id=m.campaign_id,
            campaign_title=camp.title if camp else None,
            match_score=m.match_score, meets_requirements=m.meets_requirements,
            suggested_caption=m.suggested_caption, rank=m.rank,
        ))
    rows.sort(key=lambda r: (r.rank is None, r.rank or 0))

    requirements: dict = {}
    if rows:
        camp = session.get(Campaign, rows[0].campaign_id)
        if camp is not None:
            requirements = {
                "caption_rules": camp.caption_rules,
                "banned_content": camp.banned_content,
                "clip_min_len_s": camp.clip_min_len_s,
                "clip_max_len_s": camp.clip_max_len_s,
                "target_platforms": camp.target_platforms,
            }
    return ReviewDetail(
        clip=_to_review_clip(session, clip), matches=rows,
        requirements=requirements, download_url=f"/media/{clip_id}",
    )


def monthly_cost_usd(session: Session, now=None) -> float:
    start, nxt = et_month_bounds_utc(now)
    clips = session.execute(
        select(Clip.cost_usd).where(
            Clip.created_at >= start, Clip.created_at < nxt
        )
    ).scalars().all()
    return float(sum(c or 0.0 for c in clips))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_web_queries.py -v && pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/clipscore/web/queries.py src/clipscore/time.py tests/test_web_queries.py
git commit -m "feat(b4): pure read queries (approval/review/monthly-cost) + ET month bounds helper"
```

---

## Task 4: Pure duplicate-deliverable warnings — `web/warnings.py`

**Files:**
- Create: `src/clipscore/web/warnings.py`
- Test: `tests/test_web_warnings.py`

**Interfaces:**
- Produces `web/warnings.py`:
  - `duplicate_warnings(session, clip_id: int, campaign_id: str) -> list[str]` — advisory strings; empty when clean. Two independent checks:
    1. **Repeat delivery:** an `Outcome` already exists for `campaign_id` → `"Already delivered to this campaign (outcome logged <logged_at>)."`.
    2. **Footage reuse:** the clip's `source_asset_id` is shared by another `Clip` that has an `Outcome` for a **different** `campaign_id` → `"This source footage was already posted to campaign <other_id>."` (one string per distinct other campaign).
  - Never raises for unknown clip/campaign — an unknown `clip_id` simply skips check 2.

- [ ] **Step 1: Write the failing test** `tests/test_web_warnings.py`:

```python
from clipscore.db.models import Outcome, Clip, SourceAsset
from clipscore.web.warnings import duplicate_warnings


def _clip(session, source_asset_id, cid=None):
    c = Clip(source_asset_id=source_asset_id, status="ready", created_at="2026-07-10T00:00:00Z")
    session.add(c); session.commit()
    return c


def test_no_warnings_when_clean(session):
    sa = SourceAsset(clip_job_id=1); session.add(sa); session.commit()
    c = _clip(session, sa.id)
    assert duplicate_warnings(session, c.id, "camp1") == []


def test_repeat_delivery_warning(session):
    sa = SourceAsset(clip_job_id=1); session.add(sa); session.commit()
    c = _clip(session, sa.id)
    session.add(Outcome(campaign_id="camp1", clip_id=c.id, clips_posted=1,
                        logged_at="2026-07-10T00:00:00Z"))
    session.commit()
    warns = duplicate_warnings(session, c.id, "camp1")
    assert any("Already delivered to this campaign" in w for w in warns)


def test_footage_reuse_warning(session):
    sa = SourceAsset(clip_job_id=1); session.add(sa); session.commit()
    c1 = _clip(session, sa.id)      # posted to campA
    c2 = _clip(session, sa.id)      # same footage, about to post to campB
    session.add(Outcome(campaign_id="campA", clip_id=c1.id, clips_posted=1,
                        logged_at="2026-07-10T00:00:00Z"))
    session.commit()
    warns = duplicate_warnings(session, c2.id, "campB")
    assert any("already posted to campaign campA" in w for w in warns)
    # posting the SAME footage to the SAME campA is repeat-delivery, not reuse
    warns_same = duplicate_warnings(session, c2.id, "campA")
    assert any("Already delivered to this campaign" in w for w in warns_same)
    assert not any("already posted to campaign campA" in w for w in warns_same)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_warnings.py -v`
Expected: FAIL — `ModuleNotFoundError: clipscore.web.warnings`.

- [ ] **Step 3: Write `web/warnings.py`:**

```python
"""Pure, advisory duplicate-deliverable checks for the B4 review surface.
Returns human-readable warning strings; NEVER blocks a post (compliance-first
means we surface the risk and let the operator decide)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from clipscore.db.models import Outcome, Clip


def duplicate_warnings(session: Session, clip_id: int, campaign_id: str) -> list[str]:
    warnings: list[str] = []

    # (1) repeat delivery: this campaign already has an outcome
    existing = session.execute(
        select(Outcome).where(Outcome.campaign_id == campaign_id)
    ).scalars().first()
    if existing is not None:
        warnings.append(
            f"Already delivered to this campaign (outcome logged {existing.logged_at})."
        )

    # (2) footage reuse: another clip from the same source asset was posted to
    #     a DIFFERENT campaign
    clip = session.get(Clip, clip_id)
    if clip is not None and clip.source_asset_id is not None:
        sibling_ids = session.execute(
            select(Clip.id).where(Clip.source_asset_id == clip.source_asset_id)
        ).scalars().all()
        others = session.execute(
            select(Outcome.campaign_id).where(
                Outcome.clip_id.in_(sibling_ids),
                Outcome.campaign_id != campaign_id,
            )
        ).scalars().all()
        for other in dict.fromkeys(others):   # distinct, order-preserving
            warnings.append(f"This source footage was already posted to campaign {other}.")

    return warnings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web_warnings.py -v && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/web/warnings.py tests/test_web_warnings.py
git commit -m "feat(b4): advisory duplicate-deliverable warnings (repeat-delivery + footage-reuse)"
```

---

## Task 5: Guarded write actions — `web/actions.py`

**Files:**
- Create: `src/clipscore/web/actions.py`
- Test: `tests/test_web_actions.py`

**Interfaces:**
- Produces `web/actions.py`:
  - `ClipResult(BaseModel)` — `ok: bool`, `job_id: int | None = None`, `status: str | None = None`, `error: str | None = None`.
  - `clip_this(session, campaign_id, settings) -> ClipResult` — wraps `create_clip_job`; catches `ValueError` → `ClipResult(ok=False, error=str(e))` (e.g. unknown campaign, "no acquirable source"); on success returns `ok=True, job_id, status="queued"`.
  - `mark_posted(session, match_id, *, now=None) -> ClipResult` — look up the `ClipMatch`; **idempotent upsert** of an `Outcome` on `(clip_id, campaign_id)`: if one exists set `clips_posted=1` (leave other actuals), else insert `Outcome(campaign_id, clip_id, clips_posted=1, logged_at=now or utcnow_iso())`. Unknown `match_id` → `ClipResult(ok=False, error="unknown match")`.
  - `create_manual_campaign(session, *, title, niche, content_bank_url, target_creator, settings, now=None) -> ClipResult` — insert a minimal `Campaign` (`id`/`external_id` = a stem of the title + timestamp; `source="manual"`, `campaign_type="clipping"`, `status="active"`, `access_status="ingestable"`, `first_seen_at`/`last_seen_at`=now), set `content_bank_url` / `target_creator` from args, commit, then call `create_clip_job` (catching `ValueError`). On job success returns `ok=True, job_id, status="queued"`; if the campaign saved but no source was acquirable, returns `ok=True, job_id=None, error="campaign created; no acquirable source"` (the campaign still persists).

- [ ] **Step 1: Write the failing test** `tests/test_web_actions.py`:

```python
from clipscore.config import Settings
from clipscore.db.models import Campaign, Clip, SourceAsset, ClipMatch, Outcome
from clipscore.web import actions


def _camp(session, cid, bank="https://drive.google.com/x", creator=None):
    session.add(Campaign(
        id=cid, source="s", external_id=cid, campaign_type="clipping", status="active",
        access_status="ingestable", first_seen_at="2026-01-01T00:00:00Z",
        last_seen_at="2026-01-01T00:00:00Z", content_bank_url=bank, target_creator=creator,
    ))
    session.commit()


def test_clip_this_enqueues(session):
    _camp(session, "a")
    res = actions.clip_this(session, "a", Settings())
    assert res.ok and res.status == "queued" and res.job_id is not None


def test_clip_this_no_source(session):
    _camp(session, "a", bank=None, creator=None)
    res = actions.clip_this(session, "a", Settings())
    assert res.ok is False and "no acquirable source" in res.error


def test_clip_this_unknown_campaign(session):
    res = actions.clip_this(session, "nope", Settings())
    assert res.ok is False and res.error


def test_mark_posted_idempotent(session):
    _camp(session, "a")
    sa = SourceAsset(clip_job_id=1); session.add(sa); session.commit()
    clip = Clip(source_asset_id=sa.id, status="ready", created_at="2026-07-10T00:00:00Z")
    session.add(clip); session.commit()
    m = ClipMatch(clip_id=clip.id, campaign_id="a", rank=1); session.add(m); session.commit()

    r1 = actions.mark_posted(session, m.id, now="2026-07-15T00:00:00Z")
    r2 = actions.mark_posted(session, m.id, now="2026-07-16T00:00:00Z")
    assert r1.ok and r2.ok
    outs = session.query(Outcome).filter_by(clip_id=clip.id, campaign_id="a").all()
    assert len(outs := outs) == 1                       # upsert, not append
    assert outs[0].clips_posted == 1


def test_mark_posted_unknown_match(session):
    assert actions.mark_posted(session, 9999).ok is False


def test_create_manual_campaign(session):
    res = actions.create_manual_campaign(
        session, title="My Manual", niche="gaming",
        content_bank_url="https://drive.google.com/y", target_creator=None,
        settings=Settings(), now="2026-07-15T00:00:00Z",
    )
    assert res.ok and res.job_id is not None
    assert session.query(Campaign).filter_by(source="manual").count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_actions.py -v`
Expected: FAIL — `ModuleNotFoundError: clipscore.web.actions`.

- [ ] **Step 3: Write `web/actions.py`:**

```python
"""Thin, guarded write layer for the B4 dashboard. Reuses create_clip_job for
job creation (both 'Clip this' and manual entry) and performs the idempotent
mark-posted upsert. Returns ClipResult view models; route handlers translate
these into HTMX partials / redirects."""
import re

from pydantic import BaseModel
from sqlalchemy.orm import Session

from clipscore.config import Settings
from clipscore.db.models import Campaign, ClipMatch, Outcome
from clipscore.jobs.clipfactory import create_clip_job
from clipscore.time import utcnow_iso


class ClipResult(BaseModel):
    ok: bool
    job_id: int | None = None
    status: str | None = None
    error: str | None = None


def clip_this(session: Session, campaign_id: str, settings: Settings) -> ClipResult:
    try:
        job = create_clip_job(session, campaign_id, settings)
    except ValueError as e:
        return ClipResult(ok=False, error=str(e))
    return ClipResult(ok=True, job_id=job.id, status=job.status)


def mark_posted(session: Session, match_id: int, *, now: str | None = None) -> ClipResult:
    match = session.get(ClipMatch, match_id)
    if match is None:
        return ClipResult(ok=False, error="unknown match")
    existing = session.query(Outcome).filter_by(
        clip_id=match.clip_id, campaign_id=match.campaign_id
    ).first()
    if existing is not None:
        existing.clips_posted = 1
    else:
        session.add(Outcome(
            campaign_id=match.campaign_id, clip_id=match.clip_id, clips_posted=1,
            logged_at=now or utcnow_iso(),
        ))
    session.commit()
    return ClipResult(ok=True, status="posted")


def _manual_id(title: str, now: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "campaign").lower()).strip("-") or "campaign"
    return f"manual-{slug}-{re.sub(r'[^0-9]', '', now)}"


def create_manual_campaign(session: Session, *, title: str, niche: str | None,
                           content_bank_url: str | None, target_creator: str | None,
                           settings: Settings, now: str | None = None) -> ClipResult:
    now = now or utcnow_iso()
    cid = _manual_id(title, now)
    session.add(Campaign(
        id=cid, source="manual", external_id=cid, campaign_type="clipping",
        niche=niche, title=title, status="active", access_status="ingestable",
        ingest_method="manual", first_seen_at=now, last_seen_at=now,
        content_bank_url=content_bank_url or None, target_creator=target_creator or None,
    ))
    session.commit()
    try:
        job = create_clip_job(session, cid, settings)
    except ValueError:
        return ClipResult(ok=True, job_id=None, error="campaign created; no acquirable source")
    return ClipResult(ok=True, job_id=job.id, status=job.status)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web_actions.py -v && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/web/actions.py tests/test_web_actions.py
git commit -m "feat(b4): guarded write actions — clip_this, idempotent mark_posted, manual campaign"
```

---

## Task 6: Approval surface — `GET /`, `POST /clip/{campaign_id}` + templates

**Files:**
- Modify: `src/clipscore/web/app.py`
- Create: `src/clipscore/web/templates/approval.html`, `src/clipscore/web/templates/_clip_button.html`
- Test: `tests/test_web_approval.py`

**Interfaces:**
- Consumes: `queries.approval_rows`, `queries.monthly_cost_usd`, `actions.clip_this`, `get_db`.
- Produces routes:
  - `GET /` → renders `approval.html` with `rows=approval_rows(...)` and `monthly_cost=monthly_cost_usd(...)`.
  - `POST /clip/{campaign_id}` → `actions.clip_this(...)`; renders the `_clip_button.html` partial reflecting the result (HTMX swaps it in; a non-HTMX post returns the same partial HTML, status 200).

- [ ] **Step 1: Write the failing test** `tests/test_web_approval.py`:

```python
from fastapi.testclient import TestClient
from clipscore.config import Settings
from clipscore.db.models import Campaign, CampaignScore
from clipscore.web.app import create_app, get_db


def _client(session):
    app = create_app(Settings(clip_est_cost_usd=2.0))
    def _override():
        yield session
    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def _camp(session, cid, pct=0.8, bank="https://drive.google.com/x"):
    session.add(Campaign(id=cid, source="s", external_id=cid, campaign_type="clipping",
                         title=f"T {cid}", niche="gaming", status="active",
                         access_status="ingestable", first_seen_at="2026-01-01T00:00:00Z",
                         last_seen_at="2026-01-01T00:00:00Z", content_bank_url=bank))
    session.add(CampaignScore(campaign_id=cid, scored_at="2026-01-01T00:00:00Z",
                              cvs_niche_percentile=pct))
    session.commit()


def test_approval_page_lists_campaigns(session):
    _camp(session, "a")
    resp = _client(session).get("/")
    assert resp.status_code == 200
    assert "T a" in resp.text
    assert "Clip this" in resp.text


def test_post_clip_enqueues(session):
    _camp(session, "a")
    resp = _client(session).post("/clip/a")
    assert resp.status_code == 200
    assert "queued" in resp.text.lower()
    from clipscore.db.models import ClipJob
    assert session.query(ClipJob).filter_by(campaign_id="a").count() == 1


def test_post_clip_no_source_shows_error(session):
    _camp(session, "a", bank=None)
    resp = _client(session).post("/clip/a")
    assert resp.status_code == 200
    assert "no acquirable source" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_approval.py -v`
Expected: FAIL — 404 on `/` (route not registered).

- [ ] **Step 3: Register the routes.** In `web/app.py`, inside `create_app` (before `return app`), add imports at top of file:

```python
from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from clipscore.web import queries, actions
```

and the routes:

```python
    templates = app.state.templates

    @app.get("/", response_class=HTMLResponse)
    def approval(request: Request, db: Session = Depends(get_db)):
        return templates.TemplateResponse("approval.html", {
            "request": request,
            "rows": queries.approval_rows(db, settings),
            "monthly_cost": queries.monthly_cost_usd(db),
        })

    @app.post("/clip/{campaign_id}", response_class=HTMLResponse)
    def clip(campaign_id: str, request: Request, db: Session = Depends(get_db)):
        result = actions.clip_this(db, campaign_id, settings)
        return templates.TemplateResponse("_clip_button.html", {
            "request": request, "campaign_id": campaign_id, "result": result,
        })
```

- [ ] **Step 4: Write `templates/approval.html`:**

```html
{% extends "base.html" %}
{% block title %}Approve — clipscore{% endblock %}
{% block body %}
<h1>Approve campaigns</h1>
<p class="muted">Monthly clip cost so far: ${{ "%.2f"|format(monthly_cost) }}</p>
<table>
  <tr><th>Campaign</th><th>Niche</th><th>CVS %ile</th><th>Est. cost</th><th></th></tr>
  {% for r in rows %}
  <tr>
    <td>{{ r.title or r.campaign_id }}</td>
    <td>{{ r.niche or "" }}</td>
    <td>{{ "%.2f"|format(r.cvs_niche_percentile) if r.cvs_niche_percentile is not none else "—" }}</td>
    <td>${{ "%.2f"|format(r.est_cost_usd) }}</td>
    <td>{# the swap target id lives on the partial's inner <div>, not here #}
      {% include "_clip_button.html" with context %}
    </td>
  </tr>
  {% endfor %}
</table>
{% endblock %}
```

Where the row loop needs `result` and `campaign_id` for the include, set defaults at the top of `_clip_button.html` (below) so it renders both from the page (no result yet) and from the POST response.

- [ ] **Step 5: Write `templates/_clip_button.html`:**

```html
{% set cid = campaign_id if campaign_id is defined else r.campaign_id %}
{% set res = result if result is defined else None %}
{% set jstatus = (r.job_status if r is defined else None) %}
<div id="clip-{{ cid }}">
  {% if res and res.ok %}
    <span>queued ✓</span>
  {% elif res and not res.ok %}
    <span class="warn">{{ res.error }}</span>
  {% elif jstatus %}
    <span class="muted">{{ jstatus }}</span>
  {% elif r is defined and not r.clippable %}
    <span class="warn">no acquirable source</span>
  {% else %}
    <form hx-post="/clip/{{ cid }}" hx-target="#clip-{{ cid }}" hx-swap="outerHTML"
          method="post" action="/clip/{{ cid }}">
      <button type="submit">Clip this</button>
    </form>
  {% endif %}
</div>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_web_approval.py -v && pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/clipscore/web/app.py src/clipscore/web/templates/ tests/test_web_approval.py
git commit -m "feat(b4): approval surface — GET / + POST /clip with HTMX clip-button partial"
```

---

## Task 7: Review surface — `GET /review`, `GET /review/{clip_id}`, `GET /media/{clip_id}`, `POST /posted/{match_id}` + templates

**Files:**
- Modify: `src/clipscore/web/app.py`
- Create: `src/clipscore/web/templates/review_list.html`, `src/clipscore/web/templates/review.html`, `src/clipscore/web/templates/_posted.html`
- Test: `tests/test_web_review.py`, `tests/test_web_media.py`

**Interfaces:**
- Consumes: `queries.ready_clips`, `queries.review_detail`, `warnings.duplicate_warnings`, `actions.mark_posted`, `get_db`, `app.state.settings`.
- Produces routes:
  - `GET /review` → `review_list.html` with `clips=ready_clips(db)`.
  - `GET /review/{clip_id}` → `review.html` with `detail=review_detail(...)` (404 if `None`); attaches per-match `duplicate_warnings(db, clip_id, match.campaign_id)`.
  - `GET /media/{clip_id}` → `FileResponse` of `Clip.storage_uri`, **traversal-guarded** (see Global Constraints); 404 otherwise.
  - `POST /posted/{match_id}` → `actions.mark_posted(...)`; renders `_posted.html` (HTMX swap).

- [ ] **Step 1: Write the failing tests** `tests/test_web_review.py`:

```python
from fastapi.testclient import TestClient
from clipscore.config import Settings
from clipscore.db.models import Campaign, Clip, SourceAsset, ClipMatch, Outcome
from clipscore.web.app import create_app, get_db


def _client(session, settings=None):
    app = create_app(settings or Settings())
    def _override():
        yield session
    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def _ready_clip(session, cid="a"):
    session.add(Campaign(id=cid, source="s", external_id=cid, campaign_type="clipping",
                         title=f"T {cid}", status="active", access_status="ingestable",
                         first_seen_at="2026-01-01T00:00:00Z", last_seen_at="2026-01-01T00:00:00Z"))
    sa = SourceAsset(clip_job_id=1, storage_uri="media/x.mp4"); session.add(sa); session.commit()
    clip = Clip(source_asset_id=sa.id, platform_variant="tiktok", duration_s=60,
                status="ready", cost_usd=0.5, created_at="2026-07-10T00:00:00Z")
    session.add(clip); session.commit()
    m = ClipMatch(clip_id=clip.id, campaign_id=cid, match_score=0.7, meets_requirements=1,
                  suggested_caption="watch #ad", rank=1); session.add(m); session.commit()
    return clip, m


def test_review_list(session):
    _ready_clip(session)
    resp = _client(session).get("/review")
    assert resp.status_code == 200 and "tiktok" in resp.text


def test_review_detail_renders_video_and_caption(session):
    clip, m = _ready_clip(session)
    resp = _client(session).get(f"/review/{clip.id}")
    assert resp.status_code == 200
    assert f"/media/{clip.id}" in resp.text
    assert "watch #ad" in resp.text
    assert "T a" in resp.text


def test_review_detail_404(session):
    assert _client(session).get("/review/9999").status_code == 404


def test_review_shows_duplicate_warning(session):
    clip, m = _ready_clip(session)
    session.add(Outcome(campaign_id="a", clip_id=clip.id, clips_posted=1,
                        logged_at="2026-07-10T00:00:00Z")); session.commit()
    resp = _client(session).get(f"/review/{clip.id}")
    assert "Already delivered to this campaign" in resp.text


def test_post_posted_writes_outcome(session):
    clip, m = _ready_clip(session)
    resp = _client(session).post(f"/posted/{m.id}")
    assert resp.status_code == 200 and "posted" in resp.text.lower()
    assert session.query(Outcome).filter_by(clip_id=clip.id, campaign_id="a").count() == 1
    # idempotent: second post does not append
    _client(session).post(f"/posted/{m.id}")
    assert session.query(Outcome).filter_by(clip_id=clip.id, campaign_id="a").count() == 1
```

and `tests/test_web_media.py`:

```python
import os
from fastapi.testclient import TestClient
from clipscore.config import Settings
from clipscore.db.models import Clip, SourceAsset
from clipscore.web.app import create_app, get_db


def _client(session, settings):
    app = create_app(settings)
    def _override():
        yield session
    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def test_media_serves_file_under_media_dir(session, tmp_path):
    media = tmp_path / "media"
    (media / "clips").mkdir(parents=True)
    f = media / "clips" / "c.mp4"
    f.write_bytes(b"\x00\x01\x02")
    sa = SourceAsset(clip_job_id=1); session.add(sa); session.commit()
    clip = Clip(source_asset_id=sa.id, status="ready", storage_uri=str(f),
                created_at="2026-07-10T00:00:00Z"); session.add(clip); session.commit()
    client = _client(session, Settings(media_dir=str(media)))
    resp = client.get(f"/media/{clip.id}")
    assert resp.status_code == 200 and resp.content == b"\x00\x01\x02"


def test_media_404_when_missing_uri(session, tmp_path):
    sa = SourceAsset(clip_job_id=1); session.add(sa); session.commit()
    clip = Clip(source_asset_id=sa.id, status="ready", storage_uri=None,
                created_at="2026-07-10T00:00:00Z"); session.add(clip); session.commit()
    client = _client(session, Settings(media_dir=str(tmp_path / "media")))
    assert client.get(f"/media/{clip.id}").status_code == 404


def test_media_404_on_traversal_outside_media_dir(session, tmp_path):
    outside = tmp_path / "secret.txt"; outside.write_text("nope")
    sa = SourceAsset(clip_job_id=1); session.add(sa); session.commit()
    clip = Clip(source_asset_id=sa.id, status="ready", storage_uri=str(outside),
                created_at="2026-07-10T00:00:00Z"); session.add(clip); session.commit()
    (tmp_path / "media").mkdir()
    client = _client(session, Settings(media_dir=str(tmp_path / "media")))
    assert client.get(f"/media/{clip.id}").status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_review.py tests/test_web_media.py -v`
Expected: FAIL — 404s (routes not registered).

- [ ] **Step 3: Register the routes.** In `web/app.py` add imports:

```python
import os
from fastapi import HTTPException
from fastapi.responses import FileResponse
from clipscore.web import warnings as dupwarn
```

and inside `create_app` (before `return app`):

```python
    @app.get("/review", response_class=HTMLResponse)
    def review_list(request: Request, db: Session = Depends(get_db)):
        return templates.TemplateResponse("review_list.html", {
            "request": request, "clips": queries.ready_clips(db),
        })

    @app.get("/review/{clip_id}", response_class=HTMLResponse)
    def review(clip_id: int, request: Request, db: Session = Depends(get_db)):
        detail = queries.review_detail(db, clip_id)
        if detail is None:
            raise HTTPException(status_code=404)
        warns = {m.match_id: dupwarn.duplicate_warnings(db, clip_id, m.campaign_id)
                 for m in detail.matches}
        return templates.TemplateResponse("review.html", {
            "request": request, "detail": detail, "warnings": warns,
        })

    @app.get("/media/{clip_id}")
    def media(clip_id: int, db: Session = Depends(get_db)):
        clip = db.get(__import__("clipscore.db.models", fromlist=["Clip"]).Clip, clip_id)
        if clip is None or not clip.storage_uri:
            raise HTTPException(status_code=404)
        real = os.path.realpath(clip.storage_uri)
        media_root = os.path.realpath(settings.media_dir)
        if not (real == media_root or real.startswith(media_root + os.sep)):
            raise HTTPException(status_code=404)
        if not os.path.isfile(real):
            raise HTTPException(status_code=404)
        return FileResponse(real)

    @app.post("/posted/{match_id}", response_class=HTMLResponse)
    def posted(match_id: int, request: Request, db: Session = Depends(get_db)):
        result = actions.mark_posted(db, match_id)
        return templates.TemplateResponse("_posted.html", {
            "request": request, "result": result,
        })
```

> Prefer a top-of-file `from clipscore.db.models import Clip` over the inline `__import__`; the inline form is shown only to keep the snippet self-contained. Use the clean import.

- [ ] **Step 4: Write `templates/review_list.html`:**

```html
{% extends "base.html" %}
{% block title %}Review — clipscore{% endblock %}
{% block body %}
<h1>Ready clips</h1>
{% if not clips %}<p class="muted">No clips ready.</p>{% endif %}
<ul>
  {% for c in clips %}
  <li><a href="/review/{{ c.clip_id }}">Clip {{ c.clip_id }} — {{ c.platform_variant or "?" }},
      {{ c.duration_s or "?" }}s</a></li>
  {% endfor %}
</ul>
{% endblock %}
```

- [ ] **Step 5: Write `templates/review.html`:**

```html
{% extends "base.html" %}
{% block title %}Clip {{ detail.clip.clip_id }} — clipscore{% endblock %}
{% block body %}
<h1>Clip {{ detail.clip.clip_id }}</h1>
<video controls width="360" src="{{ detail.download_url }}"></video>
<p><a href="{{ detail.download_url }}" download>Download</a></p>

<h2>Requirements</h2>
<pre>{{ detail.requirements }}</pre>

<h2>Matches</h2>
{% for m in detail.matches %}
<div>
  <strong>#{{ m.rank if m.rank is not none else "?" }}</strong>
  {{ m.campaign_title or m.campaign_id }}
  (score {{ "%.3f"|format(m.match_score) if m.match_score is not none else "—" }})
  {% for w in warnings.get(m.match_id, []) %}<div class="warn">{{ w }}</div>{% endfor %}
  <p class="muted">Caption: {{ m.suggested_caption or "—" }}</p>
  <div id="posted-{{ m.match_id }}">
    <form hx-post="/posted/{{ m.match_id }}" hx-target="#posted-{{ m.match_id }}"
          hx-swap="outerHTML" method="post" action="/posted/{{ m.match_id }}">
      <button type="submit">Mark posted</button>
    </form>
  </div>
</div>
<hr>
{% endfor %}
{% endblock %}
```

- [ ] **Step 6: Write `templates/_posted.html`:**

```html
<div>{% if result.ok %}<span>posted ✓</span>{% else %}<span class="warn">{{ result.error }}</span>{% endif %}</div>
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_web_review.py tests/test_web_media.py -v && pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/clipscore/web/app.py src/clipscore/web/templates/ tests/test_web_review.py tests/test_web_media.py
git commit -m "feat(b4): review surface — list, detail (video/matches/caption/dup-warnings), traversal-safe media, mark-posted"
```

---

## Task 8: Manual entry + cost panel + end-to-end acceptance

**Files:**
- Modify: `src/clipscore/web/app.py`
- Create: `src/clipscore/web/templates/manual.html`
- Test: `tests/test_web_manual.py`, `tests/test_web_e2e.py`

**Interfaces:**
- Consumes: `actions.create_manual_campaign`, `get_db`.
- Produces routes:
  - `GET /manual` → `manual.html` (form).
  - `POST /manual` → parse form fields (`title`, `niche`, `content_bank_url`, `target_creator`) via FastAPI `Form(...)`; call `create_manual_campaign`; re-render `manual.html` with a `result` banner.

- [ ] **Step 1: Write the failing tests** `tests/test_web_manual.py`:

```python
from fastapi.testclient import TestClient
from clipscore.config import Settings
from clipscore.db.models import Campaign
from clipscore.web.app import create_app, get_db


def _client(session):
    app = create_app(Settings())
    def _override():
        yield session
    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def test_manual_form_renders(session):
    resp = _client(session).get("/manual")
    assert resp.status_code == 200 and "<form" in resp.text


def test_manual_post_creates_campaign_and_job(session):
    resp = _client(session).post("/manual", data={
        "title": "Hand Entry", "niche": "gaming",
        "content_bank_url": "https://drive.google.com/z", "target_creator": "",
    })
    assert resp.status_code == 200
    assert session.query(Campaign).filter_by(source="manual").count() == 1
```

and the e2e `tests/test_web_e2e.py`:

```python
import os

from fastapi.testclient import TestClient
from clipscore.config import Settings
from clipscore.db.models import Campaign, CampaignScore, Clip, ClipMatch, Outcome
from clipscore.factory.acquire.base import BaseAcquirer, AcquisitionResult
from clipscore.factory.clip.base import FakeClipEngine
from clipscore.jobs.clipfactory import process_clip_jobs
from clipscore.web.app import create_app, get_db


class _FakeAcquirer(BaseAcquirer):
    """No-network acquirer: writes a tiny local file and reports creator '@me'
    so the produced clip matches the seeded campaign (see match.py criteria)."""
    source_type = "campaign_provided"
    requires_authorization = False

    def acquire(self, source_ref, dest_path, **kw):
        os.makedirs(os.path.dirname(dest_path + ".mp4"), exist_ok=True)
        with open(dest_path + ".mp4", "wb") as fh:
            fh.write(b"x" * 42)
        return AcquisitionResult(status="acquired", platform="campaign_provided",
                                 creator="@me", storage_uri=dest_path + ".mp4", bytes=42)


def _client(session, settings):
    app = create_app(settings)
    def _override():
        yield session
    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def test_approve_produce_review_post_flow(session, tmp_path):
    settings = Settings(_env_file=None, media_dir=str(tmp_path / "media"),
                        clip_engine="fake", clip_est_cost_usd=1.0, max_media_gb=50.0)
    # a scored, clippable, campaign-provided campaign. target_creator '@me' +
    # target_platforms ['tiktok'] + no length window make the produced tiktok
    # clip (creator '@me', 60s) match this campaign in match_clip.
    session.add(Campaign(id="a", source="s", external_id="a", campaign_type="clipping",
                         title="E2E", niche="gaming", status="active",
                         access_status="ingestable", allowed_socials=["tiktok"],
                         first_seen_at="2026-07-01T00:00:00Z", last_seen_at="2026-07-01T00:00:00Z",
                         content_bank_url="https://drive.google.com/e2e",
                         target_creator='["@me"]', target_platforms='["tiktok"]'))
    session.add(CampaignScore(campaign_id="a", scored_at="2026-07-01T00:00:00Z",
                              cvs_niche_percentile=0.9))
    session.commit()

    client = _client(session, settings)

    # approve -> enqueue a queued clip_job
    assert client.post("/clip/a").status_code == 200

    # The scheduler's runner advances ONE stage per call (queued -> acquired ->
    # produced -> matched/ready), so loop until nothing advances. The web layer
    # never produces clips; we inject the fake acquirer + FakeClipEngine so no
    # network / real engine is touched.
    reg = {"campaign_provided": _FakeAcquirer()}
    for _ in range(6):
        res = process_clip_jobs(session, settings, registry=reg, engine=FakeClipEngine())
        if res["advanced"] == 0:
            break

    ready = session.query(Clip).filter_by(status="ready").all()
    assert ready, "expected at least one ready clip"
    clip = ready[0]
    match = session.query(ClipMatch).filter_by(clip_id=clip.id, campaign_id="a").first()
    assert match is not None

    # review renders
    assert client.get(f"/review/{clip.id}").status_code == 200

    # mark posted -> exactly one outcome
    assert client.post(f"/posted/{match.id}").status_code == 200
    assert session.query(Outcome).filter_by(clip_id=clip.id, campaign_id="a").count() == 1

    # a second post is idempotent; the dup warning now fires on the review page
    client.post(f"/posted/{match.id}")
    assert session.query(Outcome).filter_by(clip_id=clip.id, campaign_id="a").count() == 1
    assert "Already delivered to this campaign" in client.get(f"/review/{clip.id}").text
```

> **e2e lifecycle notes (verified against B2/B3 source):** `process_clip_jobs(session, settings, *, registry=None, engine=None, llm=None, now=None)` advances each in-flight job exactly one stage per call, so the loop is required. `registry` (source_type → acquirer) and `engine` are the injection seams — the `_FakeAcquirer` writes a local file and reports `creator="@me"`; combined with `target_creator='["@me"]'`, `target_platforms='["tiktok"]'`, and no length window, `match_clip` yields one candidate (score `0.9 × 0.9`). No `build_engine`/network path is exercised.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_manual.py tests/test_web_e2e.py -v`
Expected: FAIL — `/manual` 404; e2e fails at `/clip/a` or later.

- [ ] **Step 3: Register the manual routes.** In `web/app.py` add `from fastapi import Form` and inside `create_app`:

```python
    @app.get("/manual", response_class=HTMLResponse)
    def manual_form(request: Request):
        return templates.TemplateResponse("manual.html", {"request": request, "result": None})

    @app.post("/manual", response_class=HTMLResponse)
    def manual_submit(request: Request, db: Session = Depends(get_db),
                      title: str = Form(...), niche: str = Form(""),
                      content_bank_url: str = Form(""), target_creator: str = Form("")):
        result = actions.create_manual_campaign(
            db, title=title, niche=niche or None,
            content_bank_url=content_bank_url or None,
            target_creator=target_creator or None, settings=settings,
        )
        return templates.TemplateResponse("manual.html", {"request": request, "result": result})
```

- [ ] **Step 4: Write `templates/manual.html`:**

```html
{% extends "base.html" %}
{% block title %}Manual entry — clipscore{% endblock %}
{% block body %}
<h1>Manual campaign entry</h1>
{% if result %}
  {% if result.ok and result.job_id %}<p>Created and queued (job {{ result.job_id }}).</p>
  {% elif result.ok %}<p class="warn">{{ result.error }}</p>
  {% else %}<p class="warn">{{ result.error }}</p>{% endif %}
{% endif %}
<form method="post" action="/manual">
  <p><label>Title <input name="title" required></label></p>
  <p><label>Niche <input name="niche"></label></p>
  <p><label>Content bank URL <input name="content_bank_url" size="50"></label></p>
  <p><label>Target creator <input name="target_creator"></label></p>
  <button type="submit">Create + queue</button>
</form>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_web_manual.py tests/test_web_e2e.py -v && pytest -q`
Expected: PASS; full suite green.

- [ ] **Step 6: Commit**

```bash
git add src/clipscore/web/app.py src/clipscore/web/templates/manual.html tests/test_web_manual.py tests/test_web_e2e.py
git commit -m "feat(b4): manual-entry form + cost panel + end-to-end approve→produce→review→post acceptance"
```

---

## Done criteria

- `clipscore web` serves the approval, review, and manual-entry surfaces on localhost.
- "Clip this" enqueues a job (reusing `create_clip_job`); the scheduler's B3 runner produces clips; the review page shows the video, ranked matches, requirements, and suggested caption.
- "Mark posted" writes exactly one `outcomes` row per `(clip_id, campaign_id)`; monthly cost readout reflects `clips.cost_usd` for the current ET month.
- Advisory duplicate-deliverable warnings fire for repeat delivery and cross-campaign footage reuse.
- Media serving is traversal-safe. All tests run under `TestClient` with no network, no server, no real video. One additive migration (`0006`).
