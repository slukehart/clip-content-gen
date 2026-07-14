# Pipeline A — Stage 2: contentrewards.com Ingester — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the public `contentrewards.com/discover` page into `campaigns` + `campaign_snapshots` rows via a compliant, challenge-aware ingester built on the Stage 1 framework.

**Architecture:** Small single-responsibility modules under `src/clipscore/ingest/` (coercion, RSC parsing, challenge detection, requirements extraction, fetch-event logging) composed by a `ContentrewardsIngester(BaseIngester)` and driven by an APScheduler poll job. All heavy decode logic is in pure, fixture-tested functions; the ingester wires them to httpx. DB writes stay in the Stage 1 `upsert.py` orchestrator, extended for halts and malformed entries.

**Tech Stack:** Python 3.11+ · httpx · SQLAlchemy 2.x · Alembic · APScheduler · pydantic-settings · pytest (+ `httpx.MockTransport`).

## Global Constraints

- **SQLite storage conventions** (verbatim from `IMPLEMENTATION_PLAN.md`): money → REAL/`float`; counts → INTEGER; large counts (views) → BigInteger; arrays → JSON TEXT; timestamps → UTC ISO-8601 `YYYY-MM-DDTHH:MM:SSZ` via `clipscore.time.utcnow_iso()`; booleans → `Boolean`.
- **Dedup key = source campaign `id` (UUID)** → `CampaignUpsert.external_id`. `whopExperienceId` is shared (305/502 distinct) and goes to the separate nullable `whop_experience_id`. Source `id` must **not** be written to `campaigns.id` (that is an app-generated UUID PK set by `upsert_campaign`).
- **Drop, don't evade.** Any challenge/block (403/429/CAPTCHA/Cloudflare/DataDome/login-redirect/robots-disallow) → log a `fetch_events` row with the exact URL + marker, halt the source, flip its campaigns' `access_status`. Never solve challenges, rotate identity, use proxies, or force retries. No Playwright for this source (`enable_playwright` stays off).
- **Harvest sanity gate** (Stage 1, keep): a poll yielding `< harvest_min_campaigns` (default 50; ~502 normal) is a parse/fetch failure — do not write authoritative state, do **not** run the ended-sweep.
- **niche = source `category` verbatim, slugified** (e.g. `"Personal Brand"` → `"personal brand"` lowercased). No mapping to a curated enum in v1.
- **`campaign_type` kept, not filtered** at ingest; downstream stages filter.
- **`stats.successRate`/`engagement` captured raw** into the snapshot; their meaning is a Stage 3 decision (see `docs/spikes/2026-07-13-phase-0-stable-key-spike.md`). Do not wire `successRate` into scoring here.
- Money on the wire is a display string (`"$1.50"`, `"$250,000"`); `stats.viewCount` is an abbreviated string (`"51.4M"`). Coerce via `ingest/coerce.py`.
- `get_settings()` is `@lru_cache`d — any test that sets env or `.env` must call `get_settings.cache_clear()` in setup/teardown.
- Tests import via `pythonpath=["src"]`; DB tests use the `session` fixture in `tests/conftest.py`. **New tests that need a specific `Settings` must not rely on a real `.env`.**

## Prerequisites already in the repo (from the Phase 0 spike, do not redo)

- `docs/spikes/2026-07-13-phase-0-stable-key-spike.md` — findings (read for field reality).
- `tests/fixtures/contentrewards/discover_golden.html` — 5 real campaigns nested under the real `initialData.bannerCampaigns` key, in exact RSC wire format (`self.__next_f.push`, `$$`-escape, `\"`-escape), **with a 6th entry duplicating campaign 0** so `parse_discover` dedup is exercised. Campaign ids in the fixture (for test assertions):
  - `dd9f7918-e51d-4935-9f23-5935c783774a` — active, all optionals present, `pricePerView` `"$1.50"`, category `Entertainment`, `campaignType` `clipping`.
  - `5d5933f0-b869-466c-909c-05715db13c09` — missing `category`, `whopProductRoute`, `description`; has `programId`.
  - `09a289b7-900f-4daf-bd46-a636dd6a731f` — missing `whopProductRoute`; `pricePerView` `"$8.00"`.
  - `b82221fa-1e7a-4d88-ad84-2a286771c118` — missing `description`; `pricePerView` `"$0.15"`.
  - `6b7db90d-412f-4bcc-ab1e-619ab73bfa09` — `status` `"completed"`.

---

## Task 1: Config settings + `campaign_type` column + migration 0002

**Files:**
- Modify: `src/clipscore/config.py`
- Modify: `src/clipscore/db/models.py`
- Modify: `src/clipscore/ingest/dto.py`
- Create: `alembic/versions/0002_add_campaign_type.py`
- Test: `tests/test_migration_0002.py`, `tests/test_config_source.py`

**Interfaces:**
- Produces: `Settings.source_base_url`, `.discover_path`, `.user_agent`, `.http_timeout_s`; `Campaign.campaign_type: Mapped[str|None]`; `CampaignUpsert.campaign_type: str|None = None`.

- [ ] **Step 1: Failing test — settings + column exist**

```python
# tests/test_config_source.py
from clipscore.config import Settings

def test_source_fetch_settings_defaults():
    s = Settings(_env_file=None)
    assert s.source_base_url == "https://contentrewards.com"
    assert s.discover_path == "/discover"
    assert s.http_timeout_s == 60
    assert "clipscore" in s.user_agent.lower()
```

```python
# tests/test_migration_0002.py
import sqlalchemy as sa
from alembic.config import Config
from alembic import command

def test_migration_adds_campaign_type(tmp_path):
    db = tmp_path / "m.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    command.upgrade(cfg, "head")
    eng = sa.create_engine(f"sqlite:///{db}")
    cols = {c["name"]: c for c in sa.inspect(eng).get_columns("campaigns")}
    assert "campaign_type" in cols
    assert cols["campaign_type"]["nullable"] is True
```

- [ ] **Step 2: Run to confirm fail** — `pytest tests/test_config_source.py tests/test_migration_0002.py -q` → FAIL (attr/column missing).

- [ ] **Step 3: Implement**

In `config.py` add to `Settings` (after `enable_playwright`):
```python
    source_base_url: str = "https://contentrewards.com"
    discover_path: str = "/discover"
    user_agent: str = "clipscore/0.1 (+personal research; contact via repo)"
    http_timeout_s: int = 60
```
In `db/models.py` `Campaign`, add after `title`:
```python
    campaign_type: Mapped[str | None] = mapped_column(String, nullable=True)
```
In `ingest/dto.py` `CampaignUpsert`, add field:
```python
    campaign_type: str | None = None
```
Create `alembic/versions/0002_add_campaign_type.py`:
```python
"""add campaign_type to campaigns"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("campaigns", sa.Column("campaign_type", sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column("campaigns", "campaign_type")
```
(Confirm `0001`'s `revision` string is `"0001"`; if it differs, set `down_revision` to match it.)

- [ ] **Step 4: Run** — both test files PASS; also `pytest -q` (full suite still green).
- [ ] **Step 5: Commit** — `git add src/clipscore/config.py src/clipscore/db/models.py src/clipscore/ingest/dto.py alembic/versions/0002_add_campaign_type.py tests/test_config_source.py tests/test_migration_0002.py && git commit -m "feat: add campaign_type column + source-fetch settings (migration 0002)"`

---

## Task 2: Coercion helpers (`coerce.py`)

**Files:** Create `src/clipscore/ingest/coerce.py`; Test `tests/test_coerce.py`

**Interfaces:**
- Produces: `money_to_float(s) -> float | None`, `views_to_int(s) -> int | None`, `to_int(v) -> int | None`, `to_float(v) -> float | None`.

- [ ] **Step 1: Failing test**

```python
# tests/test_coerce.py
import pytest
from clipscore.ingest.coerce import money_to_float, views_to_int, to_int, to_float

@pytest.mark.parametrize("s,expected", [
    ("$1.50", 1.5), ("$0.15", 0.15), ("$250,000", 250000.0),
    ("$86,690.35", 86690.35), ("0", 0.0), ("", None), (None, None), ("n/a", None),
])
def test_money_to_float(s, expected):
    assert money_to_float(s) == expected

@pytest.mark.parametrize("s,expected", [
    ("51.4M", 51_400_000), ("9.1M", 9_100_000), ("226.2K", 226_200),
    ("811.8K", 811_800), ("2.1B", 2_100_000_000), ("0", 0),
    ("1234", 1234), ("", None), (None, None),
])
def test_views_to_int(s, expected):
    assert views_to_int(s) == expected

def test_to_int_and_float():
    assert to_int(3728) == 3728 and to_int("5") == 5 and to_int(None) is None
    assert to_float("2.0") == 2.0 and to_float(None) is None
```

- [ ] **Step 2: Confirm fail.**
- [ ] **Step 3: Implement**

```python
# src/clipscore/ingest/coerce.py
"""Pure coercion for contentrewards' display-formatted values.
Money arrives as strings like "$250,000"; view counts as "51.4M"/"226.2K"."""
import re

_SUFFIX = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}

def money_to_float(s):
    if s is None:
        return None
    cleaned = str(s).replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None

def views_to_int(s):
    if s is None:
        return None
    t = str(s).replace(",", "").strip()
    if not t:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([KMB])?", t)
    if not m:
        return None
    num = float(m.group(1))
    if m.group(2):
        num *= _SUFFIX[m.group(2)]
    return int(round(num))

def to_int(v):
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None

def to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None
```

- [ ] **Step 4: Run PASS.**
- [ ] **Step 5: Commit** — `git add src/clipscore/ingest/coerce.py tests/test_coerce.py && git commit -m "feat: add display-value coercion helpers"`

---

## Task 3: RSC payload parser (`rsc.py`)

**Files:** Create `src/clipscore/ingest/rsc.py`; Test `tests/test_rsc_parse.py`

**Interfaces:**
- Produces: `parse_discover(html: str) -> list[dict]` — decoded, `$$`-unescaped, deduped-by-`id` campaign objects.

- [ ] **Step 1: Failing test (against the golden fixture)**

```python
# tests/test_rsc_parse.py
from pathlib import Path
from clipscore.ingest.rsc import parse_discover

FIX = Path("tests/fixtures/contentrewards/discover_golden.html")

def test_parses_and_dedups():
    camps = parse_discover(FIX.read_text(encoding="utf-8"))
    ids = [c["id"] for c in camps]
    assert len(camps) == 5                     # 6 raw entries -> 5 after dedup-by-id
    assert len(set(ids)) == 5
    assert "dd9f7918-e51d-4935-9f23-5935c783774a" in ids

def test_money_unescaped_but_string():
    camps = {c["id"]: c for c in parse_discover(FIX.read_text(encoding="utf-8"))}
    c = camps["dd9f7918-e51d-4935-9f23-5935c783774a"]
    assert c["pricePerView"] == "$1.50"        # single $, coercion happens later
    assert c["totalBudget"] == "$250,000"
    assert c["whopExperienceId"].startswith("exp_")

def test_empty_or_garbage_returns_empty():
    assert parse_discover("") == []
    assert parse_discover("<html><body>no payload</body></html>") == []
```

- [ ] **Step 2: Confirm fail.**
- [ ] **Step 3: Implement** (mirrors the spike-validated pipeline)

```python
# src/clipscore/ingest/rsc.py
"""Extract campaign objects from the /discover Next.js RSC payload.

The page emits many `self.__next_f.push([1,"<chunk>"])` calls whose JS string
chunks concatenate into one escaped blob. There is NO single named campaigns
array (the list is RSC-streamed), so we locate each campaign by its
`whopExperienceId`, brace-walk to the enclosing object, and dedup by `id`.
`$$` is the RSC escape for a literal `$` in money fields. Validated in the
Phase 0 spike (526 raw matches -> 502 distinct on live data)."""
import json
import re

_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,\s*(".*?")\]\)', re.DOTALL)

def _decode_blob(html: str) -> str:
    chunks = _CHUNK.findall(html)
    if not chunks:
        return ""
    parts = []
    for c in chunks:
        try:
            parts.append(json.loads(c))   # unescape the JS string literal
        except json.JSONDecodeError:
            continue
    return "".join(parts).replace("$$", "$")

def _enclosing_object(s: str, idx: int) -> str | None:
    depth = 0
    start = None
    for i in range(idx, -1, -1):
        ch = s[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            if depth == 0:
                start = i
                break
            depth -= 1
    if start is None:
        return None
    depth = 0
    for j in range(start, len(s)):
        ch = s[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:j + 1]
    return None

def parse_discover(html: str) -> list[dict]:
    blob = _decode_blob(html)
    if not blob:
        return []
    out: dict[str, dict] = {}
    for m in re.finditer("whopExperienceId", blob):
        obj = _enclosing_object(blob, m.start())
        if not obj:
            continue
        try:
            d = json.loads(obj)
        except json.JSONDecodeError:
            continue
        cid = d.get("id")
        if cid and cid not in out:
            out[cid] = d
    return list(out.values())
```

- [ ] **Step 4: Run PASS + full suite green.**
- [ ] **Step 5: Commit** — `git add src/clipscore/ingest/rsc.py tests/test_rsc_parse.py && git commit -m "feat: add RSC discover-payload parser with dedup-by-id"`

---

## Task 4: Challenge/block classifier + `SourceHalted` (`detect.py`)

**Files:** Create `src/clipscore/ingest/detect.py`; Test `tests/test_detect.py`

**Interfaces:**
- Produces: `classify_response(status_code: int, body: str) -> str` returning one of `ok|blocked_403|rate_limited_429|captcha|cf_challenge|login_wall|empty_parse|error`; `class SourceHalted(Exception)` with attrs `url, event_type, http_status, detail`.

- [ ] **Step 1: Failing test**

```python
# tests/test_detect.py
import pytest
from clipscore.ingest.detect import classify_response, SourceHalted

VALID = '<script>self.__next_f.push([1,"x"])</script>' + "x" * 5000

@pytest.mark.parametrize("status,body,expected", [
    (200, VALID, "ok"),
    (403, "Forbidden", "blocked_403"),
    (429, "Too Many Requests", "rate_limited_429"),
    (503, "<div>cf-chl-bypass</div>Cloudflare", "cf_challenge"),
    (200, "please complete the reCAPTCHA to continue", "captcha"),
    (200, "<html>Attention Required! Cloudflare</html>", "cf_challenge"),
    (200, "redirecting to /login for authentication", "login_wall"),
    (200, "<html><body>tiny</body></html>", "empty_parse"),
    (500, "Internal Server Error", "error"),
])
def test_classify(status, body, expected):
    assert classify_response(status, body) == expected

def test_sourcehalted_carries_fields():
    e = SourceHalted(url="https://x/discover", event_type="blocked_403",
                     http_status=403, detail="Forbidden")
    assert e.event_type == "blocked_403" and e.http_status == 403
```

- [ ] **Step 2: Confirm fail.**
- [ ] **Step 3: Implement**

```python
# src/clipscore/ingest/detect.py
"""Classify an HTTP response for challenges/blocks BEFORE parsing.
Enforces drop-don't-evade: the ingester raises SourceHalted on any non-`ok`."""
import re

class SourceHalted(Exception):
    def __init__(self, url: str, event_type: str, http_status: int | None, detail: str):
        super().__init__(f"{event_type} at {url}: {detail}")
        self.url = url
        self.event_type = event_type
        self.http_status = http_status
        self.detail = detail

_CAPTCHA = re.compile(r"recaptcha|hcaptcha|captcha", re.I)
_CF = re.compile(r"cf-chl|cloudflare|attention required|__cf_bm", re.I)
_DATADOME = re.compile(r"datadome|perimeterx|px-captcha", re.I)
_LOGIN = re.compile(r"/login|please (log|sign) in|authentication required", re.I)
_PAYLOAD = "self.__next_f.push"
_MIN_BODY = 1000  # a real /discover page is ~8MB; anything tiny is a failed fetch

def classify_response(status_code: int, body: str) -> str:
    if status_code == 403:
        return "blocked_403"
    if status_code == 429:
        return "rate_limited_429"
    body = body or ""
    if _CAPTCHA.search(body):
        return "captcha"
    if _CF.search(body) or _DATADOME.search(body):
        return "cf_challenge"
    if _LOGIN.search(body) and _PAYLOAD not in body:
        return "login_wall"
    if status_code >= 500 or status_code >= 400:
        return "error"
    if _PAYLOAD not in body or len(body) < _MIN_BODY:
        return "empty_parse"
    return "ok"
```
(Order matters: body-marker checks run before the generic `>=400` error bucket so a 503 Cloudflare page classifies as `cf_challenge`, not `error`.)

- [ ] **Step 4: Run PASS.**
- [ ] **Step 5: Commit** — `git add src/clipscore/ingest/detect.py tests/test_detect.py && git commit -m "feat: add challenge/block classifier and SourceHalted"`

---

## Task 5: Requirements extraction (`extract.py`)

**Files:** Create `src/clipscore/ingest/extract.py`; Test `tests/test_extract.py`

**Interfaces:**
- Produces: `extract_requirements(description: str | None) -> dict` with keys `cap_per_post_usd: float|None`, `cap_provenance: str` (`"observed"|"absent"`), `min_views_threshold: int|None`, `min_payout_threshold_usd: float|None`.

- [ ] **Step 1: Failing test**

```python
# tests/test_extract.py
from clipscore.ingest.extract import extract_requirements

def test_cap_observed():
    r = extract_requirements("Great campaign. Max $500 per video. Post daily.")
    assert r["cap_per_post_usd"] == 500.0
    assert r["cap_provenance"] == "observed"

def test_min_views():
    r = extract_requirements("Minimum Floor: 5,000 views required to earn.")
    assert r["min_views_threshold"] == 5000

def test_min_payout():
    r = extract_requirements("Minimum payout $50 before withdrawal.")
    assert r["min_payout_threshold_usd"] == 50.0

def test_absent_when_none_or_no_match():
    for d in (None, "", "Just vibes, clip our streams."):
        r = extract_requirements(d)
        assert r["cap_per_post_usd"] is None
        assert r["cap_provenance"] == "absent"
        assert r["min_views_threshold"] is None
        assert r["min_payout_threshold_usd"] is None
```

- [ ] **Step 2: Confirm fail.**
- [ ] **Step 3: Implement** (partial-coverage regex; unknown ⇒ absent, never assume uncapped)

```python
# src/clipscore/ingest/extract.py
"""Best-effort regex extraction of caps/thresholds from a campaign's free-text
`description` (contentrewards has no structured requirements field). Coverage is
partial by design: no match => provenance 'absent' (NOT 'uncapped')."""
import re
from clipscore.ingest.coerce import money_to_float, views_to_int

_CAP = re.compile(r"(?:max|cap|up to|maximum)\D{0,15}\$\s?([\d,]+(?:\.\d+)?)\s*(?:/|per)?\s*(?:video|post|clip)?", re.I)
_MIN_VIEWS = re.compile(r"(?:min(?:imum)?(?:\s+floor)?|floor|at least)\D{0,15}?([\d,]+)\s*views", re.I)
_MIN_PAYOUT = re.compile(r"min(?:imum)?\s+payout\D{0,10}\$\s?([\d,]+(?:\.\d+)?)", re.I)

def extract_requirements(description: str | None) -> dict:
    out = {"cap_per_post_usd": None, "cap_provenance": "absent",
           "min_views_threshold": None, "min_payout_threshold_usd": None}
    if not description:
        return out
    m = _CAP.search(description)
    if m:
        out["cap_per_post_usd"] = money_to_float(m.group(1))
        if out["cap_per_post_usd"] is not None:
            out["cap_provenance"] = "observed"
    m = _MIN_VIEWS.search(description)
    if m:
        out["min_views_threshold"] = views_to_int(m.group(1))
    m = _MIN_PAYOUT.search(description)
    if m:
        out["min_payout_threshold_usd"] = money_to_float(m.group(1))
    return out
```

- [ ] **Step 4: Run PASS.**
- [ ] **Step 5: Commit** — `git add src/clipscore/ingest/extract.py tests/test_extract.py && git commit -m "feat: add requirements regex extraction from description"`

---

## Task 6: Epoch-model fix (revival-only) in `upsert.py`

**Files:** Modify `src/clipscore/ingest/upsert.py`; Test `tests/test_epoch_status.py`

**Interfaces:**
- Consumes: existing `upsert_campaign(session, up, seen_at)`, `_current_epoch`.
- Behavior change: a new epoch is triggered by (a) budget top-up `> EPOCH_RESET_RATIO×` (unchanged), or (b) a genuine **ended→active revival**. A present campaign that stays `ended` keeps its epoch.

- [ ] **Step 1: Failing regression test**

```python
# tests/test_epoch_status.py
from clipscore.ingest.upsert import upsert_campaign
from clipscore.ingest.dto import CampaignUpsert, SnapshotData
from clipscore.db.models import CampaignSnapshot
from sqlalchemy import select

def _up(status, remaining):
    return CampaignUpsert(source="cr", external_id="x", status=status,
                          snapshot=SnapshotData(budget_total_usd=1000,
                                                budget_remaining_usd=remaining))

def _epochs(session):
    return [s.epoch for s in session.execute(
        select(CampaignSnapshot).order_by(CampaignSnapshot.id)).scalars().all()]

def test_present_ended_does_not_inflate_epoch(session):
    for _ in range(3):
        upsert_campaign(session, _up("ended", 500), "2026-07-13T00:00:00Z")
    assert _epochs(session) == [0, 0, 0]

def test_revival_bumps_epoch(session):
    upsert_campaign(session, _up("ended", 500), "2026-07-13T00:00:00Z")
    upsert_campaign(session, _up("active", 500), "2026-07-13T01:00:00Z")
    assert _epochs(session) == [0, 1]

def test_budget_topup_still_bumps(session):
    upsert_campaign(session, _up("active", 100), "2026-07-13T00:00:00Z")
    upsert_campaign(session, _up("active", 1000), "2026-07-13T01:00:00Z")  # >1.10x
    assert _epochs(session)[-1] == 1
```

- [ ] **Step 2: Run** — `test_present_ended_does_not_inflate_epoch` FAILS (epochs `[0,1,2]`); others pass.

- [ ] **Step 3: Implement** — in `upsert.py`:
Replace the `was_ended` computation and `_current_epoch` signature so revival, not "currently ended", drives the bump.
```python
def _current_epoch(session, campaign_id, new_remaining, reviving: bool) -> int:
    latest = _latest_snapshot(session, campaign_id)
    if latest is None:
        return 0
    if reviving:
        return latest.epoch + 1
    prev = latest.budget_remaining_usd
    if prev is not None and new_remaining is not None and prev > 0 and new_remaining > prev * EPOCH_RESET_RATIO:
        return latest.epoch + 1
    return latest.epoch
```
In `upsert_campaign`, replace:
```python
    was_ended = existing is not None and existing.status == "ended"
```
with:
```python
    reviving = existing is not None and existing.status == "ended" and up.status != "ended"
```
and pass `reviving` into `_current_epoch(...)`.

- [ ] **Step 4: Run** — `tests/test_epoch_status.py` all PASS; full suite green (Stage-1 epoch tests unaffected).
- [ ] **Step 5: Commit** — `git add src/clipscore/ingest/upsert.py tests/test_epoch_status.py && git commit -m "fix: epoch resets on ended->active revival, not while staying ended"`

---

## Task 7: Fetch-event logging + access-status flip (`events.py`)

**Files:** Create `src/clipscore/ingest/events.py`; Test `tests/test_events.py`

**Interfaces:**
- Produces: `log_fetch_event(session, source, url, event_type, http_status=None, detail=None) -> None`; `flip_access_status(session, source, access_status) -> int` (returns rows updated).

- [ ] **Step 1: Failing test**

```python
# tests/test_events.py
from clipscore.ingest.events import log_fetch_event, flip_access_status
from clipscore.ingest.upsert import upsert_campaign
from clipscore.ingest.dto import CampaignUpsert, SnapshotData
from clipscore.db.models import FetchEvent, Campaign
from sqlalchemy import select

def test_log_fetch_event(session):
    log_fetch_event(session, "cr", "https://x/discover", "blocked_403", 403, "Forbidden")
    ev = session.execute(select(FetchEvent)).scalars().one()
    assert ev.url == "https://x/discover" and ev.event_type == "blocked_403"
    assert ev.http_status == 403 and ev.detected_at.endswith("Z")

def test_flip_access_status(session):
    upsert_campaign(session, CampaignUpsert(source="cr", external_id="a",
                    snapshot=SnapshotData()), "2026-07-13T00:00:00Z")
    n = flip_access_status(session, "cr", "tos_restricted")
    assert n == 1
    c = session.execute(select(Campaign)).scalars().one()
    assert c.access_status == "tos_restricted"
```

- [ ] **Step 2: Confirm fail.**
- [ ] **Step 3: Implement**

```python
# src/clipscore/ingest/events.py
"""Audit + halt side-effects for drop-don't-evade."""
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from clipscore.db.models import FetchEvent, Campaign
from clipscore.time import utcnow_iso

def log_fetch_event(session: Session, source: str, url: str, event_type: str,
                    http_status: int | None = None, detail: str | None = None) -> None:
    session.add(FetchEvent(source=source, url=url, event_type=event_type,
                           http_status=http_status, detail=detail,
                           detected_at=utcnow_iso()))
    session.commit()

def flip_access_status(session: Session, source: str, access_status: str) -> int:
    result = session.execute(
        update(Campaign).where(Campaign.source == source).values(access_status=access_status)
    )
    session.commit()
    return result.rowcount
```

- [ ] **Step 4: Run PASS.**
- [ ] **Step 5: Commit** — `git add src/clipscore/ingest/events.py tests/test_events.py && git commit -m "feat: add fetch-event logging and access-status flip"`

---

## Task 8: `run_ingest_batch` halt-handling + malformed-entry skip

**Files:** Modify `src/clipscore/ingest/upsert.py`; Test `tests/test_batch_resilience.py`

**Interfaces:**
- Consumes: `SourceHalted` (Task 4), `log_fetch_event`/`flip_access_status` (Task 7).
- Behavior: `run_ingest_batch` catches `SourceHalted` from `ingester.fetch()` → logs event, flips `access_status` to `tos_restricted`, returns `{"status":"halted","event_type":...}`, runs no sweep. Per-raw `normalize`+`upsert` wrapped so one malformed entry is logged & skipped without aborting the batch (returned `{"status":"ok","count":N,"skipped":K,"ended":...}`).

- [ ] **Step 1: Failing test**

```python
# tests/test_batch_resilience.py
import pytest
from clipscore.config import get_settings
from clipscore.ingest.base import BaseIngester
from clipscore.ingest.detect import SourceHalted
from clipscore.ingest.dto import CampaignUpsert, SnapshotData
from clipscore.ingest.upsert import run_ingest_batch
from clipscore.db.models import Campaign, FetchEvent
from sqlalchemy import select

@pytest.fixture(autouse=True)
def _clear():
    get_settings.cache_clear(); yield; get_settings.cache_clear()

class HaltIngester(BaseIngester):
    source_name = "cr"
    def fetch(self):
        raise SourceHalted("https://x/discover", "blocked_403", 403, "Forbidden")
    def normalize(self, raw):
        raise AssertionError("should not be called")

class MostlyGoodIngester(BaseIngester):
    source_name = "cr"
    def fetch(self):
        return [{"ok": True, "eid": str(i)} for i in range(60)] + [{"bad": True}]
    def normalize(self, raw):
        if raw.get("bad"):
            raise ValueError("malformed entry")
        return CampaignUpsert(source="cr", external_id=raw["eid"], status="active",
                              snapshot=SnapshotData(budget_total_usd=100, budget_remaining_usd=50))

def test_halt_logs_and_flips_no_sweep(session):
    res = run_ingest_batch(session, HaltIngester())
    assert res["status"] == "halted" and res["event_type"] == "blocked_403"
    assert session.execute(select(FetchEvent)).scalars().one().event_type == "blocked_403"

def test_malformed_entry_skipped(session):
    res = run_ingest_batch(session, MostlyGoodIngester())
    assert res["status"] == "ok" and res["count"] == 61 and res["skipped"] == 1
    assert len(session.execute(select(Campaign)).scalars().all()) == 60
```

- [ ] **Step 2: Confirm fail.**
- [ ] **Step 3: Implement** — rewrite `run_ingest_batch` (keep harvest gate + sweep):

```python
def run_ingest_batch(session, ingester, seen_at=None, miss_counts=None):
    from clipscore.ingest.detect import SourceHalted
    from clipscore.ingest.events import log_fetch_event, flip_access_status
    settings = get_settings()
    seen_at = seen_at or utcnow_iso()
    miss_counts = miss_counts if miss_counts is not None else {}
    try:
        raws = ingester.fetch()
    except SourceHalted as e:
        log_fetch_event(session, ingester.source_name, e.url, e.event_type,
                        e.http_status, e.detail)
        flip_access_status(session, ingester.source_name, "tos_restricted")
        return {"status": "halted", "event_type": e.event_type}
    if len(raws) < settings.harvest_min_campaigns:
        return {"status": "harvest_too_small", "count": len(raws)}
    current_ids, skipped = set(), 0
    for raw in raws:
        try:
            up = ingester.normalize(raw)
            upsert_campaign(session, up, seen_at)
            current_ids.add(up.external_id)
        except Exception:
            skipped += 1
            continue
    ended = sweep_ended(session, ingester.source_name, current_ids,
                        miss_counts, settings.unseen_polls_to_end)
    return {"status": "ok", "count": len(raws), "skipped": skipped, "ended": ended}
```
(Imports are function-local to avoid a circular import: `events` imports models; `detect` is dependency-free.)

- [ ] **Step 4: Run PASS + full suite green** (existing Stage-1 `run_ingest_batch` tests: the ok path now also returns `skipped`; update those assertions only if they assert exact dict equality — prefer key-wise asserts).
- [ ] **Step 5: Commit** — `git add src/clipscore/ingest/upsert.py tests/test_batch_resilience.py && git commit -m "feat: run_ingest_batch handles SourceHalted and skips malformed entries"`

---

## Task 9: `ContentrewardsIngester` + poll job

**Files:** Create `src/clipscore/ingest/contentrewards.py`, `src/clipscore/jobs/__init__.py`, `src/clipscore/jobs/poll.py`; Test `tests/test_contentrewards.py`

**Interfaces:**
- Consumes: `parse_discover`, `classify_response`/`SourceHalted`, `coerce.*`, `extract_requirements`, `Settings`, `BaseIngester`, `CampaignUpsert`/`SnapshotData`.
- Produces: `ContentrewardsIngester(client: httpx.Client | None = None, etag: str | None = None)` with `source_name = "contentrewards"`, `fetch()`, `normalize(raw)`; `jobs.poll.run_once(session)` and `jobs.poll.build_scheduler(session_factory)`.

- [ ] **Step 1: Failing tests (httpx.MockTransport — no network)**

```python
# tests/test_contentrewards.py
from pathlib import Path
import httpx, pytest
from clipscore.config import get_settings
from clipscore.ingest.contentrewards import ContentrewardsIngester
from clipscore.ingest.detect import SourceHalted

FIX = Path("tests/fixtures/contentrewards/discover_golden.html").read_text(encoding="utf-8")
ROBOTS_OK = "User-Agent: *\nAllow: /discover\nDisallow: /api/\n"

@pytest.fixture(autouse=True)
def _clear():
    get_settings.cache_clear(); yield; get_settings.cache_clear()

def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://contentrewards.com")

def test_fetch_parses_campaigns():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_OK)
        return httpx.Response(200, text=FIX)
    raws = ContentrewardsIngester(client=_client(handler)).fetch()
    assert len(raws) == 5

def test_fetch_403_raises_halt():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_OK)
        return httpx.Response(403, text="Forbidden")
    with pytest.raises(SourceHalted) as ei:
        ContentrewardsIngester(client=_client(handler)).fetch()
    assert ei.value.event_type == "blocked_403"

def test_robots_disallow_raises_halt():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-Agent: *\nDisallow: /discover\n")
        return httpx.Response(200, text=FIX)
    with pytest.raises(SourceHalted) as ei:
        ContentrewardsIngester(client=_client(handler)).fetch()
    assert ei.value.event_type == "robots_disallow"

def test_normalize_maps_fields():
    ing = ContentrewardsIngester()
    raw = {"id": "abc", "whopExperienceId": "exp_1", "whopProductRoute": "slug",
           "title": "T", "brand": "B", "category": "Personal Brand",
           "campaignType": "clipping", "pricePerView": "$1.50",
           "totalBudget": "$250,000", "budgetSpent": "$50,000", "creators": 10,
           "socialPlatforms": ["tiktok", "instagram"], "isVerified": True,
           "status": "completed", "description": "Max $500 per video.",
           "stats": {"successRate": 26, "engagement": "50000.0", "viewCount": "51.4M"}}
    up = ing.normalize(raw)
    assert up.external_id == "abc" and up.whop_experience_id == "exp_1"
    assert up.niche == "personal brand"           # category, slugified
    assert up.campaign_type == "clipping"
    assert up.cpm_usd == 1.5 and up.budget_total_usd == 250000.0
    assert up.status == "ended"                    # completed -> ended
    assert up.cap_per_post_usd == 500.0 and up.cap_provenance == "observed"
    assert up.snapshot.budget_remaining_usd == 200000.0
    assert up.snapshot.total_views == 51_400_000
    assert up.snapshot.active_clippers == 10
    assert up.snapshot.success_rate == 26.0
    assert up.allowed_socials == ["tiktok", "instagram"]
```

- [ ] **Step 2: Confirm fail.**
- [ ] **Step 3: Implement**

```python
# src/clipscore/ingest/contentrewards.py
"""Ingester for contentrewards.com/discover (== Whop Content Rewards).

Compliance: robots.txt allows /discover, disallows /api/ (checked at runtime,
every poll). Single plain GET of the already-served public page; no Playwright,
no /api/ probing. Any challenge/block => SourceHalted (drop-don't-evade).
Initial recon 2026-07-13: robots allows /discover; site ToS has no anti-scraping
clause. See docs/spikes/2026-07-13-phase-0-stable-key-spike.md for payload shape."""
import re
import httpx
from urllib.robotparser import RobotFileParser
from clipscore.config import get_settings
from clipscore.ingest.base import BaseIngester
from clipscore.ingest.dto import CampaignUpsert, SnapshotData
from clipscore.ingest.rsc import parse_discover
from clipscore.ingest.detect import classify_response, SourceHalted
from clipscore.ingest.extract import extract_requirements
from clipscore.ingest import coerce

_TERMINAL = {"completed": "ended", "ended": "ended", "paused": "paused", "active": "active"}

class ContentrewardsIngester(BaseIngester):
    source_name = "contentrewards"

    def __init__(self, client: httpx.Client | None = None, etag: str | None = None):
        s = get_settings()
        self._base = s.source_base_url
        self._path = s.discover_path
        self._ua = s.user_agent
        self._timeout = s.http_timeout_s
        self._client = client
        self._etag = etag

    def _http(self) -> httpx.Client:
        return self._client or httpx.Client(base_url=self._base, timeout=self._timeout,
                                            headers={"User-Agent": self._ua}, follow_redirects=True)

    def _discover_url(self) -> str:
        return f"{self._base}{self._path}"

    def _check_robots(self, client: httpx.Client) -> None:
        try:
            r = client.get("/robots.txt")
        except httpx.HTTPError:
            return  # robots unreachable: fail open on the check, response classifier still guards
        rp = RobotFileParser()
        rp.parse(r.text.splitlines())
        if not rp.can_fetch(self._ua, self._path) and not rp.can_fetch("*", self._path):
            raise SourceHalted(self._discover_url(), "robots_disallow", None,
                               f"robots.txt disallows {self._path}")

    def fetch(self) -> list[dict]:
        client = self._http()
        try:
            self._check_robots(client)
            headers = {"If-None-Match": self._etag} if self._etag else {}
            resp = client.get(self._path, headers=headers)
            if resp.status_code == 304:
                return []  # unchanged since last poll; caller keeps prior state
            body = resp.text
            event = classify_response(resp.status_code, body)
            if event != "ok":
                raise SourceHalted(self._discover_url(), event, resp.status_code,
                                   f"classify_response={event}")
            self._etag = resp.headers.get("ETag") or self._etag
            return parse_discover(body)
        finally:
            if self._client is None:
                client.close()

    def normalize(self, raw: dict) -> CampaignUpsert:
        stats = raw.get("stats") or {}
        req = extract_requirements(raw.get("description"))
        total = coerce.money_to_float(raw.get("totalBudget"))
        spent = coerce.money_to_float(raw.get("budgetSpent"))
        remaining = (total - spent) if (total is not None and spent is not None) else None
        category = raw.get("category")
        niche = category.strip().lower() if isinstance(category, str) and category.strip() else None
        route = raw.get("whopProductRoute")
        url = f"{self._base}{self._path}/{route}" if route else self._discover_url()
        return CampaignUpsert(
            source=self.source_name,
            external_id=raw["id"],
            whop_experience_id=raw.get("whopExperienceId"),
            whop_product_route=route,
            url=url,
            brand=raw.get("brand"),
            title=raw.get("title"),
            niche=niche,
            campaign_type=raw.get("campaignType"),
            cpm_usd=coerce.money_to_float(raw.get("pricePerView")),
            platform_fee_pct=None,  # source default applied at scoring from platform_trust
            cap_per_post_usd=req["cap_per_post_usd"],
            cap_provenance=req["cap_provenance"],
            min_payout_threshold_usd=req["min_payout_threshold_usd"],
            min_views_threshold=req["min_views_threshold"],
            budget_total_usd=total,
            allowed_socials=raw.get("socialPlatforms"),
            requirements_raw=raw.get("description"),
            status=_TERMINAL.get(raw.get("status"), "active"),
            is_verified=raw.get("isVerified"),
            snapshot=SnapshotData(
                budget_total_usd=total,
                budget_spent_usd=spent,
                budget_remaining_usd=remaining,
                active_clippers=coerce.to_int(raw.get("creators")),
                total_views=coerce.views_to_int(stats.get("viewCount")),
                success_rate=coerce.to_float(stats.get("successRate")),
                engagement=coerce.to_float(stats.get("engagement")),
            ),
        )
```

```python
# src/clipscore/jobs/__init__.py
```
```python
# src/clipscore/jobs/poll.py
"""APScheduler entrypoint: poll contentrewards on an interval and ingest."""
import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from clipscore.config import get_settings
from clipscore.ingest.contentrewards import ContentrewardsIngester
from clipscore.ingest.upsert import run_ingest_batch

log = structlog.get_logger()
_MISS_COUNTS: dict[str, int] = {}

def run_once(session) -> dict:
    result = run_ingest_batch(session, ContentrewardsIngester(), miss_counts=_MISS_COUNTS)
    log.info("ingest_batch", **result)
    return result

def build_scheduler(session_factory) -> BackgroundScheduler:
    sched = BackgroundScheduler()
    minutes = get_settings().poll_interval_minutes
    def job():
        with session_factory() as s:
            run_once(s)
    sched.add_job(job, "interval", minutes=minutes, id="contentrewards_poll")
    return sched
```

- [ ] **Step 4: Run** — `tests/test_contentrewards.py` PASS; full suite green. (`apscheduler` and `structlog` must be in `pyproject.toml` deps; add if missing and note in commit.)
- [ ] **Step 5: Commit** — `git add src/clipscore/ingest/contentrewards.py src/clipscore/jobs/ tests/test_contentrewards.py pyproject.toml && git commit -m "feat: ContentrewardsIngester + APScheduler poll job"`

---

## Manual (non-CI) acceptance — spec Phase 2

Not a pytest test (needs live network); run once after the branch is green, document the result:
1. Point `.env` at a scratch SQLite DB; `alembic upgrade head`; seed (`python -m clipscore.seed` or the Stage-1 seed entry).
2. Run two poll cycles (call `jobs.poll.run_once` twice, minutes apart, against the real site).
3. Confirm: `campaigns` populated (~500 rows; `niche` from category; `campaign_type` set; caps `observed`/`absent`); ≥2 `campaign_snapshots` per active campaign across the two polls; no non-`ok` `fetch_events` rows under normal operation.
4. Simulate a partial poll (truncate the fixture / force `< harvest_min_campaigns`) and confirm the ended-sweep does **not** run and no authoritative bad state is written.

## Self-review checklist (author, before dispatch)
- Every non-Optional model/DTO field written by `normalize` has a value or is explicitly nullable (avoid the Stage-1 nullability-drift class of bug).
- `0002` `down_revision` matches the real `0001` revision id.
- No test depends on a real `.env`; `get_settings.cache_clear()` used where env matters.
- Circular imports avoided (function-local imports in `upsert.run_ingest_batch`).
- Stage-1 tests that assert on `run_ingest_batch`'s return dict updated for the new `skipped` key.
