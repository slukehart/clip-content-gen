# Pipeline A — Stage 3: Scoring Engine + CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn ingested campaigns + snapshots into `campaign_scores` rows carrying a within-niche screening signal (`cvs_niche_percentile`), and surface a ranked CLI board.

**Architecture:** Pure scoring primitives (`scoring/formula.py`, `scoring/budget.py`, `scoring/percentile.py`) with zero DB coupling, orchestrated by a DB-facing engine (`scoring/engine.py`) that gathers inputs, computes every component, and writes score rows. Scoring runs after each **successful** ingest cycle. A retention/rollup job trims old snapshots. A zero-dependency CLI (`jobs/rank.py`) prints the within-niche board.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x, structlog, pytest. No new runtime dependencies.

## Context

This is **Phase 3** of `IMPLEMENTATION_PLAN.md` (the source-of-truth design). Stage 1 (data layer) and Stage 2 (contentrewards ingester) are merged. The scoring formula is specified verbatim at `IMPLEMENTATION_PLAN.md:185-233`; implement it exactly. All Stage 3 tables (`campaign_scores`, `niche_baselines`, `outcomes`) already exist from migration `0001` — **no migration in this stage.**

**Two deferred design decisions resolved with the user (2026-07-13):**
- **`stats.successRate` stays guessed.** Its meaning is undetermined (spike). Capture it raw in the snapshot (already done); `p_approval` remains the guessed `DEFAULT_P_APPROVAL` constant. Do **not** wire successRate/engagement into scoring — revisit in Phase 5 with outcome data.
- **`niche_baselines` re-seeded to the real source categories**, slugified, with **uniform** placeholder guesses (honest: within-niche ranking is partition-agnostic; cross-niche isn't trustworthy in v1 regardless).

**Not in this stage:** ETag/304 conditional-GET activation (stays on the Stage-2 deferred list — activating the dormant `fetch()→[]` 304 path is a real behavior change conflating "unchanged" with "bad parse"; it needs its own task with a distinct status. Do **not** touch it here). Discord bot + `ALERT_PERCENTILE`/`MIN_NICHE_SAMPLE` (Phase 4). Feedback loop (Phase 5).

## Existing code this builds on (reuse, don't reinvent)

- `src/clipscore/db/models.py` — `Campaign`, `CampaignSnapshot`, `CampaignScore`, `NicheBaseline` (PK `niche`, cols `e_views_median: int`, `p_threshold: float`), `PlatformTrust` (PK `source`, cols `trust_score`, `default_fee_pct`).
- `src/clipscore/config.py` — `Settings`: already has `default_p_approval=0.7`, `default_assumed_cap_usd=500.0`, `hours_per_clip=0.75`. `get_settings()` is `lru_cache`d — tests that change env must `get_settings.cache_clear()`.
- `src/clipscore/seed.py` — `seed_all(session)`, `NICHE_BASELINE_SEED`, `PLATFORM_TRUST_SEED` (upsert-style).
- `src/clipscore/time.py` — `utcnow_iso()` → `"%Y-%m-%dT%H:%M:%SZ"` (parse with `datetime.fromisoformat` after replacing trailing `Z`, or `datetime.strptime`).
- `src/clipscore/ingest/contentrewards.py` — `normalize()` sets `niche = category.strip().lower()`; **null category → `niche=None`** (so scoring must map `None`/unknown → `"other"` baseline). `campaign_type` stored verbatim (`clipping`/`ugc`/`both`). `platform_fee_pct` on the campaign is `None` (fee comes from `platform_trust` at scoring).
- `src/clipscore/ingest/upsert.py` — `_current_epoch` bumps epoch on revival or budget top-up (>1.10×); each snapshot carries `.epoch`.
- `src/clipscore/jobs/poll.py` — `run_once(session)` calls `run_ingest_batch(...)` and returns a dict whose `"status"` is `"ok"` on a clean cycle.
- `tests/conftest.py` — `session` fixture (in-memory SQLite, all tables). Seed `niche_baselines`/`platform_trust` inside tests that need them.

## Global Constraints

Every task's requirements implicitly include these. Copy exact values.

- **Formula is verbatim.** Implement `IMPLEMENTATION_PLAN.md:185-233` exactly. Constants come from `Settings`, never hardcoded in logic: `default_p_approval=0.7`, `default_assumed_cap_usd=500.0`, `hours_per_clip=0.75`.
- **Honest scoring.** Every user-facing surface carries the literal caveat string **`estimated screening signal, not a payout prediction`**. Never present `cvs_raw` as a $/hr figure. The primary user-facing number is `cvs_niche_percentile` (within-niche, 0–1).
- **Small footprint.** No new runtime dependencies. The CLI table is hand-rolled fixed-width text.
- **Scored population** = campaigns with `status == "active"` AND `access_status == "ingestable"` AND `campaign_type != "ugc"`. UGC campaigns are skipped entirely (no score row). Non-ingestable (walled/restricted) campaigns are skipped.
- **Niche resolution:** score partition key = `campaign.niche or "other"`; if no baseline row exists for that key, fall back to the `"other"` baseline (guaranteed seeded).
- **Zero/missing CPM** (`cpm_usd` is `None` or `<= 0`) → `cvs_raw = 0.0`, all downstream components `0.0`, log a warning, and **exclude from the percentile population** (write the score row with `cvs_niche_percentile = None`).
- **`cvs_niche_percentile`** = empirical CDF within the niche over the valid population: `count(cvs_raw <= this) / n`. Ties get identical values; `n == 1` → `1.0`. Excluded (zero-CPM) campaigns are not in the population and get `None`.
- **`budget_health`** uses only snapshots in the **latest snapshot's epoch**; picks the snapshot closest to `now − 48h` that is **at least 48h old**; `< 2` in-epoch snapshots, no ≥48h-old snapshot, or missing budget → `0.7`; `daily_burn <= 0` (topped up / no burn) → `1.0`.
- **Scoring runs only after a successful ingest** (`run_ingest_batch` returned `status == "ok"`).
- **No schema migration.** All tables exist.

---

## Task 1: Re-seed niche_baselines to real categories + retention config

**Files:**
- Modify: `src/clipscore/seed.py`
- Modify: `src/clipscore/config.py`
- Test: `tests/test_seed_baselines.py`

**Interfaces:**
- Consumes: `NicheBaseline`, `PlatformTrust` models; `seed_all(session)`.
- Produces: `niche_baselines` rows keyed by the real slugified categories `{entertainment, technology, product, music, logo, personal brand, slideshow, gaming, other}`; `Settings.raw_retention_days: int = 14`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seed_baselines.py
from sqlalchemy import select
from clipscore.db.models import NicheBaseline
from clipscore.seed import seed_all, NICHE_BASELINE_SEED
from clipscore.config import Settings

REAL_NICHES = {"entertainment", "technology", "product", "music",
               "logo", "personal brand", "slideshow", "gaming", "other"}

def test_seed_loads_real_categories(session):
    seed_all(session)
    got = {n for (n,) in session.execute(select(NicheBaseline.niche)).all()}
    assert got == REAL_NICHES

def test_other_partition_present(session):
    seed_all(session)
    assert session.get(NicheBaseline, "other") is not None

def test_baselines_uniform_guesses(session):
    seed_all(session)
    rows = session.execute(select(NicheBaseline)).scalars().all()
    assert len({r.e_views_median for r in rows}) == 1
    assert len({r.p_threshold for r in rows}) == 1

def test_reseed_prunes_stale_rows(session):
    # a stale topical niche from the old seed must be removed on re-seed
    session.add(NicheBaseline(niche="crypto", e_views_median=6000, p_threshold=0.5))
    session.commit()
    seed_all(session)
    assert session.get(NicheBaseline, "crypto") is None

def test_seed_idempotent(session):
    seed_all(session); seed_all(session)
    rows = session.execute(select(NicheBaseline)).scalars().all()
    assert len(rows) == len(REAL_NICHES)

def test_retention_config_default():
    assert Settings().raw_retention_days == 14
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_seed_baselines.py -v`
Expected: FAIL (old seed has topical niches; `crypto` survives; no `raw_retention_days`).

- [ ] **Step 3: Implement**

In `src/clipscore/config.py`, add to `Settings` (near `hours_per_clip`):

```python
    raw_retention_days: int = 14
```

In `src/clipscore/seed.py`, replace `NICHE_BASELINE_SEED` and add stale-row pruning to `seed_all`:

```python
# Real source categories (slugified: category.strip().lower()). Uniform placeholder
# guesses — within-niche ranking is partition-agnostic and cross-niche is not
# trustworthy in v1, so differentiated per-niche guesses would be guess-on-guess.
# null category normalizes to niche=None, which scoring maps to "other".
_E_VIEWS_GUESS = 8000
_P_THRESHOLD_GUESS = 0.55
NICHE_BASELINE_SEED = [
    dict(niche=n, e_views_median=_E_VIEWS_GUESS, p_threshold=_P_THRESHOLD_GUESS)
    for n in ("entertainment", "technology", "product", "music",
              "logo", "personal brand", "slideshow", "gaming", "other")
]
```

In `seed_all`, after the niche upsert loop and before `session.commit()`, prune rows not in the canonical set:

```python
    canonical = {row["niche"] for row in NICHE_BASELINE_SEED}
    for existing in session.execute(select(NicheBaseline)).scalars().all():
        if existing.niche not in canonical:
            session.delete(existing)
```

Add `from sqlalchemy import select` to `seed.py` imports.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_seed_baselines.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/seed.py src/clipscore/config.py tests/test_seed_baselines.py
git commit -m "feat: re-seed niche_baselines to real categories + raw_retention_days config"
```

---

## Task 2: Pure scoring primitives

**Files:**
- Create: `src/clipscore/scoring/__init__.py` (empty)
- Create: `src/clipscore/scoring/formula.py`
- Test: `tests/test_formula.py`

**Interfaces:**
- Produces (all pure, no DB): `net_cpm(cpm_usd, fee_pct)`, `raw_earnings(net_cpm_val, e_views)`, `capped_earnings(raw, cap_per_post_usd, cap_provenance, default_cap)`, `sat_factor(budget_remaining_now, active_clippers)`, `ev_per_clip(capped, p_threshold, p_approval, p_payout, budget_health, sat)`, `cvs_raw(ev, hours_per_clip)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_formula.py
import pytest
from clipscore.scoring import formula as f

def test_net_cpm():
    assert f.net_cpm(2.0, 0.10) == pytest.approx(1.8)

def test_raw_earnings():
    assert f.raw_earnings(1.8, 8000) == pytest.approx(14.4)

def test_capped_earnings_observed():
    assert f.capped_earnings(100.0, 30.0, "observed", 500.0) == 30.0

def test_capped_earnings_observed_below_cap():
    assert f.capped_earnings(20.0, 30.0, "observed", 500.0) == 20.0

def test_capped_earnings_absent_uses_default_cap():
    assert f.capped_earnings(900.0, None, "absent", 500.0) == 500.0

def test_capped_earnings_observed_but_null_cap_falls_back_to_default():
    # provenance says observed but the value is missing -> conservative default
    assert f.capped_earnings(900.0, None, "observed", 500.0) == 500.0

def test_sat_factor_normal():
    assert f.sat_factor(1000.0, 10) == pytest.approx(0.5)   # 100/200

def test_sat_factor_caps_at_one():
    assert f.sat_factor(100000.0, 1) == 1.0

def test_sat_factor_missing_clippers():
    assert f.sat_factor(1000.0, None) == 0.8

def test_sat_factor_missing_remaining():
    assert f.sat_factor(None, 10) == 0.8

def test_sat_factor_zero_clippers_no_div0():
    assert f.sat_factor(200.0, 0) == pytest.approx(1.0)     # max(0,1)=1 -> 200/200

def test_ev_per_clip_product():
    assert f.ev_per_clip(30.0, 0.55, 0.7, 0.8, 1.0, 0.5) == pytest.approx(30*0.55*0.7*0.8*1.0*0.5)

def test_cvs_raw():
    assert f.cvs_raw(9.24, 0.75) == pytest.approx(12.32)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_formula.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# src/clipscore/scoring/formula.py
"""Pure scoring primitives (no DB, no I/O). Verbatim from IMPLEMENTATION_PLAN.md
lines 185-219. Provenance: net_cpm/sat_factor are OBSERVED-driven; the p_* factors
and e_views are GUESSED constants (see engine.py)."""


def net_cpm(cpm_usd: float, fee_pct: float) -> float:
    return cpm_usd * (1 - fee_pct)


def raw_earnings(net_cpm_val: float, e_views: float) -> float:
    return net_cpm_val * (e_views / 1000)


def capped_earnings(raw: float, cap_per_post_usd, cap_provenance: str, default_cap: float) -> float:
    # unknown cap != uncapped: absent (or observed-but-missing) -> conservative default
    if cap_provenance == "observed" and cap_per_post_usd is not None:
        return min(raw, cap_per_post_usd)
    return min(raw, default_cap)


def sat_factor(budget_remaining_now, active_clippers) -> float:
    if budget_remaining_now is None or active_clippers is None:
        return 0.8
    saturation = budget_remaining_now / max(active_clippers, 1)
    return min(1.0, saturation / 200)


def ev_per_clip(capped: float, p_threshold: float, p_approval: float,
                p_payout: float, budget_health: float, sat: float) -> float:
    return capped * p_threshold * p_approval * p_payout * budget_health * sat


def cvs_raw(ev: float, hours_per_clip: float) -> float:
    return ev / hours_per_clip
```

Create empty `src/clipscore/scoring/__init__.py`.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_formula.py -v`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/scoring/__init__.py src/clipscore/scoring/formula.py tests/test_formula.py
git commit -m "feat: pure scoring primitives (net_cpm, capped_earnings, sat_factor, ev_per_clip)"
```

---

## Task 3: Epoch-aware budget_health from snapshot series

**Files:**
- Create: `src/clipscore/scoring/budget.py`
- Test: `tests/test_budget_health.py`

**Interfaces:**
- Produces: `budget_health(snapshots, now_iso, neutral=0.7) -> float`. `snapshots` is any iterable of objects with `.epoch: int`, `.budget_remaining_usd: float | None`, `.captured_at: str` (ISO `%Y-%m-%dT%H:%M:%SZ`). Uses only the latest snapshot's epoch. Latest = max by `captured_at` (ties broken arbitrarily; one snapshot per poll per campaign).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_budget_health.py
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from clipscore.scoring.budget import budget_health

def iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)
NOW_ISO = iso(NOW)

@dataclass
class Snap:
    epoch: int
    budget_remaining_usd: float | None
    captured_at: str

def test_none_snapshots_neutral():
    assert budget_health([], NOW_ISO) == 0.7

def test_single_snapshot_neutral():
    assert budget_health([Snap(0, 500.0, iso(NOW))], NOW_ISO) == 0.7

def test_no_snapshot_at_least_48h_old_neutral():
    # two snapshots but both younger than 48h -> can't measure burn
    snaps = [Snap(0, 500.0, iso(NOW - timedelta(hours=10))),
             Snap(0, 450.0, iso(NOW))]
    assert budget_health(snaps, NOW_ISO) == 0.7

def test_healthy_burn():
    # remaining fell 700->500 over ~48h -> daily_burn=100/day, days_left=5 -> 5/7
    snaps = [Snap(0, 700.0, iso(NOW - timedelta(hours=48))),
             Snap(0, 500.0, iso(NOW))]
    assert budget_health(snaps, NOW_ISO) == round(5/7, 10) or abs(budget_health(snaps, NOW_ISO) - 5/7) < 1e-9

def test_days_left_caps_at_one():
    # tiny burn -> days_left huge -> capped 1.0
    snaps = [Snap(0, 1000.0, iso(NOW - timedelta(hours=48))),
             Snap(0, 998.0, iso(NOW))]
    assert budget_health(snaps, NOW_ISO) == 1.0

def test_zero_or_negative_burn_is_healthy():
    # remaining rose (topped up within same epoch, sub-threshold) -> burn<=0 -> 1.0
    snaps = [Snap(0, 400.0, iso(NOW - timedelta(hours=48))),
             Snap(0, 450.0, iso(NOW))]
    assert budget_health(snaps, NOW_ISO) == 1.0

def test_epoch_reset_not_crossed():
    # old snapshot is a PRIOR epoch (topped up -> epoch bumped). Current epoch has
    # only 1 snapshot -> neutral, must NOT reach across the reset to compute burn.
    snaps = [Snap(0, 300.0, iso(NOW - timedelta(hours=48))),   # prior epoch
             Snap(1, 1000.0, iso(NOW))]                        # current epoch
    assert budget_health(snaps, NOW_ISO) == 0.7

def test_picks_snapshot_closest_to_48h():
    # current epoch has three ≥48h-old rows plus now; the one CLOSEST to now-48h
    # (the 49h row, remaining 600) must be chosen, not the oldest (72h, 900).
    snaps = [Snap(0, 900.0, iso(NOW - timedelta(hours=72))),
             Snap(0, 600.0, iso(NOW - timedelta(hours=49))),
             Snap(0, 400.0, iso(NOW))]
    # burn=(600-400)/2=100/day, days_left=4 -> 4/7
    assert abs(budget_health(snaps, NOW_ISO) - 4/7) < 1e-9

def test_missing_remaining_neutral():
    snaps = [Snap(0, None, iso(NOW - timedelta(hours=48))),
             Snap(0, 500.0, iso(NOW))]
    assert budget_health(snaps, NOW_ISO) == 0.7
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_budget_health.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# src/clipscore/scoring/budget.py
"""budget_health from a campaign's snapshot series (IMPLEMENTATION_PLAN.md:204-208).
OBSERVED signal. Uses ONLY the latest snapshot's epoch so a budget top-up (which
bumps the epoch at ingest) never lets burn be measured across the reset."""
from datetime import datetime, timedelta


def _parse(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")


def budget_health(snapshots, now_iso: str, neutral: float = 0.7) -> float:
    snaps = list(snapshots)
    if not snaps:
        return neutral
    latest = max(snaps, key=lambda s: s.captured_at)
    epoch = latest.epoch
    in_epoch = [s for s in snaps if s.epoch == epoch]
    if len(in_epoch) < 2:
        return neutral
    now = _parse(now_iso)
    cutoff = now - timedelta(hours=48)
    older = [s for s in in_epoch if _parse(s.captured_at) <= cutoff]
    if not older:
        return neutral
    then = max(older, key=lambda s: s.captured_at)   # closest to now-48h from below
    r_then, r_now = then.budget_remaining_usd, latest.budget_remaining_usd
    if r_then is None or r_now is None:
        return neutral
    daily_burn = (r_then - r_now) / 2.0
    if daily_burn <= 0:
        return 1.0
    days_left = r_now / daily_burn
    return min(1.0, days_left / 7)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_budget_health.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/scoring/budget.py tests/test_budget_health.py
git commit -m "feat: epoch-aware budget_health from snapshot series"
```

---

## Task 4: Within-niche percentile (empirical CDF)

**Files:**
- Create: `src/clipscore/scoring/percentile.py`
- Test: `tests/test_percentile.py`

**Interfaces:**
- Produces: `empirical_cdf(value: float, population: list[float]) -> float` — returns `count(x <= value) / len(population)`; assumes `value` is a member of `population`; `len == 1` → `1.0`. Ties get identical values.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_percentile.py
import pytest
from clipscore.scoring.percentile import empirical_cdf

def test_single_element_is_top():
    assert empirical_cdf(5.0, [5.0]) == 1.0

def test_max_is_one():
    assert empirical_cdf(9.0, [1.0, 5.0, 9.0]) == 1.0

def test_min_is_fraction_not_zero():
    assert empirical_cdf(1.0, [1.0, 5.0, 9.0]) == pytest.approx(1/3)

def test_middle():
    assert empirical_cdf(5.0, [1.0, 5.0, 9.0]) == pytest.approx(2/3)

def test_ties_equal():
    pop = [1.0, 5.0, 5.0, 9.0]
    assert empirical_cdf(5.0, pop) == pytest.approx(3/4)   # both 5.0s get 3/4
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_percentile.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# src/clipscore/scoring/percentile.py
"""Within-niche rank as an empirical CDF (IMPLEMENTATION_PLAN.md:167). The primary
user-facing signal. Population = the campaign's niche's valid scored campaigns."""


def empirical_cdf(value: float, population: list[float]) -> float:
    n = len(population)
    if n == 0:
        raise ValueError("empty population")
    return sum(1 for x in population if x <= value) / n
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_percentile.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/scoring/percentile.py tests/test_percentile.py
git commit -m "feat: within-niche percentile (empirical CDF)"
```

---

## Task 5: Scoring engine (DB orchestration)

**Files:**
- Create: `src/clipscore/scoring/engine.py`
- Test: `tests/test_scoring_engine.py`

**Interfaces:**
- Consumes: `formula`, `budget`, `percentile`; `Campaign`, `CampaignSnapshot`, `CampaignScore`, `NicheBaseline`, `PlatformTrust`; `get_settings()`; `utcnow_iso()`.
- Produces: `score_all(session, now_iso: str | None = None) -> dict` — scores the eligible population, writes one `CampaignScore` row per scored campaign, returns `{"scored": int, "skipped_ugc": int, "skipped_walled": int, "zero_cpm": int}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scoring_engine.py
import pytest
from sqlalchemy import select
from clipscore.db.models import (Campaign, CampaignSnapshot, CampaignScore,
                                 NicheBaseline, PlatformTrust)
from clipscore.scoring.engine import score_all
from clipscore.time import utcnow_iso

def _seed_refs(session):
    session.add(PlatformTrust(source="contentrewards", trust_score=0.8, default_fee_pct=0.10))
    for n in ("gaming", "other"):
        session.add(NicheBaseline(niche=n, e_views_median=8000, p_threshold=0.55))
    session.commit()

def _campaign(session, ext, **kw):
    now = utcnow_iso()
    defaults = dict(id=ext, source="contentrewards", external_id=ext,
                    niche="gaming", cpm_usd=2.0, cap_provenance="absent",
                    campaign_type="clipping", status="active",
                    access_status="ingestable", first_seen_at=now, last_seen_at=now)
    defaults.update(kw)
    c = Campaign(**defaults)
    session.add(c); session.commit()
    return c

def _snap(session, cid, remaining, clippers=10, epoch=0, captured_at=None):
    session.add(CampaignSnapshot(campaign_id=cid, epoch=epoch,
                budget_remaining_usd=remaining, active_clippers=clippers,
                captured_at=captured_at or utcnow_iso()))
    session.commit()

def test_scores_active_ingestable_campaign(session):
    _seed_refs(session)
    _campaign(session, "a"); _snap(session, "a", 500.0)
    res = score_all(session)
    assert res["scored"] == 1
    row = session.execute(select(CampaignScore)).scalars().one()
    assert row.campaign_id == "a"
    assert row.net_cpm == pytest.approx(1.8)         # 2.0*(1-0.10)
    assert row.p_payout == pytest.approx(0.8)         # platform trust
    assert row.p_approval == pytest.approx(0.7)       # guessed default
    assert row.budget_health == pytest.approx(0.7)    # <2 snapshots -> neutral
    assert row.cvs_niche_percentile == pytest.approx(1.0)   # only campaign in niche

def test_ugc_skipped(session):
    _seed_refs(session)
    _campaign(session, "u", campaign_type="ugc"); _snap(session, "u", 500.0)
    res = score_all(session)
    assert res["scored"] == 0 and res["skipped_ugc"] == 1
    assert session.execute(select(CampaignScore)).scalars().first() is None

def test_walled_skipped(session):
    _seed_refs(session)
    _campaign(session, "w", access_status="tos_restricted"); _snap(session, "w", 500.0)
    res = score_all(session)
    assert res["scored"] == 0 and res["skipped_walled"] == 1

def test_ended_not_scored(session):
    _seed_refs(session)
    _campaign(session, "e", status="ended"); _snap(session, "e", 500.0)
    assert score_all(session)["scored"] == 0

def test_zero_cpm_flagged_and_excluded_from_percentile(session):
    _seed_refs(session)
    _campaign(session, "z", cpm_usd=0.0); _snap(session, "z", 500.0)
    _campaign(session, "g", cpm_usd=2.0); _snap(session, "g", 500.0)
    res = score_all(session)
    assert res["scored"] == 2 and res["zero_cpm"] == 1
    rows = {r.campaign_id: r for r in session.execute(select(CampaignScore)).scalars()}
    assert rows["z"].cvs_raw == 0.0
    assert rows["z"].cvs_niche_percentile is None      # excluded from population
    assert rows["g"].cvs_niche_percentile == pytest.approx(1.0)  # sole valid in niche

def test_missing_cpm_flagged(session):
    _seed_refs(session)
    _campaign(session, "m", cpm_usd=None); _snap(session, "m", 500.0)
    res = score_all(session)
    assert res["zero_cpm"] == 1
    row = session.execute(select(CampaignScore)).scalars().one()
    assert row.cvs_raw == 0.0 and row.cvs_niche_percentile is None

def test_null_niche_uses_other_baseline(session):
    _seed_refs(session)
    _campaign(session, "n", niche=None); _snap(session, "n", 500.0)
    assert score_all(session)["scored"] == 1   # resolves to "other" baseline, no crash

def test_unknown_niche_falls_back_to_other(session):
    _seed_refs(session)
    _campaign(session, "x", niche="nonexistent"); _snap(session, "x", 500.0)
    assert score_all(session)["scored"] == 1

def test_percentile_within_niche(session):
    _seed_refs(session)
    # two gaming campaigns, different remaining -> different sat_factor -> different cvs
    _campaign(session, "lo", cpm_usd=2.0); _snap(session, "lo", 100.0, clippers=50)
    _campaign(session, "hi", cpm_usd=2.0); _snap(session, "hi", 5000.0, clippers=1)
    score_all(session)
    rows = {r.campaign_id: r for r in session.execute(select(CampaignScore)).scalars()}
    assert rows["hi"].cvs_raw > rows["lo"].cvs_raw
    assert rows["hi"].cvs_niche_percentile == pytest.approx(1.0)
    assert rows["lo"].cvs_niche_percentile == pytest.approx(0.5)

def test_components_persisted(session):
    _seed_refs(session)
    _campaign(session, "c"); _snap(session, "c", 500.0)
    score_all(session)
    r = session.execute(select(CampaignScore)).scalars().one()
    for col in ("net_cpm", "capped_earnings", "p_threshold", "p_approval",
                "p_payout", "budget_health", "sat_factor", "ev_per_clip", "cvs_raw"):
        assert getattr(r, col) is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_scoring_engine.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# src/clipscore/scoring/engine.py
"""Scoring engine: gather DB inputs, run the pure formula, write campaign_scores.
Scored population = active + ingestable + not-UGC. Cross-niche placement is NOT
trustworthy in v1; cvs_niche_percentile (within-niche) is the user-facing signal."""
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session
from clipscore.config import get_settings
from clipscore.time import utcnow_iso
from clipscore.db.models import (Campaign, CampaignSnapshot, CampaignScore,
                                 NicheBaseline, PlatformTrust)
from clipscore.scoring import formula
from clipscore.scoring.budget import budget_health
from clipscore.scoring.percentile import empirical_cdf

log = structlog.get_logger()


def _snapshots_for(session: Session, campaign_id: str) -> list[CampaignSnapshot]:
    return session.execute(
        select(CampaignSnapshot).where(CampaignSnapshot.campaign_id == campaign_id)
    ).scalars().all()


def _baseline(baselines: dict, niche) -> NicheBaseline:
    key = niche or "other"
    return baselines.get(key) or baselines["other"]


def score_all(session: Session, now_iso: str | None = None) -> dict:
    now_iso = now_iso or utcnow_iso()
    settings = get_settings()

    campaigns = session.execute(
        select(Campaign).where(Campaign.source == "contentrewards")
    ).scalars().all()

    baselines = {b.niche: b for b in session.execute(select(NicheBaseline)).scalars().all()}
    trust = {t.source: t for t in session.execute(select(PlatformTrust)).scalars().all()}

    res = {"scored": 0, "skipped_ugc": 0, "skipped_walled": 0, "zero_cpm": 0}
    # collect (record, niche_key, cvs_or_None) so we can compute percentiles after
    pending = []
    for c in campaigns:
        if c.status != "active":
            continue
        if c.access_status != "ingestable":
            res["skipped_walled"] += 1
            continue
        if c.campaign_type == "ugc":
            res["skipped_ugc"] += 1
            continue

        pt = trust.get(c.source)
        fee = pt.default_fee_pct if pt else 0.0
        p_payout = pt.trust_score if pt else 0.0
        base = _baseline(baselines, c.niche)
        niche_key = c.niche or "other"

        snaps = _snapshots_for(session, c.id)
        latest = max(snaps, key=lambda s: s.captured_at) if snaps else None
        remaining_now = latest.budget_remaining_usd if latest else None
        clippers_now = latest.active_clippers if latest else None

        if c.cpm_usd is None or c.cpm_usd <= 0:
            log.warning("zero_or_missing_cpm", campaign_id=c.id, cpm=c.cpm_usd)
            res["zero_cpm"] += 1
            rec = dict(campaign_id=c.id, net_cpm=0.0, capped_earnings=0.0,
                       p_threshold=base.p_threshold, p_approval=settings.default_p_approval,
                       p_payout=p_payout, budget_health=0.0, sat_factor=0.0,
                       ev_per_clip=0.0, cvs_raw=0.0)
            pending.append((rec, niche_key, None))   # None -> excluded from percentile
            res["scored"] += 1
            continue

        ncpm = formula.net_cpm(c.cpm_usd, fee)
        raw = formula.raw_earnings(ncpm, base.e_views_median)
        capped = formula.capped_earnings(raw, c.cap_per_post_usd, c.cap_provenance,
                                         settings.default_assumed_cap_usd)
        bh = budget_health(snaps, now_iso)
        sat = formula.sat_factor(remaining_now, clippers_now)
        ev = formula.ev_per_clip(capped, base.p_threshold, settings.default_p_approval,
                                 p_payout, bh, sat)
        cvs = formula.cvs_raw(ev, settings.hours_per_clip)
        rec = dict(campaign_id=c.id, net_cpm=ncpm, capped_earnings=capped,
                   p_threshold=base.p_threshold, p_approval=settings.default_p_approval,
                   p_payout=p_payout, budget_health=bh, sat_factor=sat,
                   ev_per_clip=ev, cvs_raw=cvs)
        pending.append((rec, niche_key, cvs))
        res["scored"] += 1

    # percentile population per niche = valid (non-excluded) cvs only
    pops: dict[str, list[float]] = {}
    for _, niche_key, cvs in pending:
        if cvs is not None:
            pops.setdefault(niche_key, []).append(cvs)

    for rec, niche_key, cvs in pending:
        pct = empirical_cdf(cvs, pops[niche_key]) if cvs is not None else None
        session.add(CampaignScore(scored_at=now_iso, cvs_niche_percentile=pct, **rec))
    session.commit()
    return res
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_scoring_engine.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/scoring/engine.py tests/test_scoring_engine.py
git commit -m "feat: scoring engine writes campaign_scores with within-niche percentile"
```

---

## Task 6: Wire scoring into the poll cycle

**Files:**
- Modify: `src/clipscore/jobs/poll.py`
- Test: `tests/test_poll_scoring.py`

**Interfaces:**
- Consumes: `run_ingest_batch` result dict (`status`), `score_all`.
- Produces: `run_once(session)` runs `score_all` **only when** the ingest result `status == "ok"`; returns the ingest result dict augmented with `"scored"` (int) when scoring ran, else unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_poll_scoring.py
from unittest.mock import patch
from clipscore.jobs.poll import run_once

def test_scoring_runs_on_ok(session):
    with patch("clipscore.jobs.poll.run_ingest_batch", return_value={"status": "ok", "count": 500}), \
         patch("clipscore.jobs.poll.score_all", return_value={"scored": 42}) as m:
        res = run_once(session)
    m.assert_called_once()
    assert res["scored"] == 42

def test_scoring_skipped_on_halted(session):
    with patch("clipscore.jobs.poll.run_ingest_batch", return_value={"status": "halted"}), \
         patch("clipscore.jobs.poll.score_all") as m:
        res = run_once(session)
    m.assert_not_called()
    assert res["status"] == "halted" and "scored" not in res

def test_scoring_skipped_on_harvest_too_small(session):
    with patch("clipscore.jobs.poll.run_ingest_batch", return_value={"status": "harvest_too_small", "count": 3}), \
         patch("clipscore.jobs.poll.score_all") as m:
        run_once(session)
    m.assert_not_called()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_poll_scoring.py -v`
Expected: FAIL (no `score_all` import in poll; scoring not wired).

- [ ] **Step 3: Implement**

In `src/clipscore/jobs/poll.py`, add the import and gate scoring on `status == "ok"`:

```python
from clipscore.scoring.engine import score_all
```

Replace `run_once`:

```python
def run_once(session) -> dict:
    result = run_ingest_batch(session, ContentrewardsIngester(), miss_counts=_MISS_COUNTS)
    log.info("ingest_batch", **result)
    if result.get("status") == "ok":
        score_result = score_all(session)
        log.info("scoring", **score_result)
        result["scored"] = score_result["scored"]
    return result
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_poll_scoring.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/jobs/poll.py tests/test_poll_scoring.py
git commit -m "feat: run scoring after each successful ingest cycle"
```

---

## Task 7: Snapshot retention/rollup job

**Files:**
- Create: `src/clipscore/jobs/retention.py`
- Test: `tests/test_retention.py`

**Interfaces:**
- Produces: `rollup_snapshots(session, now_iso: str | None = None) -> dict` — for snapshots **older than `raw_retention_days`**, keep at most one per `(campaign_id, hour-bucket)` (the latest in each bucket by `id`), delete the rest. Snapshots within the retention window are never touched. Returns `{"deleted": int, "kept": int}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_retention.py
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from clipscore.db.models import CampaignSnapshot
from clipscore.jobs.retention import rollup_snapshots

def iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)

def _snap(session, cid, dt):
    s = CampaignSnapshot(campaign_id=cid, epoch=0, budget_remaining_usd=100.0,
                         captured_at=iso(dt))
    session.add(s); session.commit(); return s

def test_recent_snapshots_untouched(session):
    # three snapshots within the same hour but < 14 days old -> all kept
    for m in (0, 20, 40):
        _snap(session, "a", NOW - timedelta(days=1, minutes=m))
    res = rollup_snapshots(session, iso(NOW))
    assert res["deleted"] == 0
    assert len(session.execute(select(CampaignSnapshot)).scalars().all()) == 3

def test_old_same_hour_rolled_up_to_one(session):
    old = NOW - timedelta(days=20)
    for m in (0, 20, 40):
        _snap(session, "a", old + timedelta(minutes=m))
    res = rollup_snapshots(session, iso(NOW))
    assert res["deleted"] == 2
    remaining = session.execute(select(CampaignSnapshot)).scalars().all()
    assert len(remaining) == 1

def test_old_different_hours_all_kept(session):
    old = NOW - timedelta(days=20)
    for h in (0, 1, 2):
        _snap(session, "a", old + timedelta(hours=h))
    res = rollup_snapshots(session, iso(NOW))
    assert res["deleted"] == 0

def test_per_campaign_isolation(session):
    old = NOW - timedelta(days=20)
    for m in (0, 30):
        _snap(session, "a", old + timedelta(minutes=m))
        _snap(session, "b", old + timedelta(minutes=m))
    rollup_snapshots(session, iso(NOW))
    a = session.execute(select(CampaignSnapshot).where(CampaignSnapshot.campaign_id == "a")).scalars().all()
    b = session.execute(select(CampaignSnapshot).where(CampaignSnapshot.campaign_id == "b")).scalars().all()
    assert len(a) == 1 and len(b) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_retention.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# src/clipscore/jobs/retention.py
"""Snapshot retention: raw within raw_retention_days, hourly rollup beyond.
Only ever touches snapshots older than the window, so it can never affect the
48h budget-health burn window or the latest-per-epoch rows scoring reads."""
import structlog
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from clipscore.config import get_settings
from clipscore.time import utcnow_iso
from clipscore.db.models import CampaignSnapshot

log = structlog.get_logger()


def _parse(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")


def rollup_snapshots(session: Session, now_iso: str | None = None) -> dict:
    now = _parse(now_iso or utcnow_iso())
    cutoff = now - timedelta(days=get_settings().raw_retention_days)
    rows = session.execute(select(CampaignSnapshot)).scalars().all()
    # bucket old rows by (campaign_id, hour); keep max id per bucket
    buckets: dict[tuple, list[CampaignSnapshot]] = {}
    kept = 0
    for s in rows:
        if _parse(s.captured_at) >= cutoff:
            kept += 1
            continue
        key = (s.campaign_id, s.captured_at[:13])   # "YYYY-MM-DDTHH"
        buckets.setdefault(key, []).append(s)
    deleted = 0
    for group in buckets.values():
        group.sort(key=lambda s: s.id)
        for stale in group[:-1]:      # keep the last (max id) in the bucket
            session.delete(stale)
            deleted += 1
        kept += 1
    session.commit()
    log.info("snapshot_rollup", deleted=deleted, kept=kept)
    return {"deleted": deleted, "kept": kept}
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_retention.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/jobs/retention.py tests/test_retention.py
git commit -m "feat: snapshot retention/rollup job (raw 14d, hourly beyond)"
```

---

## Task 8: Ranked CLI board

**Files:**
- Create: `src/clipscore/jobs/rank.py`
- Test: `tests/test_rank_cli.py`

**Interfaces:**
- Produces:
  - `ranked_rows(session, top: int | None = None, niche: str | None = None) -> list[dict]` — one row per campaign using its **latest** score (max `CampaignScore.id` per `campaign_id`), joined to the campaign for `title`/`niche`/`cpm_usd`. Sorted by `cvs_niche_percentile` descending (rows with `None` percentile sort last). Optional `niche` filter (matched against `campaign.niche or "other"`); optional `top` limit.
  - `format_table(rows: list[dict]) -> str` — fixed-width text table; the output MUST contain the literal caveat `estimated screening signal, not a payout prediction` and MUST show the percentile column; MUST NOT label `cvs_raw` as `$/hr`.
  - `main(argv=None)` — argparse entrypoint for `python -m clipscore.jobs.rank --top N [--niche X]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rank_cli.py
import pytest
from clipscore.db.models import Campaign, CampaignScore
from clipscore.jobs.rank import ranked_rows, format_table
from clipscore.time import utcnow_iso

def _camp(session, cid, niche="gaming", cpm=2.0):
    now = utcnow_iso()
    session.add(Campaign(id=cid, source="contentrewards", external_id=cid, niche=niche,
                cpm_usd=cpm, cap_provenance="absent", status="active",
                access_status="ingestable", first_seen_at=now, last_seen_at=now))
    session.commit()

def _score(session, cid, cvs, pct, scored_at):
    session.add(CampaignScore(campaign_id=cid, scored_at=scored_at, cvs_raw=cvs,
                cvs_niche_percentile=pct, net_cpm=1.8, budget_health=0.7, sat_factor=0.8))
    session.commit()

def test_uses_latest_score_only(session):
    _camp(session, "a")
    _score(session, "a", 1.0, 0.2, "2026-07-10T00:00:00Z")
    _score(session, "a", 9.0, 0.9, "2026-07-13T00:00:00Z")   # latest
    rows = ranked_rows(session)
    assert len(rows) == 1 and rows[0]["cvs_raw"] == 9.0 and rows[0]["cvs_niche_percentile"] == 0.9

def test_sorted_by_percentile_desc(session):
    _camp(session, "a"); _camp(session, "b")
    _score(session, "a", 1.0, 0.3, "2026-07-13T00:00:00Z")
    _score(session, "b", 5.0, 0.8, "2026-07-13T00:00:00Z")
    rows = ranked_rows(session)
    assert [r["campaign_id"] for r in rows] == ["b", "a"]

def test_top_limit(session):
    for i in range(5):
        _camp(session, f"c{i}"); _score(session, f"c{i}", float(i), i/4, "2026-07-13T00:00:00Z")
    assert len(ranked_rows(session, top=2)) == 2

def test_niche_filter(session):
    _camp(session, "g", niche="gaming"); _camp(session, "m", niche="music")
    _score(session, "g", 1.0, 0.5, "2026-07-13T00:00:00Z")
    _score(session, "m", 2.0, 0.5, "2026-07-13T00:00:00Z")
    rows = ranked_rows(session, niche="music")
    assert [r["campaign_id"] for r in rows] == ["m"]

def test_format_table_carries_caveat(session):
    _camp(session, "a"); _score(session, "a", 9.0, 0.9, "2026-07-13T00:00:00Z")
    out = format_table(ranked_rows(session))
    assert "estimated screening signal, not a payout prediction" in out
    assert "$/hr" not in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_rank_cli.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# src/clipscore/jobs/rank.py
"""CLI: python -m clipscore.jobs.rank --top N [--niche X]
Within-niche screening board. cvs_niche_percentile is the signal; cvs_raw is an
internal scalar shown for debugging, NEVER a $/hr promise."""
import argparse
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from clipscore.db.models import Campaign, CampaignScore
from clipscore.db.session import get_engine, SessionLocal

CAVEAT = "estimated screening signal, not a payout prediction"


def ranked_rows(session: Session, top: int | None = None, niche: str | None = None) -> list[dict]:
    # latest score per campaign = max(id) per campaign_id
    latest_ids = select(func.max(CampaignScore.id)).group_by(CampaignScore.campaign_id)
    scores = session.execute(
        select(CampaignScore).where(CampaignScore.id.in_(latest_ids))
    ).scalars().all()
    camps = {c.id: c for c in session.execute(select(Campaign)).scalars().all()}
    rows = []
    for s in scores:
        c = camps.get(s.campaign_id)
        if c is None:
            continue
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


def _fmt(v, spec="{:.3f}"):
    return "-" if v is None else spec.format(v)


def format_table(rows: list[dict]) -> str:
    header = f"{'#':>3}  {'niche':<16} {'title':<28} {'cpm':>6} {'net':>6} " \
             f"{'bhlth':>6} {'sat':>6} {'cvs_raw':>8} {'pctile':>7}"
    lines = [f"Campaign screening board — {CAVEAT}.", "", header, "-" * len(header)]
    for i, r in enumerate(rows, 1):
        title = (r["title"] or "")[:28]
        lines.append(
            f"{i:>3}  {r['niche']:<16} {title:<28} "
            f"{_fmt(r['cpm_usd'], '{:.2f}'):>6} {_fmt(r['net_cpm'], '{:.2f}'):>6} "
            f"{_fmt(r['budget_health'], '{:.2f}'):>6} {_fmt(r['sat_factor'], '{:.2f}'):>6} "
            f"{_fmt(r['cvs_raw']):>8} {_fmt(r['cvs_niche_percentile'], '{:.2f}'):>7}"
        )
    if not rows:
        lines.append("(no scored campaigns)")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="clipscore.jobs.rank")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--niche", type=str, default=None)
    args = ap.parse_args(argv)
    get_engine()
    with SessionLocal() as session:
        print(format_table(ranked_rows(session, top=args.top, niche=args.niche)))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_rank_cli.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/jobs/rank.py tests/test_rank_cli.py
git commit -m "feat: ranked CLI board (within-niche percentile, honest-scoring caveat)"
```

---

## Verification

- **Unit (CI, no network):** `pytest -q` green — all Stage-1/2 tests still pass plus the new suites (formula, budget_health, percentile, engine, poll-scoring, retention, rank CLI, seed).
- **Cold-start expectation (documented):** for the first ~48h a campaign has `<2` in-epoch snapshots, so `budget_health` falls back to `0.7` and `sat_factor` to `0.8` when data is thin — early rankings are low-signal. This is expected, not a bug.
- **Manual live smoke (needs network, not CI):** after two live poll cycles, `python -m clipscore.jobs.rank --top 10` prints a within-niche board; `--niche gaming` filters; every board carries the caveat; `cvs_raw` is never labeled $/hr.

## Out of scope (later stages)

- ETag/304 conditional-GET activation (Stage-2 deferred — its own task).
- Discord bot, `ALERT_PERCENTILE`, `MIN_NICHE_SAMPLE`, daily summary (Phase 4).
- Feedback loop / `outcomes` population; wiring `successRate` into `p_approval` (Phase 5, pending validation).
- Wiring `rollup_snapshots` into APScheduler (add alongside the Phase-4 scheduler work).
