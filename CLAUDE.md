# CLAUDE.md

Guidance for Claude Code (and any agent) working in this repository.

## What this project is

**`clipscore`** — a personal two-pipeline system for finding the best content-clipping
campaigns and turning them into review-ready clips. See [`README.md`](README.md) for the
full pitch; the two design docs below are the source of truth for architecture.

- **Pipeline A — Deal Finder** ([`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md))
  Ingests campaigns from a public marketplace, stores time-series snapshots, and computes
  a **Campaign Value Score (CVS)** — a *relative, within-niche screening signal*, not a
  guaranteed $/hr prediction. Surfaces results via a Discord bot and ranked CLI output.
- **Pipeline B — Clip Factory** ([`PIPELINE_B_CLIP_FACTORY.md`](PIPELINE_B_CLIP_FACTORY.md))
  For approved campaigns, acquires source footage, sends it to a hosted clipping engine,
  matches finished clips back to live campaigns, and presents a local review dashboard.

**Status:** Pipeline A Stages 1–4 are merged (foundation, ingester, scoring, Discord bot —
see [`plans/`](plans/)). The bot runs end-to-end (`clipscore bot`). Pipeline B is not yet
started.

## Non-negotiable principles

These are product constraints, not preferences — do not violate them when writing code:

- **Compliance first.** Respect `robots.txt` and each source's terms. On a block/challenge,
  log the URL and **drop the source — never evade** (no header spoofing to circumvent, no
  CAPTCHA solving). Sources that forbid automated access are handled by manual capture.
- **No auto-posting, no multi-account automation.** The system ranks and produces; the
  human posts, one account per platform.
- **Honest scoring.** Every user-facing number is an estimated screening signal, not a
  payout guarantee. Track observed vs. guessed factors separately.
- **Small footprint.** Python + SQLite, single-process, single small box.

## Tech stack

Python 3.11+ · SQLite (WAL) · SQLAlchemy 2.x + Alembic · pydantic-settings · structlog ·
pytest / pytest-asyncio · APScheduler + discord.py (Pipeline A Stage 4, wired).
(Planned, not yet wired: httpx, FastAPI.)

## Repository layout

```
src/clipscore/
  config.py          # Settings (pydantic-settings) — env-driven config
  time.py            # time helpers
  seed.py            # seed data
  db/                # base.py, models.py, session.py (WAL pragmas)
  ingest/            # base.py (ingester ABC), dto.py, upsert.py
alembic/             # env.py + versions/ (0001_initial.py)
tests/               # pytest suite, conftest.py builds tables from ORM models
plans/               # phased build briefs (subagent-driven-development)
IMPLEMENTATION_PLAN.md      # Pipeline A design (source of truth)
PIPELINE_B_CLIP_FACTORY.md  # Pipeline B design (source of truth)
```

## Dev setup & commands

```bash
python3 -m pip install -e ".[dev]"   # install with dev extras
pytest -q                            # run the test suite
alembic upgrade head                 # apply migrations
alembic revision --autogenerate -m "msg"   # new migration
```

Tests use `pythonpath = ["src"]` (see `pyproject.toml`), so `import clipscore` works without
installing. `tests/conftest.py` registers the ORM models and creates tables for fixtures.

The installed entrypoint is a single CLI (`[project.scripts]` → `clipscore.cli:main`):

```bash
clipscore setup          # create tables + load seeds (platform_trust, niche_baselines)
clipscore poll           # one ingest+score cycle against the configured DB
clipscore rank [--top N] [--niche X]   # ranked CLI output
clipscore smoke [db]     # live capture check into a throwaway DB
clipscore bot            # run the Discord bot (see below)
```

## Running the Discord bot

Pipeline A Stage 4. Decision logic (alert selection, dedup, formatting, movers) lives in
`src/clipscore/bot/` and is fully CI-tested with a fake notifier; `bot/discord_bot.py` is a
thin `discord.py` adapter that is manual-acceptance-only (real token + network, never in CI).
`clipscore bot` connects, syncs the `/top` slash command, and schedules the poll+alert cycle
and the daily 9am-ET summary. A Discord failure can never break ingest/scoring.

**Env vars (in `.env`, `CLIPSCORE_` prefix):**

| Var | Required | Purpose |
|-----|----------|---------|
| `CLIPSCORE_DISCORD_TOKEN` | yes | Bot token from the Developer Portal → **Bot → Reset Token**. |
| `CLIPSCORE_DISCORD_ALERT_CHANNEL_ID` | for alerts | **Channel** ID (not the application ID) where alerts + daily summary post. If unset, sends silently no-op; `/top` still works. Get it via Discord client → Developer Mode → right-click channel → Copy Channel ID. |
| `CLIPSCORE_ALERT_PERCENTILE` (0.90), `CLIPSCORE_MIN_NICHE_SAMPLE` (5), `CLIPSCORE_SUMMARY_HOUR_ET` (9), `CLIPSCORE_POLL_INTERVAL_MINUTES` (45) | no | Tuning; defaults in `config.py`. |

The bot uses `discord.Intents.default()` — **no privileged intents** (do not enable Message
Content / Members / Presence). Install to a server with the OAuth2 scopes `bot` +
`applications.commands` and the **View Channels** + **Send Messages** permissions.

**macOS SSL gotcha (bites first run on a fresh machine):** python.org's Python ships with no
CA bundle wired to OpenSSL, so the bot's HTTPS connection to `discord.com` fails with
`SSLCertVerificationError: CERTIFICATE_VERIFY_FAILED — unable to get local issuer certificate`.
This is **not** a bad token — it reaches the host and fails only on cert verification. Fix once
per Python install:

```bash
"/Applications/Python 3.12/Install Certificates.command"
# verify: python3 -c "import ssl; print(ssl.get_default_verify_paths().cafile)"  # must be non-None + exist
```

## Configuration & secrets

- Runtime config is defined in **`src/clipscore/config.py`** via `Settings` (pydantic-settings).
- Env vars use the prefix **`CLIPSCORE_`** and load from a local **`.env`** file
  (e.g. `CLIPSCORE_DB_URL`, `CLIPSCORE_DISCORD_TOKEN`, `CLIPSCORE_POLL_INTERVAL_MINUTES`).
- **`.env` is gitignored** — never commit real secrets. `.env.example` is the committed template.
- `.db` / `.sqlite` files and downloaded media (`media/`, `clips/`, `*.mp4`, …) are gitignored.

## Where permissions live (Claude Code)

Claude Code tool-permission settings for this repo are under **`.claude/`**. Two files,
loaded in order (later overrides earlier): **user (`~/.claude`) → project → local**.

| File | Scope | Git | Notes |
|------|-------|-----|-------|
| `.claude/settings.json` | Project, team-wide | **committed** | Holds `permissions.defaultMode` (currently `bypassPermissions`). Not touched by the permission auto-recorder — edit here for durable changes. |
| `.claude/settings.local.json` | Personal, this machine | **gitignored** | Holds the auto-accumulated `permissions.allow` list. Rewritten by Claude Code whenever a tool approval is recorded. |

To inspect or change permissions:
- **Durable / effective mode** → `.claude/settings.json` (`permissions.defaultMode`).
- **Per-command allow rules** → `.claude/settings.local.json` (`permissions.allow`).
- Interactively → the `/permissions` command, or `Shift+Tab` to cycle permission modes.

**Multi-session gotcha (important):** more than one Claude Code session can run against this
same working tree at once. Each session **rewrites the entire `settings.local.json`** from
its own in-memory state every time it records a newly-approved tool. So edits to
`settings.local.json` made by one session get clobbered by another that is still discovering
and approving new commands. Put anything that must survive in `settings.json` instead — the
auto-recorder never writes that file. (Once `defaultMode` is `bypassPermissions`, approvals
stop being prompted, so nothing new is recorded.)
