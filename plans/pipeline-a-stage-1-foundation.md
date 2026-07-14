# Pipeline A — Stage 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the data layer and ingestion framework for the Clipping Campaign Value Aggregator — SQLite schema, migrations, seeds, config, and a testable `BaseIngester` with upsert/epoch/ended-sweep logic — with no live scraping yet.

**Architecture:** Python package `clipscore` (src layout). SQLite (WAL) via SQLAlchemy 2.x ORM + Alembic. All ingestion sources subclass a `BaseIngester` ABC that returns normalized DTOs; shared upsert logic writes campaigns + time-series snapshots, handles budget-reset epochs, and marks stale campaigns ended (gated by a harvest sanity check). A `FakeIngester` drives all tests so Stage 1 is fully testable without network access.

**Tech Stack:** Python 3.11+ · SQLAlchemy 2.x · Alembic · pydantic-settings · structlog · pytest. (httpx, APScheduler, discord.py arrive in later stages.)

## Global Constraints

- **Python:** 3.11+ required.
- **Database:** SQLite in **WAL mode** with `busy_timeout`; single-process topology. No Postgres-only features (no JSONB, no native arrays).
- **Storage conventions (apply to every model):** UUID PK / FK → `String` (TEXT); money (`*_usd`) and ratios → `Float` (REAL); counts → `Integer`; boolean → `Boolean`; string arrays → `JSON` column holding a JSON list; timestamps → `String` (TEXT) holding UTC ISO-8601 `YYYY-MM-DDTHH:MM:SSZ`; bigserial/serial → `Integer` autoincrement PK.
- **Times are UTC** everywhere; use the shared `utcnow_iso()` helper — never store local time.
- **Money is REAL** (scores are estimates, not accounting).
- **TDD:** every task writes a failing test first, then the minimal implementation. Commit after each task.
- **Package name:** `clipscore`, importable from `src/`.

---

## File Structure

```
clipping/
├── pyproject.toml                      # package + pinned deps (Task 1)
├── .env.example                        # documented config keys (Task 1)
├── alembic.ini                         # (Task 6)
├── alembic/
│   ├── env.py                          # wired to clipscore metadata (Task 6)
│   └── versions/0001_initial.py        # all tables (Task 6)
├── src/clipscore/
│   ├── __init__.py
│   ├── time.py                         # utcnow_iso() (Task 2)
│   ├── config.py                       # pydantic-settings (Task 3)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py                     # DeclarativeBase (Task 4)
│   │   ├── models.py                   # all 7 ORM models (Task 4)
│   │   └── session.py                  # engine + WAL pragmas + session factory (Task 5)
│   ├── seed.py                         # platform_trust + niche_baselines seeds (Task 7)
│   └── ingest/
│       ├── __init__.py
│       ├── dto.py                      # RawCampaign, CampaignUpsert, SnapshotData (Task 8)
│       ├── base.py                     # BaseIngester ABC (Task 8)
│       └── upsert.py                   # upsert + epoch + ended-sweep (Tasks 9–10)
└── tests/
    ├── conftest.py                     # in-memory DB fixture + FakeIngester (Task 5, 8)
    ├── test_config.py                  # (Task 3)
    ├── test_models.py                  # (Task 4)
    ├── test_session.py                 # (Task 5)
    ├── test_migration.py               # (Task 6)
    ├── test_seed.py                    # (Task 7)
    └── test_upsert.py                  # (Tasks 9–10)
```

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `src/clipscore/__init__.py`
- Create: `tests/__init__.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an installable `clipscore` package; `pytest` runnable.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "clipscore"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "sqlalchemy>=2.0,<2.1",
    "alembic>=1.13,<2.0",
    "pydantic-settings>=2.2,<3.0",
    "structlog>=24.1",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]

[tool.hatch.build.targets.wheel]
packages = ["src/clipscore"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Write `.env.example`**

```bash
# SQLite database URL (WAL enabled at runtime)
CLIPSCORE_DB_URL=sqlite:///clipscore.db
# Ingestion poll interval, minutes
CLIPSCORE_POLL_INTERVAL_MINUTES=45
# Consecutive missed polls before a campaign is marked ended
CLIPSCORE_UNSEEN_POLLS_TO_END=3
# Minimum campaigns in a poll to be considered a healthy harvest
CLIPSCORE_HARVEST_MIN_CAMPAIGNS=50
# Scoring constants
CLIPSCORE_DEFAULT_P_APPROVAL=0.7
CLIPSCORE_DEFAULT_ASSUMED_CAP_USD=500
CLIPSCORE_HOURS_PER_CLIP=0.75
# Discord (later stages)
CLIPSCORE_DISCORD_TOKEN=
# Feature flags
CLIPSCORE_ENABLE_PLAYWRIGHT=false
```

- [ ] **Step 3: Create empty package files**

```bash
mkdir -p src/clipscore tests
printf '' > src/clipscore/__init__.py
printf '' > tests/__init__.py
```

- [ ] **Step 4: Install and verify pytest runs**

Run: `pip install -e ".[dev]" && pytest -q`
Expected: pytest runs and reports "no tests ran" (exit 5) — no import errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .env.example src/clipscore/__init__.py tests/__init__.py
git commit -m "chore: scaffold clipscore package"
```

---

### Task 2: Time helper

**Files:**
- Create: `src/clipscore/time.py`
- Test: `tests/test_time.py`

**Interfaces:**
- Produces: `utcnow_iso() -> str` returning `YYYY-MM-DDTHH:MM:SSZ` (UTC).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_time.py
import re
from clipscore.time import utcnow_iso

def test_utcnow_iso_format():
    value = utcnow_iso()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_time.py -v`
Expected: FAIL — `ModuleNotFoundError: clipscore.time`.

- [ ] **Step 3: Implement**

```python
# src/clipscore/time.py
from datetime import datetime, timezone

def utcnow_iso() -> str:
    """Current UTC time as ISO-8601 with trailing Z, second precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_time.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/time.py tests/test_time.py
git commit -m "feat: add utcnow_iso helper"
```

---

### Task 3: Config

**Files:**
- Create: `src/clipscore/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings` (pydantic-settings) and `get_settings() -> Settings`. Fields: `db_url: str`, `poll_interval_minutes: int`, `unseen_polls_to_end: int`, `harvest_min_campaigns: int`, `default_p_approval: float`, `default_assumed_cap_usd: float`, `hours_per_clip: float`, `discord_token: str | None`, `enable_playwright: bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from clipscore.config import Settings

def test_defaults():
    s = Settings(_env_file=None)
    assert s.db_url == "sqlite:///clipscore.db"
    assert s.poll_interval_minutes == 45
    assert s.unseen_polls_to_end == 3
    assert s.harvest_min_campaigns == 50
    assert s.default_p_approval == 0.7
    assert s.default_assumed_cap_usd == 500.0
    assert s.hours_per_clip == 0.75
    assert s.enable_playwright is False

def test_env_override(monkeypatch):
    monkeypatch.setenv("CLIPSCORE_POLL_INTERVAL_MINUTES", "10")
    s = Settings(_env_file=None)
    assert s.poll_interval_minutes == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: clipscore.config`.

- [ ] **Step 3: Implement**

```python
# src/clipscore/config.py
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLIPSCORE_", env_file=".env", extra="ignore")

    db_url: str = "sqlite:///clipscore.db"
    poll_interval_minutes: int = 45
    unseen_polls_to_end: int = 3
    harvest_min_campaigns: int = 50
    default_p_approval: float = 0.7
    default_assumed_cap_usd: float = 500.0
    hours_per_clip: float = 0.75
    discord_token: str | None = None
    enable_playwright: bool = False

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/config.py tests/test_config.py
git commit -m "feat: add pydantic-settings config"
```

---

### Task 4: ORM models

**Files:**
- Create: `src/clipscore/db/__init__.py` (empty)
- Create: `src/clipscore/db/base.py`
- Create: `src/clipscore/db/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Base` (DeclarativeBase) and models `Campaign`, `CampaignSnapshot`, `FetchEvent`, `PlatformTrust`, `NicheBaseline`, `CampaignScore`, `Outcome`. Column names match `IMPLEMENTATION_PLAN.md` schema; SQLite type conventions from Global Constraints.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from clipscore.db.base import Base
from clipscore.db.models import Campaign, CampaignSnapshot, PlatformTrust

def test_create_and_roundtrip_campaign():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        c = Campaign(
            id="cid-1", source="contentrewards", external_id="ext-1",
            title="Roobet UGC", niche="entertainment", cpm_usd=1.5,
            platform_fee_pct=0.10, allowed_socials=["tiktok", "reels"],
            status="active", ingest_method="auto", access_status="ingestable",
            cap_provenance="absent", first_seen_at="2026-07-13T00:00:00Z",
            last_seen_at="2026-07-13T00:00:00Z",
        )
        s.add(c)
        s.commit()
        got = s.get(Campaign, "cid-1")
        assert got.allowed_socials == ["tiktok", "reels"]
        assert got.cpm_usd == 1.5

def test_snapshot_has_epoch_and_fk():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        snap = CampaignSnapshot(
            campaign_id="cid-1", epoch=0, budget_total_usd=1000.0,
            budget_spent_usd=200.0, budget_remaining_usd=800.0,
            active_clippers=50, total_views=1_000_000,
            success_rate=0.4, engagement=0.1, captured_at="2026-07-13T00:00:00Z",
        )
        s.add(snap)
        s.commit()
        assert snap.id is not None
        assert snap.epoch == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: clipscore.db.base`.

- [ ] **Step 3: Implement base and models**

```python
# src/clipscore/db/__init__.py
```
```python
# src/clipscore/db/base.py
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```
```python
# src/clipscore/db/models.py
from sqlalchemy import String, Integer, Float, Boolean, JSON, BigInteger
from sqlalchemy.orm import Mapped, mapped_column
from clipscore.db.base import Base

class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, index=True)
    external_id: Mapped[str] = mapped_column(String, index=True)
    whop_experience_id: Mapped[str | None] = mapped_column(String, nullable=True)
    whop_product_route: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    brand: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    niche: Mapped[str | None] = mapped_column(String, nullable=True)
    cpm_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    platform_fee_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    cap_per_post_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cap_provenance: Mapped[str] = mapped_column(String, default="absent")
    min_payout_threshold_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_views_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_total_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    allowed_socials: Mapped[list | None] = mapped_column(JSON, nullable=True)
    requirements_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
    ingest_method: Mapped[str] = mapped_column(String, default="auto")
    access_status: Mapped[str] = mapped_column(String, default="ingestable")
    is_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    first_seen_at: Mapped[str] = mapped_column(String)
    last_seen_at: Mapped[str] = mapped_column(String)

class CampaignSnapshot(Base):
    __tablename__ = "campaign_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(String, index=True)
    epoch: Mapped[int] = mapped_column(Integer, default=0)
    budget_total_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_spent_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_remaining_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_clippers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    engagement: Mapped[float | None] = mapped_column(Float, nullable=True)
    captured_at: Mapped[str] = mapped_column(String, index=True)

class FetchEvent(Base):
    __tablename__ = "fetch_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, index=True)
    url: Mapped[str] = mapped_column(String)
    event_type: Mapped[str] = mapped_column(String)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(String, nullable=True)
    detected_at: Mapped[str] = mapped_column(String, index=True)

class PlatformTrust(Base):
    __tablename__ = "platform_trust"
    source: Mapped[str] = mapped_column(String, primary_key=True)
    trust_score: Mapped[float] = mapped_column(Float)
    default_fee_pct: Mapped[float] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

class NicheBaseline(Base):
    __tablename__ = "niche_baselines"
    niche: Mapped[str] = mapped_column(String, primary_key=True)
    e_views_median: Mapped[int] = mapped_column(Integer)
    p_threshold: Mapped[float] = mapped_column(Float)

class CampaignScore(Base):
    __tablename__ = "campaign_scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(String, index=True)
    scored_at: Mapped[str] = mapped_column(String)
    net_cpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    capped_earnings: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_approval: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_payout: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_health: Mapped[float | None] = mapped_column(Float, nullable=True)
    sat_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    ev_per_clip: Mapped[float | None] = mapped_column(Float, nullable=True)
    cvs_raw: Mapped[float | None] = mapped_column(Float, nullable=True)
    cvs_niche_percentile: Mapped[float | None] = mapped_column(Float, nullable=True)

class Outcome(Base):
    __tablename__ = "outcomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(String, index=True)
    clips_posted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clips_approved: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actual_payout_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    payout_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    logged_at: Mapped[str] = mapped_column(String)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/db/__init__.py src/clipscore/db/base.py src/clipscore/db/models.py tests/test_models.py
git commit -m "feat: add SQLAlchemy models for all tables"
```

---

### Task 5: DB session with WAL

**Files:**
- Create: `src/clipscore/db/session.py`
- Create: `tests/conftest.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `get_settings()`, `Base`.
- Produces: `make_engine(url: str)` (sets WAL + busy_timeout on connect for file DBs), `SessionLocal` session factory, `get_engine()`. Also `conftest.py` fixture `session` yielding a `Session` bound to a fresh in-memory DB with tables created.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session.py
from sqlalchemy import text
from clipscore.db.session import make_engine

def test_wal_enabled_for_file_db(tmp_path):
    db = tmp_path / "t.db"
    engine = make_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
    assert mode.lower() == "wal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_session.py -v`
Expected: FAIL — `ModuleNotFoundError: clipscore.db.session`.

- [ ] **Step 3: Implement session + conftest**

```python
# src/clipscore/db/session.py
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from clipscore.config import get_settings

def _set_sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()

def make_engine(url: str) -> Engine:
    # in-memory DBs cannot use WAL; only wire pragmas for file-backed sqlite
    is_file_sqlite = url.startswith("sqlite:///") and ":memory:" not in url
    engine = create_engine(url, future=True)
    if is_file_sqlite:
        event.listen(engine, "connect", _set_sqlite_pragmas)
        # trigger one connection so WAL is set immediately
        with engine.connect():
            pass
    return engine

_engine = None
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)

def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().db_url)
        SessionLocal.configure(bind=_engine)
    return _engine
```
```python
# tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from clipscore.db.base import Base

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_session.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/db/session.py tests/conftest.py tests/test_session.py
git commit -m "feat: add db session with WAL pragmas + test fixture"
```

---

### Task 6: Alembic initial migration

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/0001_initial.py`
- Test: `tests/test_migration.py`

**Interfaces:**
- Consumes: `Base.metadata`, `get_settings().db_url`.
- Produces: a migration that creates all tables; `alembic upgrade head` / `downgrade base` work.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration.py
import subprocess, sqlite3, os

def test_upgrade_creates_tables(tmp_path):
    db = tmp_path / "m.db"
    env = {**os.environ, "CLIPSCORE_DB_URL": f"sqlite:///{db}"}
    r = subprocess.run(["alembic", "upgrade", "head"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(db)
    names = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"campaigns", "campaign_snapshots", "fetch_events",
            "platform_trust", "niche_baselines", "campaign_scores", "outcomes"} <= names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_migration.py -v`
Expected: FAIL — alembic not configured / command errors.

- [ ] **Step 3: Implement alembic config, env, and migration**

```ini
# alembic.ini
[alembic]
script_location = alembic
[loggers]
keys = root
[handlers]
keys = console
[formatters]
keys = generic
[logger_root]
level = WARN
handlers = console
qualname =
[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic
[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```
```python
# alembic/env.py
from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
from clipscore.config import get_settings
from clipscore.db.base import Base
from clipscore.db import models  # noqa: F401 — register tables

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().db_url)
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True)  # batch mode: SQLite ALTER support
        with context.begin_transaction():
            context.run_migrations()

run_migrations_online()
```
```python
# alembic/versions/0001_initial.py
"""initial schema"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("campaigns",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("source", sa.String, index=True),
        sa.Column("external_id", sa.String, index=True),
        sa.Column("whop_experience_id", sa.String, nullable=True),
        sa.Column("whop_product_route", sa.String, nullable=True),
        sa.Column("url", sa.String, nullable=True),
        sa.Column("brand", sa.String, nullable=True),
        sa.Column("title", sa.String, nullable=True),
        sa.Column("niche", sa.String, nullable=True),
        sa.Column("cpm_usd", sa.Float, nullable=True),
        sa.Column("platform_fee_pct", sa.Float, nullable=True),
        sa.Column("cap_per_post_usd", sa.Float, nullable=True),
        sa.Column("cap_provenance", sa.String, server_default="absent"),
        sa.Column("min_payout_threshold_usd", sa.Float, nullable=True),
        sa.Column("min_views_threshold", sa.Integer, nullable=True),
        sa.Column("budget_total_usd", sa.Float, nullable=True),
        sa.Column("allowed_socials", sa.JSON, nullable=True),
        sa.Column("requirements_raw", sa.String, nullable=True),
        sa.Column("status", sa.String, server_default="active"),
        sa.Column("ingest_method", sa.String, server_default="auto"),
        sa.Column("access_status", sa.String, server_default="ingestable"),
        sa.Column("is_verified", sa.Boolean, nullable=True),
        sa.Column("first_seen_at", sa.String),
        sa.Column("last_seen_at", sa.String),
        sa.UniqueConstraint("source", "external_id", name="uq_source_external"),
    )
    op.create_table("campaign_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.String, index=True),
        sa.Column("epoch", sa.Integer, server_default="0"),
        sa.Column("budget_total_usd", sa.Float, nullable=True),
        sa.Column("budget_spent_usd", sa.Float, nullable=True),
        sa.Column("budget_remaining_usd", sa.Float, nullable=True),
        sa.Column("active_clippers", sa.Integer, nullable=True),
        sa.Column("total_views", sa.BigInteger, nullable=True),
        sa.Column("success_rate", sa.Float, nullable=True),
        sa.Column("engagement", sa.Float, nullable=True),
        sa.Column("captured_at", sa.String, index=True),
    )
    op.create_table("fetch_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String, index=True),
        sa.Column("url", sa.String),
        sa.Column("event_type", sa.String),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("detail", sa.String, nullable=True),
        sa.Column("detected_at", sa.String, index=True),
    )
    op.create_table("platform_trust",
        sa.Column("source", sa.String, primary_key=True),
        sa.Column("trust_score", sa.Float),
        sa.Column("default_fee_pct", sa.Float),
        sa.Column("notes", sa.String, nullable=True),
    )
    op.create_table("niche_baselines",
        sa.Column("niche", sa.String, primary_key=True),
        sa.Column("e_views_median", sa.Integer),
        sa.Column("p_threshold", sa.Float),
    )
    op.create_table("campaign_scores",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.String, index=True),
        sa.Column("scored_at", sa.String),
        sa.Column("net_cpm", sa.Float, nullable=True),
        sa.Column("capped_earnings", sa.Float, nullable=True),
        sa.Column("p_threshold", sa.Float, nullable=True),
        sa.Column("p_approval", sa.Float, nullable=True),
        sa.Column("p_payout", sa.Float, nullable=True),
        sa.Column("budget_health", sa.Float, nullable=True),
        sa.Column("sat_factor", sa.Float, nullable=True),
        sa.Column("ev_per_clip", sa.Float, nullable=True),
        sa.Column("cvs_raw", sa.Float, nullable=True),
        sa.Column("cvs_niche_percentile", sa.Float, nullable=True),
    )
    op.create_table("outcomes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.String, index=True),
        sa.Column("clips_posted", sa.Integer, nullable=True),
        sa.Column("clips_approved", sa.Integer, nullable=True),
        sa.Column("actual_views", sa.BigInteger, nullable=True),
        sa.Column("actual_payout_usd", sa.Float, nullable=True),
        sa.Column("payout_days", sa.Integer, nullable=True),
        sa.Column("logged_at", sa.String),
    )

def downgrade():
    for t in ["outcomes", "campaign_scores", "niche_baselines", "platform_trust",
              "fetch_events", "campaign_snapshots", "campaigns"]:
        op.drop_table(t)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_migration.py -v`
Expected: PASS. Also manually verify: `CLIPSCORE_DB_URL=sqlite:///tmp.db alembic downgrade base` returns 0, then remove `tmp.db`.

- [ ] **Step 5: Commit**

```bash
git add alembic.ini alembic/env.py alembic/versions/0001_initial.py tests/test_migration.py
git commit -m "feat: add alembic initial migration for all tables"
```

---

### Task 7: Seed script

**Files:**
- Create: `src/clipscore/seed.py`
- Test: `tests/test_seed.py`

**Interfaces:**
- Consumes: models `PlatformTrust`, `NicheBaseline`, a `Session`.
- Produces: `seed_all(session)` — idempotent upsert of the seed rows. `PLATFORM_TRUST_SEED` and `NICHE_BASELINE_SEED` constants.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seed.py
from clipscore.seed import seed_all
from clipscore.db.models import PlatformTrust, NicheBaseline

def test_seed_is_idempotent(session):
    seed_all(session)
    seed_all(session)  # second call must not duplicate or error
    assert session.get(PlatformTrust, "contentrewards").default_fee_pct == 0.10
    assert session.get(NicheBaseline, "gaming").e_views_median == 10000
    assert session.query(NicheBaseline).count() == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_seed.py -v`
Expected: FAIL — `ModuleNotFoundError: clipscore.seed`.

- [ ] **Step 3: Implement**

```python
# src/clipscore/seed.py
from sqlalchemy.orm import Session
from clipscore.db.models import PlatformTrust, NicheBaseline

# NOTE: starting estimates — verify against current platform terms.
PLATFORM_TRUST_SEED = [
    dict(source="contentrewards", trust_score=0.80, default_fee_pct=0.10,
         notes="Whop rails; reflects botting-flag/threshold-ban friction. VERIFY."),
]
NICHE_BASELINE_SEED = [
    dict(niche="gaming", e_views_median=10000, p_threshold=0.6),
    dict(niche="entertainment", e_views_median=12000, p_threshold=0.65),
    dict(niche="podcast", e_views_median=7000, p_threshold=0.55),
    dict(niche="finance", e_views_median=5000, p_threshold=0.5),
    dict(niche="fitness", e_views_median=8000, p_threshold=0.6),
    dict(niche="tech", e_views_median=6000, p_threshold=0.55),
    dict(niche="crypto", e_views_median=6000, p_threshold=0.5),
    dict(niche="other", e_views_median=5000, p_threshold=0.5),
]

def seed_all(session: Session) -> None:
    for row in PLATFORM_TRUST_SEED:
        existing = session.get(PlatformTrust, row["source"])
        if existing is None:
            session.add(PlatformTrust(**row))
        else:
            for k, v in row.items():
                setattr(existing, k, v)
    for row in NICHE_BASELINE_SEED:
        existing = session.get(NicheBaseline, row["niche"])
        if existing is None:
            session.add(NicheBaseline(**row))
        else:
            for k, v in row.items():
                setattr(existing, k, v)
    session.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_seed.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/seed.py tests/test_seed.py
git commit -m "feat: add idempotent seed script"
```

---

### Task 8: Ingest DTOs + BaseIngester ABC

**Files:**
- Create: `src/clipscore/ingest/__init__.py` (empty)
- Create: `src/clipscore/ingest/dto.py`
- Create: `src/clipscore/ingest/base.py`
- Modify: `tests/conftest.py` (add `FakeIngester`)
- Test: `tests/test_base_ingester.py`

**Interfaces:**
- Produces:
  - `SnapshotData` dataclass: `budget_total_usd: float|None, budget_spent_usd: float|None, budget_remaining_usd: float|None, active_clippers: int|None, total_views: int|None, success_rate: float|None, engagement: float|None`.
  - `CampaignUpsert` dataclass: `source: str, external_id: str, title: str|None, niche: str|None, cpm_usd: float|None, platform_fee_pct: float|None, cap_per_post_usd: float|None, cap_provenance: str, min_payout_threshold_usd: float|None, min_views_threshold: int|None, budget_total_usd: float|None, allowed_socials: list|None, requirements_raw: str|None, status: str, is_verified: bool|None, whop_experience_id: str|None, whop_product_route: str|None, url: str|None, brand: str|None, snapshot: SnapshotData`.
  - `RawCampaign = dict` (alias for the raw source object).
  - `BaseIngester` ABC: `source_name: str` (class attr), `fetch() -> list[RawCampaign]` (abstract), `normalize(raw: RawCampaign) -> CampaignUpsert` (abstract).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_base_ingester.py
from clipscore.ingest.base import BaseIngester
from clipscore.ingest.dto import CampaignUpsert, SnapshotData

def test_fake_ingester_yields_upserts(fake_ingester):
    raws = fake_ingester.fetch()
    assert len(raws) == 2
    up = fake_ingester.normalize(raws[0])
    assert isinstance(up, CampaignUpsert)
    assert isinstance(up.snapshot, SnapshotData)
    assert up.source == "fake"

def test_baseingester_is_abstract():
    import pytest
    with pytest.raises(TypeError):
        BaseIngester()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_base_ingester.py -v`
Expected: FAIL — modules/fixture missing.

- [ ] **Step 3: Implement DTOs, ABC, and FakeIngester fixture**

```python
# src/clipscore/ingest/__init__.py
```
```python
# src/clipscore/ingest/dto.py
from dataclasses import dataclass

RawCampaign = dict

@dataclass
class SnapshotData:
    budget_total_usd: float | None = None
    budget_spent_usd: float | None = None
    budget_remaining_usd: float | None = None
    active_clippers: int | None = None
    total_views: int | None = None
    success_rate: float | None = None
    engagement: float | None = None

@dataclass
class CampaignUpsert:
    source: str
    external_id: str
    snapshot: SnapshotData
    title: str | None = None
    niche: str | None = None
    cpm_usd: float | None = None
    platform_fee_pct: float | None = None
    cap_per_post_usd: float | None = None
    cap_provenance: str = "absent"
    min_payout_threshold_usd: float | None = None
    min_views_threshold: int | None = None
    budget_total_usd: float | None = None
    allowed_socials: list | None = None
    requirements_raw: str | None = None
    status: str = "active"
    is_verified: bool | None = None
    whop_experience_id: str | None = None
    whop_product_route: str | None = None
    url: str | None = None
    brand: str | None = None
```
```python
# src/clipscore/ingest/base.py
from abc import ABC, abstractmethod
from clipscore.ingest.dto import RawCampaign, CampaignUpsert

class BaseIngester(ABC):
    source_name: str = ""

    @abstractmethod
    def fetch(self) -> list[RawCampaign]:
        ...

    @abstractmethod
    def normalize(self, raw: RawCampaign) -> CampaignUpsert:
        ...
```
Append to `tests/conftest.py`:
```python
import pytest
from clipscore.ingest.base import BaseIngester
from clipscore.ingest.dto import CampaignUpsert, SnapshotData

class FakeIngester(BaseIngester):
    source_name = "fake"
    def __init__(self, raws=None):
        self._raws = raws if raws is not None else [
            {"external_id": "a", "cpm": 1.5, "budget": 1000, "spent": 100, "clippers": 10, "views": 50000},
            {"external_id": "b", "cpm": 2.0, "budget": 500, "spent": 400, "clippers": 40, "views": 90000},
        ]
    def fetch(self):
        return list(self._raws)
    def normalize(self, raw):
        return CampaignUpsert(
            source="fake", external_id=raw["external_id"], title=f"camp {raw['external_id']}",
            niche="gaming", cpm_usd=raw["cpm"], platform_fee_pct=0.1, budget_total_usd=raw["budget"],
            allowed_socials=["tiktok"], status="active",
            snapshot=SnapshotData(
                budget_total_usd=raw["budget"], budget_spent_usd=raw["spent"],
                budget_remaining_usd=raw["budget"] - raw["spent"],
                active_clippers=raw["clippers"], total_views=raw["views"],
            ),
        )

@pytest.fixture
def fake_ingester():
    return FakeIngester()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_base_ingester.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/ingest/__init__.py src/clipscore/ingest/dto.py src/clipscore/ingest/base.py tests/conftest.py tests/test_base_ingester.py
git commit -m "feat: add ingest DTOs, BaseIngester ABC, and FakeIngester"
```

---

### Task 9: Upsert + snapshot + epoch logic

**Files:**
- Create: `src/clipscore/ingest/upsert.py`
- Test: `tests/test_upsert.py`

**Interfaces:**
- Consumes: `Session`, `CampaignUpsert`, models `Campaign`, `CampaignSnapshot`; `utcnow_iso()`.
- Produces:
  - `EPOCH_RESET_RATIO = 1.10` (budget-remaining jump multiplier that triggers a new epoch).
  - `upsert_campaign(session, up: CampaignUpsert, seen_at: str) -> Campaign` — inserts/updates the campaign row (matched on `source`+`external_id`), sets `last_seen_at`, revives `ended`→`active` on reappearance, and writes one `CampaignSnapshot`. Chooses the snapshot `epoch`: same as latest snapshot normally; **latest.epoch + 1** when `budget_remaining` jumps up by more than `EPOCH_RESET_RATIO` vs the latest snapshot in the current epoch, or when the campaign was `ended` and is now active again.
  - `_current_epoch(session, campaign_id, new_remaining) -> int` (helper).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_upsert.py
from clipscore.ingest.upsert import upsert_campaign
from clipscore.ingest.dto import CampaignUpsert, SnapshotData
from clipscore.db.models import Campaign, CampaignSnapshot

def _up(external_id="x", remaining=800.0, total=1000.0, spent=200.0, status="active"):
    return CampaignUpsert(
        source="fake", external_id=external_id, title="t", niche="gaming",
        cpm_usd=1.5, platform_fee_pct=0.1, budget_total_usd=total, status=status,
        snapshot=SnapshotData(budget_total_usd=total, budget_spent_usd=spent,
                              budget_remaining_usd=remaining, active_clippers=10, total_views=1),
    )

def test_insert_then_update_same_row(session):
    c1 = upsert_campaign(session, _up(remaining=800.0), "2026-07-13T00:00:00Z")
    c2 = upsert_campaign(session, _up(remaining=700.0), "2026-07-13T01:00:00Z")
    assert c1.id == c2.id
    assert session.query(Campaign).count() == 1
    assert session.query(CampaignSnapshot).count() == 2
    assert c2.last_seen_at == "2026-07-13T01:00:00Z"

def test_epoch_stays_when_budget_burns_down(session):
    upsert_campaign(session, _up(remaining=800.0), "2026-07-13T00:00:00Z")
    upsert_campaign(session, _up(remaining=600.0), "2026-07-13T01:00:00Z")
    epochs = [s.epoch for s in session.query(CampaignSnapshot).all()]
    assert epochs == [0, 0]

def test_epoch_increments_on_budget_topup(session):
    upsert_campaign(session, _up(remaining=200.0), "2026-07-13T00:00:00Z")
    # remaining jumps 200 -> 900 (>10% up) => new epoch
    upsert_campaign(session, _up(remaining=900.0, total=1500.0), "2026-07-13T01:00:00Z")
    epochs = [s.epoch for s in session.query(CampaignSnapshot).order_by(CampaignSnapshot.id).all()]
    assert epochs == [0, 1]

def test_ended_campaign_revives_and_new_epoch(session):
    c = upsert_campaign(session, _up(remaining=100.0), "2026-07-13T00:00:00Z")
    c.status = "ended"; session.commit()
    upsert_campaign(session, _up(remaining=100.0, status="active"), "2026-07-13T02:00:00Z")
    latest = session.query(CampaignSnapshot).order_by(CampaignSnapshot.id.desc()).first()
    assert latest.epoch == 1
    assert session.get(Campaign, c.id).status == "active"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_upsert.py -v`
Expected: FAIL — `ModuleNotFoundError: clipscore.ingest.upsert`.

- [ ] **Step 3: Implement**

```python
# src/clipscore/ingest/upsert.py
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from clipscore.ingest.dto import CampaignUpsert
from clipscore.db.models import Campaign, CampaignSnapshot

EPOCH_RESET_RATIO = 1.10

def _latest_snapshot(session: Session, campaign_id: str) -> CampaignSnapshot | None:
    return session.execute(
        select(CampaignSnapshot).where(CampaignSnapshot.campaign_id == campaign_id)
        .order_by(CampaignSnapshot.id.desc()).limit(1)
    ).scalars().first()

def _current_epoch(session: Session, campaign_id: str, new_remaining, was_ended: bool) -> int:
    latest = _latest_snapshot(session, campaign_id)
    if latest is None:
        return 0
    if was_ended:
        return latest.epoch + 1
    prev = latest.budget_remaining_usd
    if prev is not None and new_remaining is not None and prev > 0 and new_remaining > prev * EPOCH_RESET_RATIO:
        return latest.epoch + 1
    return latest.epoch

def upsert_campaign(session: Session, up: CampaignUpsert, seen_at: str) -> Campaign:
    existing = session.execute(
        select(Campaign).where(Campaign.source == up.source, Campaign.external_id == up.external_id)
    ).scalars().first()

    was_ended = existing is not None and existing.status == "ended"

    if existing is None:
        campaign = Campaign(
            id=uuid.uuid4().hex, source=up.source, external_id=up.external_id,
            first_seen_at=seen_at, last_seen_at=seen_at,
        )
        session.add(campaign)
    else:
        campaign = existing
        campaign.last_seen_at = seen_at

    # apply mutable fields
    for field in ("title", "niche", "cpm_usd", "platform_fee_pct", "cap_per_post_usd",
                  "cap_provenance", "min_payout_threshold_usd", "min_views_threshold",
                  "budget_total_usd", "allowed_socials", "requirements_raw", "status",
                  "is_verified", "whop_experience_id", "whop_product_route", "url", "brand"):
        setattr(campaign, field, getattr(up, field))

    session.flush()  # ensure campaign.id available

    epoch = _current_epoch(session, campaign.id, up.snapshot.budget_remaining_usd, was_ended)
    session.add(CampaignSnapshot(
        campaign_id=campaign.id, epoch=epoch,
        budget_total_usd=up.snapshot.budget_total_usd,
        budget_spent_usd=up.snapshot.budget_spent_usd,
        budget_remaining_usd=up.snapshot.budget_remaining_usd,
        active_clippers=up.snapshot.active_clippers,
        total_views=up.snapshot.total_views,
        success_rate=up.snapshot.success_rate,
        engagement=up.snapshot.engagement,
        captured_at=seen_at,
    ))
    session.commit()
    return campaign
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_upsert.py -v`
Expected: PASS (all four).

- [ ] **Step 5: Commit**

```bash
git add src/clipscore/ingest/upsert.py tests/test_upsert.py
git commit -m "feat: add upsert with snapshot + epoch-reset logic"
```

---

### Task 10: Ended-sweep gated by harvest sanity check

**Files:**
- Modify: `src/clipscore/ingest/upsert.py` (add `sweep_ended`)
- Test: `tests/test_sweep.py`

**Interfaces:**
- Consumes: `Session`, model `Campaign`; `get_settings()` (for `unseen_polls_to_end`, `harvest_min_campaigns`); `utcnow_iso()`.
- Produces:
  - `sweep_ended(session, source: str, current_ids: set[str], miss_counts: dict[str, int], threshold: int) -> int` — for each `active` campaign of `source`: if its `external_id` is in `current_ids`, reset `miss_counts[external_id]` to 0; otherwise increment it, and when it reaches `threshold` mark the campaign `ended`. Returns the number newly ended. The `miss_counts` dict is the caller-owned debounce state that enforces "N consecutive missed polls."
  - `run_ingest_batch(session, ingester, seen_at: str | None = None, miss_counts: dict[str, int] | None = None) -> dict` — calls `ingester.fetch()`; **if** the fetched count `< harvest_min_campaigns`, returns `{"status": "harvest_too_small", "count": n}` without upserting or sweeping (a bad/partial poll can never mutate state); otherwise normalizes + upserts each raw, then calls `sweep_ended`, and returns `{"status": "ok", "count": n, "ended": m}`. `seen_at` defaults to `utcnow_iso()`; `miss_counts` defaults to a fresh dict.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sweep.py
from clipscore.ingest.upsert import upsert_campaign, sweep_ended, run_ingest_batch
from clipscore.ingest.dto import CampaignUpsert, SnapshotData
from clipscore.db.models import Campaign
from tests.conftest import FakeIngester

def _up(external_id):
    return CampaignUpsert(source="fake", external_id=external_id, title="t", niche="gaming",
        cpm_usd=1.0, platform_fee_pct=0.1, budget_total_usd=100.0, status="active",
        snapshot=SnapshotData(budget_remaining_usd=100.0, active_clippers=1, total_views=1))

def test_sweep_marks_ended_after_threshold(session):
    upsert_campaign(session, _up("a"), "2026-07-13T00:00:00Z")
    upsert_campaign(session, _up("b"), "2026-07-13T00:00:00Z")
    misses = {}
    # "b" missing across 3 polls with threshold 3
    for _ in range(3):
        n = sweep_ended(session, "fake", current_ids={"a"}, miss_counts=misses, threshold=3)
    assert session.get(Campaign, session.query(Campaign).filter_by(external_id="b").one().id).status == "ended"
    assert session.query(Campaign).filter_by(external_id="a").one().status == "active"

def test_sweep_not_triggered_before_threshold(session):
    upsert_campaign(session, _up("a"), "2026-07-13T00:00:00Z")
    upsert_campaign(session, _up("b"), "2026-07-13T00:00:00Z")
    misses = {}
    sweep_ended(session, "fake", current_ids={"a"}, miss_counts=misses, threshold=3)  # 1 miss
    assert session.query(Campaign).filter_by(external_id="b").one().status == "active"

def test_run_batch_skips_sweep_when_harvest_too_small(session, monkeypatch):
    # seed one active campaign
    upsert_campaign(session, _up("a"), "2026-07-13T00:00:00Z")
    # fetch returns 0 campaigns; harvest_min_campaigns default 50 => skip
    empty = FakeIngester(raws=[])
    misses = {}
    result = run_ingest_batch(session, empty, "2026-07-13T01:00:00Z", miss_counts=misses)
    assert result["status"] == "harvest_too_small"
    assert session.query(Campaign).filter_by(external_id="a").one().status == "active"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sweep.py -v`
Expected: FAIL — `sweep_ended` / `run_ingest_batch` not defined.

- [ ] **Step 3: Implement (append to `upsert.py`)**

```python
# append to src/clipscore/ingest/upsert.py
from clipscore.config import get_settings
from clipscore.time import utcnow_iso

def sweep_ended(session: Session, source: str, current_ids: set[str],
                miss_counts: dict[str, int], threshold: int) -> int:
    ended = 0
    actives = session.execute(
        select(Campaign).where(Campaign.source == source, Campaign.status == "active")
    ).scalars().all()
    for c in actives:
        if c.external_id in current_ids:
            miss_counts[c.external_id] = 0
        else:
            miss_counts[c.external_id] = miss_counts.get(c.external_id, 0) + 1
            if miss_counts[c.external_id] >= threshold:
                c.status = "ended"
                ended += 1
    session.commit()
    return ended

def run_ingest_batch(session: Session, ingester, seen_at: str | None = None,
                     miss_counts: dict[str, int] | None = None) -> dict:
    settings = get_settings()
    seen_at = seen_at or utcnow_iso()
    miss_counts = miss_counts if miss_counts is not None else {}
    raws = ingester.fetch()
    if len(raws) < settings.harvest_min_campaigns:
        return {"status": "harvest_too_small", "count": len(raws)}
    current_ids = set()
    for raw in raws:
        up = ingester.normalize(raw)
        upsert_campaign(session, up, seen_at)
        current_ids.add(up.external_id)
    ended = sweep_ended(session, ingester.source_name, current_ids,
                        miss_counts, settings.unseen_polls_to_end)
    return {"status": "ok", "count": len(raws), "ended": ended}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sweep.py -v`
Expected: PASS (all three). Note: `test_run_batch_skips_sweep_when_harvest_too_small` relies on the default `harvest_min_campaigns=50`.

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/clipscore/ingest/upsert.py tests/test_sweep.py
git commit -m "feat: add ended-sweep with harvest sanity gate"
```

---

## Stage 1 Definition of Done

- `pip install -e ".[dev]"` succeeds; `pytest -q` is green.
- `alembic upgrade head` creates all seven tables in a fresh SQLite file; `downgrade base` drops them.
- Seeds load idempotently (contentrewards trust + 8 niche baselines).
- `run_ingest_batch` with a `FakeIngester` produces campaigns + snapshots, increments epochs on budget top-up / revival, and **never sweeps or writes partial data when the harvest is below `harvest_min_campaigns`**.

## Prerequisite note: Phase 0 stable-key spike

The migration in Task 6 sets `UniqueConstraint("source", "external_id")` and treats `external_id` as the stable dedup key. This assumes the spec's **Phase 0 stable-key spike** (two time-separated live fetches of `/discover`) confirms the campaign object's `id` is stable across polls. That spike needs the live page, so it runs at the **start of Stage 2**. If it finds `id` is *not* stable and `whop_experience_id` is the stable key instead, add a one-line follow-up migration repointing the unique constraint to `whop_experience_id` before Stage 2's ingester goes live. Do not skip the spike.

## Handoff to Stage 2

Stage 2 (contentrewards ingester) will: (0) run the Phase 0 stable-key spike above; then implement `ContentRewardsIngester(BaseIngester)` with real `fetch()` (httpx + conditional GET + robots re-check + challenge detection writing `FetchEvent` rows) and `normalize()` (RSC `self.__next_f` payload parse, `category`→niche, regex cap/threshold extraction with `cap_provenance`, `stats.successRate`/`engagement` capture); then wire `run_ingest_batch` into an APScheduler job in a single-process entrypoint. It consumes: `BaseIngester`, `run_ingest_batch`, `SnapshotData`/`CampaignUpsert`, `FetchEvent`, `get_settings()`, `utcnow_iso()`.
