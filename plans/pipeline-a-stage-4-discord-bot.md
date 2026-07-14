# Pipeline A — Stage 4: Discord Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Surface scored campaigns through Discord — percentile alerts, a `/top` slash command, and a daily 9am-ET summary — without ever blocking ingest/scoring.

**Architecture:** A **testable core** (selection, dedup, formatting, movers) behind a `Notifier` protocol, fully CI-tested with a fake notifier and in-memory DB, plus a **thin `discord.py` adapter** that is manual-acceptance-only (no token/network in CI). Ingest+scoring in `poll.run_once` stays Discord-free; alert dispatch is guarded so a Discord failure can never break the committed ingest/score.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x, APScheduler, `discord.py` (new dep), `zoneinfo` (stdlib), structlog, pytest.

## Context

This is **Phase 4** of `IMPLEMENTATION_PLAN.md:276-281` (source of truth). Stages 1–3 are merged: campaigns ingest, scores (with `cvs_niche_percentile`) are written every ok cycle, and a ranked CLI exists (`jobs/rank.py`, `ranked_rows`/`format_table`).

**Two decisions resolved with the user (2026-07-14):**
- **Alert dedup = once per `(campaign_id, epoch)`.** A campaign alerts on first entry into its niche's top percentile; a genuine relaunch (epoch bump from budget top-up/revival) can re-alert. Requires a new `alerts` table → **migration `0003`**.
- **Full bot:** build the tested core AND a thin `discord.py` adapter (adds the dependency); the adapter is verified manually with the user's token.

## Existing code this builds on

- `src/clipscore/db/models.py` — `Campaign` (`.status`, `.access_status`, `.campaign_type`, `.niche`, `.title`, `.url`), `CampaignSnapshot` (`.epoch`, `.captured_at`), `CampaignScore` (`.campaign_id`, `.scored_at`, `.cvs_raw`, `.cvs_niche_percentile`, `.net_cpm`, `.budget_health`, `.sat_factor`, `.id`). Add a new `Alert` model.
- `src/clipscore/config.py` — `Settings` (has `discord_token: str | None`). Add alert/summary settings.
- `src/clipscore/jobs/rank.py` — `ranked_rows(session, top, niche)` (latest score per campaign, eligibility-filtered, sorted by percentile). `main`/`format_table` for the CLI. **Refactor `ranked_rows` to use the new shared eligibility helper.**
- `src/clipscore/jobs/poll.py` — `run_once(session)` (ingest + score; returns dict with `status`). Stays Discord-free.
- `src/clipscore/time.py` — `utcnow_iso()` → `"%Y-%m-%dT%H:%M:%SZ"`. ISO strings sort lexicographically = chronologically (compare `scored_at`/`captured_at` as strings directly).
- Alembic head is `0002`; new revision `0003` with `down_revision = "0002"`.
- `tests/test_migration_0002.py` — the migration-test pattern that WORKS in this repo (subprocess + `CLIPSCORE_DB_URL` env var; `alembic/env.py` overrides `sqlalchemy.url` from settings, so `Config.set_main_option` is a no-op — do NOT use it).
- `tests/conftest.py` — `session` fixture (in-memory SQLite, all tables from ORM).

## Global Constraints

Every task's requirements implicitly include these. Copy exact values.

- **Honest scoring — message literals (test each, like the Stage-3 CLI caveat):**
  - ALL three message types (alert, `/top`, summary) carry the literal `estimated screening signal, not a payout prediction`.
  - The ALERT additionally carries the literal `relatively best in its niche — not a quality gate` (percentile alerts fire on the *relatively* best ~10% regardless of absolute quality).
  - No message ever labels `cvs_raw` (or any number) as `$/hr`.
- **Alert dedup = once per `(campaign_id, epoch)`.** Crossing semantics: a campaign alerts iff `percentile >= ALERT_PERCENTILE AND not already_alerted(campaign_id, epoch)`. This is exactly "first crossing per epoch" — dedup suppresses re-entry within an epoch; a new epoch can re-alert. **Do not build a separate was-below-last-cycle tracker for alerts.**
- **Epoch for dedup = the campaign's latest snapshot's epoch at dispatch time.** This is correct ONLY because `poll_and_alert` runs ingest→score→dispatch in one process with no intervening ingest. State this assumption in code comments.
- **`MIN_NICHE_SAMPLE` floor:** a niche alerts only if it has `>= MIN_NICHE_SAMPLE` eligible campaigns **with a non-None percentile this cycle** (the same population the percentile was computed over). Below the floor → suppress alerts for that niche (the CLI/`/top` still shows them).
- **Eligibility (single source of truth):** "on the board / alertable" = latest score per campaign where `status=="active"` AND `access_status=="ingestable"` AND `campaign_type != "ugc"`. Implemented ONCE in `scoring/board.py:eligible_latest_scores` and reused. Zero-CPM campaigns have `cvs_niche_percentile is None` → excluded from alerts and movers.
- **Movers = relative churn, NOT improvement.** `cvs_niche_percentile` is recomputed each cycle against the live population, so a campaign's percentile moves when *other* campaigns enter/leave. Label the summary section `change in relative niche standing` — never "improved".
- **Movers 24h endpoints (pin exactly):** current = latest score; past = the score row with the largest `scored_at` that is `<= now−24h` (most recent score ≥24h old). If no such past row (campaign younger than 24h) → **exclude** (do not emit delta 0). Require non-None percentile at BOTH endpoints. "Biggest" = top-N by `abs(delta)`, showing sign. Window math in UTC, independent of the ET summary schedule.
- **Bot never blocks ingest/scoring.** `poll_and_alert` calls `run_once` first (ingest+score, already committed) and wraps alert dispatch in try/except so any notifier/Discord failure is logged and swallowed — the ingest/score result is still returned. Individual alert-send failures are logged and skipped (that alert retries next cycle because it was not recorded).
- **Concrete counts:** `ALERT_PERCENTILE = 0.90`, `MIN_NICHE_SAMPLE = 5`, summary shows **top-1 per niche** and **top-5 movers**, `/top` shows top-10 within niche.

---

## Task 1: Migration 0003 (alerts table) + Alert model + config

**Files:**
- Modify: `src/clipscore/db/models.py`
- Create: `alembic/versions/0003_add_alerts.py`
- Modify: `src/clipscore/config.py`
- Test: `tests/test_migration_0003.py`, `tests/test_alert_model.py`, `tests/test_config_alerts.py`

**Interfaces:**
- Produces: `Alert` ORM model; `alerts` table via migration `0003`; `Settings` fields `alert_percentile: float = 0.90`, `min_niche_sample: int = 5`, `discord_alert_channel_id: int | None = None`, `summary_hour_et: int = 9`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_alert_model.py
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
import pytest
from clipscore.db.models import Alert

def test_alert_roundtrip(session):
    session.add(Alert(campaign_id="c1", epoch=0, niche="gaming",
                      cvs_niche_percentile=0.95, alerted_at="2026-07-14T00:00:00Z"))
    session.commit()
    a = session.execute(select(Alert)).scalars().one()
    assert a.campaign_id == "c1" and a.epoch == 0 and a.cvs_niche_percentile == 0.95

def test_alert_unique_campaign_epoch(session):
    session.add(Alert(campaign_id="c1", epoch=0, alerted_at="t"))
    session.commit()
    session.add(Alert(campaign_id="c1", epoch=0, alerted_at="t2"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

def test_alert_same_campaign_new_epoch_allowed(session):
    session.add(Alert(campaign_id="c1", epoch=0, alerted_at="t"))
    session.commit()
    session.add(Alert(campaign_id="c1", epoch=1, alerted_at="t2"))
    session.commit()  # different epoch -> allowed
    assert len(session.execute(select(Alert)).scalars().all()) == 2
```

```python
# tests/test_config_alerts.py
from clipscore.config import Settings

def test_alert_config_defaults():
    s = Settings()
    assert s.alert_percentile == 0.90
    assert s.min_niche_sample == 5
    assert s.discord_alert_channel_id is None
    assert s.summary_hour_et == 9
```

```python
# tests/test_migration_0003.py
import subprocess, sqlite3, os, sys

def test_migration_adds_alerts_table(tmp_path):
    # Mirrors tests/test_migration_0002.py: drive alembic in a subprocess with
    # CLIPSCORE_DB_URL set (env.py reads settings, ignoring set_main_option).
    db = tmp_path / "m.db"
    env = {**os.environ, "CLIPSCORE_DB_URL": f"sqlite:///{db}"}
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(db)
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    cols = {row[1] for row in con.execute("PRAGMA table_info(alerts)")}
    con.close()
    assert "alerts" in tables
    assert {"id", "campaign_id", "epoch", "niche", "cvs_niche_percentile", "alerted_at"} <= cols
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_alert_model.py tests/test_config_alerts.py tests/test_migration_0003.py -v`
Expected: FAIL (no `Alert`, no config fields, no `0003`).

- [ ] **Step 3: Implement**

In `src/clipscore/db/models.py`, add (`UniqueConstraint` is already imported):

```python
class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("campaign_id", "epoch", name="uq_alert_campaign_epoch"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(String, index=True)
    epoch: Mapped[int] = mapped_column(Integer)
    niche: Mapped[str | None] = mapped_column(String, nullable=True)
    cvs_niche_percentile: Mapped[float | None] = mapped_column(Float, nullable=True)
    alerted_at: Mapped[str] = mapped_column(String)
```

In `src/clipscore/config.py`, add to `Settings` (near `discord_token`):

```python
    alert_percentile: float = 0.90
    min_niche_sample: int = 5
    discord_alert_channel_id: int | None = None
    summary_hour_et: int = 9
```

Create `alembic/versions/0003_add_alerts.py` (hand-written, mirroring `0002`'s style):

```python
"""add alerts table

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.String(), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("niche", sa.String(), nullable=True),
        sa.Column("cvs_niche_percentile", sa.Float(), nullable=True),
        sa.Column("alerted_at", sa.String(), nullable=False),
        sa.UniqueConstraint("campaign_id", "epoch", name="uq_alert_campaign_epoch"),
    )
    op.create_index("ix_alerts_campaign_id", "alerts", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_alerts_campaign_id", table_name="alerts")
    op.drop_table("alerts")
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_alert_model.py tests/test_config_alerts.py tests/test_migration_0003.py -v` then `pytest -q`.
Expected: PASS; full suite still green.

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/db/models.py src/clipscore/config.py alembic/versions/0003_add_alerts.py tests/test_alert_model.py tests/test_config_alerts.py tests/test_migration_0003.py
git commit -m "feat: alerts table (migration 0003) + Alert model + bot config"
```

---

## Task 2: Shared eligibility helper + refactor ranked_rows

**Files:**
- Create: `src/clipscore/scoring/board.py`
- Modify: `src/clipscore/jobs/rank.py`
- Test: `tests/test_board_eligibility.py`

**Interfaces:**
- Produces: `eligible_latest_scores(session) -> list[tuple[Campaign, CampaignScore]]` — the latest `CampaignScore` (max `id`) per `campaign_id`, joined to its `Campaign`, filtered to `status=="active"` AND `access_status=="ingestable"` AND `campaign_type != "ugc"`. This is the SINGLE source of truth for "which scored campaigns are on the board / alertable"; `rank.ranked_rows` and (later) `select_alerts`/`compute_movers` all consume it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_board_eligibility.py
from clipscore.db.models import Campaign, CampaignScore
from clipscore.scoring.board import eligible_latest_scores
from clipscore.time import utcnow_iso

def _camp(session, cid, **kw):
    now = utcnow_iso()
    d = dict(id=cid, source="contentrewards", external_id=cid, niche="gaming",
             cpm_usd=2.0, cap_provenance="absent", status="active",
             access_status="ingestable", first_seen_at=now, last_seen_at=now)
    d.update(kw); session.add(Campaign(**d)); session.commit()

def _score(session, cid, sid_hint, scored_at):
    session.add(CampaignScore(campaign_id=cid, scored_at=scored_at, cvs_raw=1.0,
                              cvs_niche_percentile=0.5))
    session.commit()

def test_returns_latest_score_only(session):
    _camp(session, "a")
    _score(session, "a", 1, "2026-07-10T00:00:00Z")
    _score(session, "a", 2, "2026-07-14T00:00:00Z")
    pairs = eligible_latest_scores(session)
    assert len(pairs) == 1
    c, s = pairs[0]
    assert c.id == "a" and s.scored_at == "2026-07-14T00:00:00Z"

def test_excludes_ended_walled_ugc(session):
    _camp(session, "live"); _score(session, "live", 1, "t")
    _camp(session, "ended", status="ended"); _score(session, "ended", 1, "t")
    _camp(session, "walled", access_status="tos_restricted"); _score(session, "walled", 1, "t")
    _camp(session, "ugc", campaign_type="ugc"); _score(session, "ugc", 1, "t")
    ids = {c.id for c, _ in eligible_latest_scores(session)}
    assert ids == {"live"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_board_eligibility.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# src/clipscore/scoring/board.py
"""Single source of truth for 'which scored campaigns are on the board / alertable':
the latest score per campaign, restricted to currently-eligible campaigns. Consumed
by jobs.rank and the bot so the eligibility predicate lives in exactly one place."""
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from clipscore.db.models import Campaign, CampaignScore


def eligible_latest_scores(session: Session) -> list[tuple[Campaign, CampaignScore]]:
    latest_ids = select(func.max(CampaignScore.id)).group_by(CampaignScore.campaign_id)
    scores = session.execute(
        select(CampaignScore).where(CampaignScore.id.in_(latest_ids))
    ).scalars().all()
    camps = {c.id: c for c in session.execute(select(Campaign)).scalars().all()}
    out = []
    for s in scores:
        c = camps.get(s.campaign_id)
        if c is None:
            continue
        if c.status != "active" or c.access_status != "ingestable" or c.campaign_type == "ugc":
            continue
        out.append((c, s))
    return out
```

In `src/clipscore/jobs/rank.py`, refactor `ranked_rows` to delegate the eligibility+latest-score query to the helper (keep the row-dict shape, niche filter, sort, and top-limit exactly as they are). Replace the manual query/loop head with:

```python
from clipscore.scoring.board import eligible_latest_scores
# ...
def ranked_rows(session, top=None, niche=None):
    rows = []
    for c, s in eligible_latest_scores(session):
        key = c.niche or "other"
        if niche is not None and key != niche:
            continue
        rows.append(dict(campaign_id=s.campaign_id, title=c.title, niche=key,
                         cpm_usd=c.cpm_usd, net_cpm=s.net_cpm,
                         budget_health=s.budget_health, sat_factor=s.sat_factor,
                         cvs_raw=s.cvs_raw, cvs_niche_percentile=s.cvs_niche_percentile))
    rows.sort(key=lambda r: (r["cvs_niche_percentile"] is not None,
                             r["cvs_niche_percentile"] or 0.0), reverse=True)
    return rows[:top] if top else rows
```

Remove the now-unused `func`/`select`/`Campaign`/`CampaignScore` imports from `rank.py` only if nothing else there uses them.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_board_eligibility.py tests/test_rank_cli.py -v` then `pytest -q`.
Expected: PASS — the existing `rank` tests (incl. `test_stale_ineligible_campaigns_excluded`, `test_uses_latest_score_only`) still pass, proving the refactor preserved behavior.

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/scoring/board.py src/clipscore/jobs/rank.py tests/test_board_eligibility.py
git commit -m "refactor: extract eligible_latest_scores helper; rank uses it"
```

---

## Task 3: Alert dedup state

**Files:**
- Create: `src/clipscore/bot/__init__.py` (empty)
- Create: `src/clipscore/bot/state.py`
- Test: `tests/test_alert_state.py`

**Interfaces:**
- Produces: `already_alerted(session, campaign_id, epoch) -> bool`; `record_alert(session, campaign_id, epoch, niche, percentile, alerted_at) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_alert_state.py
from clipscore.bot.state import already_alerted, record_alert

def test_not_alerted_initially(session):
    assert already_alerted(session, "c1", 0) is False

def test_record_then_alerted(session):
    record_alert(session, "c1", 0, "gaming", 0.95, "2026-07-14T00:00:00Z")
    assert already_alerted(session, "c1", 0) is True

def test_dedup_is_per_epoch(session):
    record_alert(session, "c1", 0, "gaming", 0.95, "t")
    assert already_alerted(session, "c1", 1) is False   # new epoch: not yet alerted
    record_alert(session, "c1", 1, "gaming", 0.96, "t2")
    assert already_alerted(session, "c1", 1) is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_alert_state.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# src/clipscore/bot/state.py
"""Alert dedup state: one alert per (campaign_id, epoch). A relaunch bumps the
epoch (see ingest.upsert), so a genuinely relaunched campaign can alert again."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from clipscore.db.models import Alert


def already_alerted(session: Session, campaign_id: str, epoch: int) -> bool:
    row = session.execute(
        select(Alert.id).where(Alert.campaign_id == campaign_id, Alert.epoch == epoch)
    ).first()
    return row is not None


def record_alert(session: Session, campaign_id: str, epoch: int, niche,
                 percentile, alerted_at: str) -> None:
    session.add(Alert(campaign_id=campaign_id, epoch=epoch, niche=niche,
                      cvs_niche_percentile=percentile, alerted_at=alerted_at))
    session.commit()
```

Create empty `src/clipscore/bot/__init__.py`.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_alert_state.py -v` then `pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/bot/__init__.py src/clipscore/bot/state.py tests/test_alert_state.py
git commit -m "feat: alert dedup state (once per campaign+epoch)"
```

---

## Task 4: Alert selection + movers

**Files:**
- Create: `src/clipscore/bot/notify.py`
- Test: `tests/test_select_alerts.py`, `tests/test_movers.py`

**Interfaces:**
- Consumes: `eligible_latest_scores` (board), `already_alerted` (state), `CampaignSnapshot` (for epoch).
- Produces:
  - `select_alerts(session, alert_percentile, min_niche_sample, now_iso) -> list[dict]` — candidate alerts. A campaign qualifies iff its niche has `>= min_niche_sample` eligible non-None-percentile campaigns this cycle, `cvs_niche_percentile >= alert_percentile`, and `not already_alerted(campaign_id, epoch)`. Each dict: `{campaign_id, title, niche, url, percentile, cvs_raw, epoch}`. `epoch` = the campaign's latest snapshot epoch.
  - `compute_movers(session, now_iso, window_hours=24, top_n=5) -> list[dict]` — see Global Constraints for the 24h endpoint rules. Each dict: `{campaign_id, title, niche, current, past, delta}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_select_alerts.py
import pytest
from clipscore.db.models import Campaign, CampaignScore, CampaignSnapshot
from clipscore.bot.notify import select_alerts
from clipscore.bot.state import record_alert
from clipscore.time import utcnow_iso

def _camp(session, cid, niche="gaming", **kw):
    now = utcnow_iso()
    d = dict(id=cid, source="contentrewards", external_id=cid, niche=niche, title=f"T{cid}",
             url=f"http://x/{cid}", cpm_usd=2.0, cap_provenance="absent", status="active",
             access_status="ingestable", first_seen_at=now, last_seen_at=now)
    d.update(kw); session.add(Campaign(**d)); session.commit()

def _score(session, cid, pct, cvs=1.0):
    session.add(CampaignScore(campaign_id=cid, scored_at=utcnow_iso(), cvs_raw=cvs,
                              cvs_niche_percentile=pct))
    session.commit()

def _snap(session, cid, epoch=0):
    session.add(CampaignSnapshot(campaign_id=cid, epoch=epoch, captured_at=utcnow_iso()))
    session.commit()

def _niche_of(session, n, count, top_pct):
    # helper: create `count` campaigns in niche n; the first gets top_pct, rest 0.1..
    for i in range(count):
        cid = f"{n}{i}"
        _camp(session, cid, niche=n)
        _score(session, cid, top_pct if i == 0 else 0.1 + i * 0.01)
        _snap(session, cid)
    return f"{n}0"

def test_alerts_top_percentile_in_big_enough_niche(session):
    top = _niche_of(session, "gaming", 5, 0.95)
    out = select_alerts(session, 0.90, 5, utcnow_iso())
    assert any(a["campaign_id"] == top for a in out)

def test_small_niche_suppressed(session):
    _niche_of(session, "music", 3, 0.99)   # only 3 < MIN_NICHE_SAMPLE 5
    out = select_alerts(session, 0.90, 5, utcnow_iso())
    assert out == []

def test_below_threshold_not_alerted(session):
    _niche_of(session, "gaming", 5, 0.80)   # top is only 0.80 < 0.90
    out = select_alerts(session, 0.90, 5, utcnow_iso())
    assert out == []

def test_already_alerted_excluded(session):
    top = _niche_of(session, "gaming", 5, 0.95)
    record_alert(session, top, 0, "gaming", 0.95, utcnow_iso())
    out = select_alerts(session, 0.90, 5, utcnow_iso())
    assert all(a["campaign_id"] != top for a in out)

def test_new_epoch_re_alerts(session):
    top = _niche_of(session, "gaming", 5, 0.95)
    record_alert(session, top, 0, "gaming", 0.95, utcnow_iso())
    # relaunch: latest snapshot now epoch 1
    _snap(session, top, epoch=1)
    out = select_alerts(session, 0.90, 5, utcnow_iso())
    assert any(a["campaign_id"] == top and a["epoch"] == 1 for a in out)

def test_none_percentile_not_counted_or_alerted(session):
    # 4 real + 1 zero-cpm(None) in gaming -> valid population is 4 < 5 -> suppressed
    _niche_of(session, "gaming", 4, 0.95)
    _camp(session, "znull", niche="gaming"); _score(session, "znull", None); _snap(session, "znull")
    out = select_alerts(session, 0.90, 5, utcnow_iso())
    assert out == []
```

```python
# tests/test_movers.py
from datetime import datetime, timedelta, timezone
from clipscore.db.models import Campaign, CampaignScore
from clipscore.bot.notify import compute_movers

def iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)

def _camp(session, cid):
    session.add(Campaign(id=cid, source="contentrewards", external_id=cid, niche="gaming",
                title=f"T{cid}", cpm_usd=2.0, cap_provenance="absent", status="active",
                access_status="ingestable", first_seen_at=iso(NOW), last_seen_at=iso(NOW)))
    session.commit()

def _score(session, cid, pct, at):
    session.add(CampaignScore(campaign_id=cid, scored_at=at, cvs_raw=1.0, cvs_niche_percentile=pct))
    session.commit()

def test_mover_delta_uses_past_ge_24h(session):
    _camp(session, "a")
    _score(session, "a", 0.3, iso(NOW - timedelta(hours=30)))   # past (>=24h)
    _score(session, "a", 0.5, iso(NOW - timedelta(hours=1)))    # between (ignored as past)
    _score(session, "a", 0.9, iso(NOW))                          # current
    m = compute_movers(session, iso(NOW))
    assert len(m) == 1 and abs(m[0]["delta"] - 0.6) < 1e-9       # 0.9 - 0.3

def test_young_campaign_excluded(session):
    _camp(session, "b")
    _score(session, "b", 0.5, iso(NOW - timedelta(hours=2)))    # no score >=24h old
    _score(session, "b", 0.9, iso(NOW))
    assert compute_movers(session, iso(NOW)) == []

def test_none_percentile_endpoint_excluded(session):
    _camp(session, "c")
    _score(session, "c", None, iso(NOW - timedelta(hours=30)))
    _score(session, "c", 0.9, iso(NOW))
    assert compute_movers(session, iso(NOW)) == []

def test_sorted_by_abs_delta_desc(session):
    _camp(session, "up"); _camp(session, "down")
    _score(session, "up", 0.5, iso(NOW - timedelta(hours=30))); _score(session, "up", 0.6, iso(NOW))
    _score(session, "down", 0.9, iso(NOW - timedelta(hours=30))); _score(session, "down", 0.3, iso(NOW))
    m = compute_movers(session, iso(NOW))
    assert m[0]["campaign_id"] == "down"   # |−0.6| > |0.1|
    assert m[0]["delta"] < 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_select_alerts.py tests/test_movers.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# src/clipscore/bot/notify.py
"""Alert selection and movers analysis over the eligible latest-score board.
Pure of Discord; returns plain dicts for the formatting/dispatch layers."""
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from clipscore.db.models import CampaignScore, CampaignSnapshot
from clipscore.scoring.board import eligible_latest_scores
from clipscore.bot.state import already_alerted

_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _latest_epoch(session: Session, campaign_id: str) -> int:
    # Dedup epoch = the campaign's latest snapshot epoch AT DISPATCH TIME. Correct
    # only because poll_and_alert runs ingest->score->dispatch in one process with
    # no intervening ingest, so this reflects the epoch the current score was for.
    s = session.execute(
        select(CampaignSnapshot).where(CampaignSnapshot.campaign_id == campaign_id)
        .order_by(CampaignSnapshot.id.desc()).limit(1)
    ).scalars().first()
    return s.epoch if s is not None else 0


def select_alerts(session: Session, alert_percentile: float, min_niche_sample: int,
                  now_iso: str) -> list[dict]:
    pairs = eligible_latest_scores(session)
    # valid population per niche = eligible campaigns with a non-None percentile
    by_niche: dict[str, list] = {}
    for c, s in pairs:
        if s.cvs_niche_percentile is None:
            continue
        by_niche.setdefault(c.niche or "other", []).append((c, s))
    out = []
    for niche, members in by_niche.items():
        if len(members) < min_niche_sample:
            continue
        for c, s in members:
            if s.cvs_niche_percentile < alert_percentile:
                continue
            epoch = _latest_epoch(session, c.id)
            if already_alerted(session, c.id, epoch):
                continue
            out.append(dict(campaign_id=c.id, title=c.title, niche=niche, url=c.url,
                            percentile=s.cvs_niche_percentile, cvs_raw=s.cvs_raw, epoch=epoch))
    return out


def compute_movers(session: Session, now_iso: str, window_hours: int = 24,
                   top_n: int = 5) -> list[dict]:
    cutoff_iso = (datetime.strptime(now_iso, _FMT) - timedelta(hours=window_hours)).strftime(_FMT)
    movers = []
    for c, latest in eligible_latest_scores(session):
        if latest.cvs_niche_percentile is None:
            continue
        past = session.execute(
            select(CampaignScore).where(CampaignScore.campaign_id == c.id,
                                        CampaignScore.scored_at <= cutoff_iso)
            .order_by(CampaignScore.scored_at.desc(), CampaignScore.id.desc()).limit(1)
        ).scalars().first()
        if past is None or past.cvs_niche_percentile is None:
            continue
        delta = latest.cvs_niche_percentile - past.cvs_niche_percentile
        movers.append(dict(campaign_id=c.id, title=c.title, niche=c.niche or "other",
                           current=latest.cvs_niche_percentile,
                           past=past.cvs_niche_percentile, delta=delta))
    movers.sort(key=lambda m: abs(m["delta"]), reverse=True)
    return movers[:top_n]
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_select_alerts.py tests/test_movers.py -v` then `pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/bot/notify.py tests/test_select_alerts.py tests/test_movers.py
git commit -m "feat: alert selection (percentile+floor+dedup) and 24h movers"
```

---

## Task 5: Message formatting

**Files:**
- Create: `src/clipscore/bot/messages.py`
- Test: `tests/test_messages.py`

**Interfaces:**
- Produces (pure functions, string in → string out):
  - `format_alert(payload: dict) -> str`
  - `format_top(rows: list[dict], niche: str | None) -> str`
  - `format_summary(top_per_niche: list[dict], movers: list[dict], now_iso: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_messages.py
from clipscore.bot.messages import format_alert, format_top, format_summary, CAVEAT, NOT_A_GATE

def _payload():
    return dict(campaign_id="c1", title="Cool Campaign", niche="gaming",
                url="http://x/c1", percentile=0.95, cvs_raw=12.3, epoch=0)

def test_alert_carries_both_literals_and_link():
    out = format_alert(_payload())
    assert CAVEAT in out
    assert NOT_A_GATE in out
    assert "http://x/c1" in out
    assert "gaming" in out and "Cool Campaign" in out
    assert "$/hr" not in out

def test_top_carries_caveat_no_hr():
    rows = [dict(campaign_id="c1", title="T", niche="gaming", cpm_usd=2.0, net_cpm=1.8,
                 budget_health=0.7, sat_factor=0.8, cvs_raw=9.0, cvs_niche_percentile=0.9)]
    out = format_top(rows, "gaming")
    assert CAVEAT in out and "$/hr" not in out
    assert "gaming" in out

def test_top_empty():
    assert "no scored campaigns" in format_top([], None).lower()

def test_summary_movers_labeled_relative_not_improved():
    top = [dict(niche="gaming", title="T", cvs_niche_percentile=0.9)]
    movers = [dict(campaign_id="c1", title="T", niche="gaming", current=0.9, past=0.3, delta=0.6)]
    out = format_summary(top, movers, "2026-07-14T13:00:00Z")
    assert CAVEAT in out
    assert "change in relative niche standing" in out.lower()
    assert "improved" not in out.lower()
    assert "$/hr" not in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_messages.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# src/clipscore/bot/messages.py
"""Discord message text. Pure formatting; honest-scoring literals are mandatory
(see the tests / plan Global Constraints)."""

CAVEAT = "estimated screening signal, not a payout prediction"
NOT_A_GATE = "relatively best in its niche — not a quality gate"


def format_alert(p: dict) -> str:
    pct = f"{p['percentile'] * 100:.0f}th pct" if p.get("percentile") is not None else "n/a"
    return (
        f"📈 **{p['title']}** ({p['niche']}) — {pct} in niche\n"
        f"{p['url']}\n"
        f"_{NOT_A_GATE}; {CAVEAT}._"
    )


def format_top(rows: list[dict], niche) -> str:
    scope = f"niche '{niche}'" if niche else "all niches"
    lines = [f"**Top campaigns — {scope}** (_{CAVEAT}_)", ""]
    if not rows:
        lines.append("(no scored campaigns)")
        return "\n".join(lines)
    for i, r in enumerate(rows, 1):
        pct = r["cvs_niche_percentile"]
        pcts = f"{pct * 100:.0f}%" if pct is not None else "-"
        lines.append(f"{i}. {r['niche']:<14} {(r['title'] or '')[:32]:<32} pctile={pcts}")
    return "\n".join(lines)


def format_summary(top_per_niche: list[dict], movers: list[dict], now_iso: str) -> str:
    lines = [f"**Daily screening summary** — {now_iso} (_{CAVEAT}_)", "", "__Top per niche__"]
    for r in top_per_niche:
        pct = r.get("cvs_niche_percentile")
        pcts = f"{pct * 100:.0f}%" if pct is not None else "-"
        lines.append(f"• {r['niche']:<14} {(r.get('title') or '')[:32]:<32} pctile={pcts}")
    lines += ["", "__Biggest movers (change in relative niche standing)__"]
    if not movers:
        lines.append("(none)")
    for m in movers:
        arrow = "▲" if m["delta"] >= 0 else "▼"
        lines.append(f"{arrow} {(m['title'] or '')[:32]:<32} {m['niche']:<14} "
                     f"{m['past'] * 100:.0f}% → {m['current'] * 100:.0f}% "
                     f"({m['delta'] * 100:+.0f} pts)")
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_messages.py -v` then `pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/bot/messages.py tests/test_messages.py
git commit -m "feat: Discord message formatting with honest-scoring literals"
```

---

## Task 6: Dispatch orchestrators + Notifier protocol

**Files:**
- Create: `src/clipscore/bot/dispatch.py`
- Test: `tests/test_dispatch.py`

**Interfaces:**
- Consumes: `select_alerts`, `compute_movers`, `eligible_latest_scores`, `record_alert`, `format_alert`/`format_top`/`format_summary`, `run_once`, `get_settings`, `utcnow_iso`.
- Produces:
  - `Notifier` (typing.Protocol) with `send(self, text: str) -> None`.
  - `dispatch_alerts(session, notifier, settings, now_iso=None) -> dict` — select → format → `notifier.send` → `record_alert` (record ONLY after a successful send; a send that raises is logged and skipped, so it retries next cycle). Returns `{"alerts_sent": int}`. Idempotent: a second immediate call sends nothing.
  - `dispatch_summary(session, notifier, now_iso=None) -> dict` — build top-1-per-niche + `compute_movers`, `format_summary`, `notifier.send`. Returns `{"summary_sent": bool}`.
  - `poll_and_alert(session, notifier, settings=None, now_iso=None) -> dict` — `run_once(session)` first (ingest+score, Discord-free & already committed); then, only if `status == "ok"`, `dispatch_alerts` wrapped in try/except so any failure is logged and swallowed. Returns the ingest/score result (augmented with `alerts_sent` when dispatch ran).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dispatch.py
import pytest
from unittest.mock import patch
from clipscore.db.models import Campaign, CampaignScore, CampaignSnapshot
from clipscore.bot.dispatch import dispatch_alerts, dispatch_summary, poll_and_alert
from clipscore.config import get_settings
from clipscore.time import utcnow_iso

class FakeNotifier:
    def __init__(self, fail=False):
        self.sent = []; self.fail = fail
    def send(self, text):
        if self.fail:
            raise RuntimeError("discord down")
        self.sent.append(text)

def _big_niche(session, top_pct=0.95, n=5):
    now = utcnow_iso()
    for i in range(n):
        cid = f"g{i}"
        session.add(Campaign(id=cid, source="contentrewards", external_id=cid, niche="gaming",
                    title=f"T{cid}", url=f"http://x/{cid}", cpm_usd=2.0, cap_provenance="absent",
                    status="active", access_status="ingestable", first_seen_at=now, last_seen_at=now))
        session.add(CampaignScore(campaign_id=cid, scored_at=now, cvs_raw=1.0,
                    cvs_niche_percentile=top_pct if i == 0 else 0.1 + i * 0.01))
        session.add(CampaignSnapshot(campaign_id=cid, epoch=0, captured_at=now))
    session.commit()

def test_dispatch_sends_then_dedups(session):
    _big_niche(session)
    n = FakeNotifier()
    r1 = dispatch_alerts(session, n, get_settings())
    assert r1["alerts_sent"] == 1 and len(n.sent) == 1
    r2 = dispatch_alerts(session, n, get_settings())        # already recorded
    assert r2["alerts_sent"] == 0 and len(n.sent) == 1

def test_failed_send_not_recorded_retries(session):
    _big_niche(session)
    bad = FakeNotifier(fail=True)
    r = dispatch_alerts(session, bad, get_settings())
    assert r["alerts_sent"] == 0                             # nothing recorded
    good = FakeNotifier()
    assert dispatch_alerts(session, good, get_settings())["alerts_sent"] == 1  # retried

def test_summary_sends(session):
    _big_niche(session)
    n = FakeNotifier()
    assert dispatch_summary(session, n)["summary_sent"] is True
    assert len(n.sent) == 1

def test_poll_and_alert_survives_notifier_failure(session):
    with patch("clipscore.bot.dispatch.run_once", return_value={"status": "ok", "scored": 5}), \
         patch("clipscore.bot.dispatch.dispatch_alerts", side_effect=RuntimeError("boom")):
        res = poll_and_alert(session, FakeNotifier())
    assert res["status"] == "ok" and res["scored"] == 5     # ingest/score result intact

def test_poll_and_alert_skips_dispatch_on_non_ok(session):
    with patch("clipscore.bot.dispatch.run_once", return_value={"status": "halted"}), \
         patch("clipscore.bot.dispatch.dispatch_alerts") as m:
        res = poll_and_alert(session, FakeNotifier())
    m.assert_not_called()
    assert res["status"] == "halted"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_dispatch.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# src/clipscore/bot/dispatch.py
"""Transport-agnostic orchestration: select/format/send/record, and the combined
poll+alert cycle. The Discord adapter supplies a Notifier; failures here never
touch the already-committed ingest/score result."""
from typing import Protocol
import structlog
from sqlalchemy.orm import Session
from clipscore.config import get_settings
from clipscore.time import utcnow_iso
from clipscore.jobs.poll import run_once
from clipscore.scoring.board import eligible_latest_scores
from clipscore.bot.notify import select_alerts, compute_movers
from clipscore.bot.state import record_alert
from clipscore.bot.messages import format_alert, format_top, format_summary

log = structlog.get_logger()


class Notifier(Protocol):
    def send(self, text: str) -> None: ...


def dispatch_alerts(session: Session, notifier: Notifier, settings, now_iso: str | None = None) -> dict:
    now_iso = now_iso or utcnow_iso()
    candidates = select_alerts(session, settings.alert_percentile,
                               settings.min_niche_sample, now_iso)
    sent = 0
    for c in candidates:
        try:
            notifier.send(format_alert(c))
        except Exception:
            log.warning("alert_send_failed", campaign_id=c["campaign_id"])
            continue   # not recorded -> retried next cycle
        record_alert(session, c["campaign_id"], c["epoch"], c["niche"], c["percentile"], now_iso)
        sent += 1
    return {"alerts_sent": sent}


def _top_per_niche(session: Session) -> list[dict]:
    best: dict[str, dict] = {}
    for c, s in eligible_latest_scores(session):
        if s.cvs_niche_percentile is None:
            continue
        niche = c.niche or "other"
        cur = best.get(niche)
        if cur is None or s.cvs_niche_percentile > cur["cvs_niche_percentile"]:
            best[niche] = dict(niche=niche, title=c.title,
                               cvs_niche_percentile=s.cvs_niche_percentile)
    return sorted(best.values(), key=lambda r: r["niche"])


def dispatch_summary(session: Session, notifier: Notifier, now_iso: str | None = None) -> dict:
    now_iso = now_iso or utcnow_iso()
    text = format_summary(_top_per_niche(session), compute_movers(session, now_iso), now_iso)
    try:
        notifier.send(text)
    except Exception:
        log.warning("summary_send_failed")
        return {"summary_sent": False}
    return {"summary_sent": True}


def poll_and_alert(session: Session, notifier: Notifier, settings=None,
                   now_iso: str | None = None) -> dict:
    result = run_once(session)   # ingest + score; Discord-free, already committed
    if result.get("status") == "ok":
        try:
            r = dispatch_alerts(session, notifier, settings or get_settings(), now_iso)
            result["alerts_sent"] = r["alerts_sent"]
        except Exception:
            log.exception("alert_dispatch_failed")   # never break ingest/score
    return result
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_dispatch.py -v` then `pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/bot/dispatch.py tests/test_dispatch.py
git commit -m "feat: alert/summary dispatch + guarded poll_and_alert cycle"
```

---

## Task 7: discord.py adapter + scheduler wiring + dependency

**Files:**
- Create: `src/clipscore/bot/discord_bot.py`
- Modify: `pyproject.toml`
- Test: `tests/test_discord_notifier.py`

**Interfaces:**
- Consumes: `dispatch_alerts`/`dispatch_summary`/`poll_and_alert`, `ranked_rows`, `format_top`, `get_settings`, `build_scheduler` patterns.
- Produces:
  - `DiscordNotifier` implementing `Notifier`: `send(text)` posts to the configured channel from a (possibly other-thread) sync context via `asyncio.run_coroutine_threadsafe`.
  - `build_bot()` / `run_bot()` assembling the `discord.py` client + `/top` app command + APScheduler jobs (poll+alert on `poll_interval_minutes`; daily summary via `CronTrigger(hour=summary_hour_et, timezone=ZoneInfo("America/New_York"))`).

**This task is mostly manual-acceptance** (gateway/token/network unavailable in CI). Keep the `discord.py`-specific code thin; unit-test only what can be tested with mocks.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add to `dependencies`:

```toml
    "discord.py>=2.3,<3.0",
```

- [ ] **Step 2: Write the failing test (DiscordNotifier only)**

```python
# tests/test_discord_notifier.py
from unittest.mock import MagicMock, patch
from clipscore.bot.discord_bot import DiscordNotifier

def test_notifier_schedules_channel_send():
    channel = MagicMock()
    loop = MagicMock()
    n = DiscordNotifier(channel=channel, loop=loop)
    with patch("clipscore.bot.discord_bot.asyncio.run_coroutine_threadsafe") as rct:
        n.send("hello")
    channel.send.assert_called_once_with("hello")
    rct.assert_called_once()   # coroutine handed to the bot's event loop

def test_notifier_noop_without_channel():
    # graceful: no channel configured -> send is a logged no-op, never raises
    DiscordNotifier(channel=None, loop=None).send("hi")
```

- [ ] **Step 3: Run to verify it fails**

Run: `pytest tests/test_discord_notifier.py -v`
Expected: FAIL (module missing).

- [ ] **Step 4: Implement**

```python
# src/clipscore/bot/discord_bot.py
"""Thin discord.py adapter. Manual-acceptance: needs a real token/channel/network.
All decision logic lives in bot.notify/dispatch (CI-tested); this only bridges to
Discord and schedules jobs. Discord failures must never break ingest/scoring."""
import asyncio
import structlog
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from clipscore.config import get_settings
from clipscore.bot.dispatch import poll_and_alert, dispatch_summary
from clipscore.jobs.rank import ranked_rows
from clipscore.bot.messages import format_top

log = structlog.get_logger()


class DiscordNotifier:
    """Notifier that posts to a discord.TextChannel from a sync scheduler thread."""
    def __init__(self, channel, loop):
        self._channel = channel
        self._loop = loop

    def send(self, text: str) -> None:
        if self._channel is None or self._loop is None:
            log.info("discord_notifier_noop", reason="no channel configured")
            return
        asyncio.run_coroutine_threadsafe(self._channel.send(text), self._loop)


def build_bot(session_factory):
    """Assemble the discord.py client, /top command, and scheduler. Returns (client,
    scheduler, start_callable). Not exercised in CI — see manual acceptance."""
    import discord
    from discord import app_commands

    settings = get_settings()
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    sched = BackgroundScheduler()

    @tree.command(name="top", description="Top campaigns by within-niche screening percentile")
    async def top(interaction, niche: str | None = None):
        await interaction.response.defer()   # 3s ACK; ranked_rows may be slow as scores grow
        with session_factory() as s:
            text = format_top(ranked_rows(s, top=10, niche=niche), niche)
        await interaction.followup.send(text)

    @client.event
    async def on_ready():
        await tree.sync()
        channel = client.get_channel(settings.discord_alert_channel_id) if settings.discord_alert_channel_id else None
        notifier = DiscordNotifier(channel=channel, loop=asyncio.get_running_loop())

        def poll_job():
            with session_factory() as s:
                poll_and_alert(s, notifier)

        def summary_job():
            with session_factory() as s:
                dispatch_summary(s, notifier)

        sched.add_job(poll_job, "interval", minutes=settings.poll_interval_minutes, id="poll_alert")
        sched.add_job(summary_job, CronTrigger(hour=settings.summary_hour_et,
                      timezone=ZoneInfo("America/New_York")), id="daily_summary")
        sched.start()
        log.info("bot_ready", channel=settings.discord_alert_channel_id)

    return client, sched


def run_bot(session_factory):
    client, _ = build_bot(session_factory)
    client.run(get_settings().discord_token)
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest tests/test_discord_notifier.py -v` then `pytest -q`.
(Install the new dep first if needed: `python3 -m pip install -e ".[dev]"`.)

- [ ] **Step 6: Commit**

```bash
git add src/clipscore/bot/discord_bot.py pyproject.toml tests/test_discord_notifier.py
git commit -m "feat: discord.py adapter (/top, alerts channel, daily ET summary)"
```

---

## Verification

- **Unit (CI, no network):** `pytest -q` green — all Stage-1/2/3 tests plus the new suites (alert model/migration/config, board helper, dedup state, select_alerts, movers, messages, dispatch, DiscordNotifier). The `discord.py` gateway/command/scheduler wiring in `build_bot` is NOT exercised in CI.
- **Migration:** `alembic upgrade head` on a fresh DB applies `0001`→`0002`→`0003`; `alerts` table present with the unique `(campaign_id, epoch)` constraint.
- **Manual live acceptance (needs a bot token + a test channel):**
  1. Set `CLIPSCORE_DISCORD_TOKEN` and `CLIPSCORE_DISCORD_ALERT_CHANNEL_ID`; run the bot; confirm it connects and `tree.sync()` registers `/top`.
  2. `/top` and `/top niche:gaming` respond **within 3s** (via `defer()` + followup) and carry the caveat. Note: `/top` latency will grow as `campaign_scores` accumulates (Stage-3 deferred: unbounded scores table).
  3. Seed a scored DB where a niche has ≥`MIN_NICHE_SAMPLE` campaigns and one ≥`ALERT_PERCENTILE`; run one poll cycle; confirm exactly one alert posts, carrying both the payout caveat and the "not a quality gate" label; a second cycle posts nothing (dedup); simulate a relaunch (epoch bump) and confirm it re-alerts.
  4. Confirm the daily summary fires at 09:00 America/New_York (DST-correct) with top-per-niche + movers labeled "change in relative niche standing".
  5. Kill Discord connectivity mid-cycle; confirm ingest/scoring still complete and the process does not crash.

## Out of scope (later stages / deferred)

- Outcome logging CLI + weekly recalibration (Phase 5).
- Unbounded `campaign_scores` growth / scores rollup (Stage-3 deferred; degrades `/top` latency — pair with a scores-retention job).
- ETag/304 activation; other Stage-2/3 deferred minors.
- Multi-account / auto-posting (permanently out of scope per project principles).
