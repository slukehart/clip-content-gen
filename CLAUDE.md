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

**Status (2026-07-15):** Pipeline A Stages 1–4 are merged. **Pipeline B Stages B1–B4 are
merged** — B1 (schema + LLM extraction), B2 (acquisition), B3 (clip production + matching +
captions), B4 (FastAPI review dashboard, `clipscore web`). The full `queued→ready` lifecycle
runs end-to-end on the CI `FakeClipEngine`. Remaining: **B5** (cost cap / retention
hardening) and real-integration acceptance.

**Manual-acceptance findings (2026-07-15) — the real integrations are NOT yet proven:**
- **The committed Vizard adapter (`factory/clip/vizard.py`) is wrong** and does not work
  against the live API — it never sends the required `videoType`, polls the wrong
  status codes, reads `clips` (real field is `videos`), and treats `preferLength` as
  seconds. A live probe established the real contract; the next build is a **minimal
  Vizard passthrough bridge** (send the public `source_url` + correct `videoType`
  straight to the URL-only Vizard API; it returns N ranked vertical clips of its own
  choosing, not one clip per spec). See `PIPELINE_B_CLIP_FACTORY.md` and the
  `vizard-api-contract` memory.
- **Source-grabbing is inherently manual.** Real campaigns are dominantly "clip a source
  video" and the operator supplies the public source URL (via B4's `/manual`); extraction
  auto-discovers a content-bank URL for ~0% of campaigns (links are gated behind joining).
  This is the marketplace's shape, not a bug.

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
pytest / pytest-asyncio · APScheduler + discord.py (Pipeline A Stage 4) · httpx (B2/B3
acquisition, LLM, Vizard) · FastAPI + uvicorn + Jinja2 + python-multipart (B4 dashboard,
server-rendered + vendored HTMX) — **all wired.** `yt-dlp` is an optional extra (VOD
acquirers only, lazy-imported). LLM calls go through a provider-agnostic OpenAI-compatible
client (default OpenRouter + `moonshotai/kimi-k2`); no vendor SDK.

## Repository layout

```
src/clipscore/
  config.py          # Settings (pydantic-settings) — env-driven config
  time.py            # time helpers (utcnow_iso, et_month_bounds_utc)
  seed.py            # seed data
  cli.py             # single argparse CLI (setup/poll/rank/smoke/bot/extract/clip/web)
  db/                # base.py, models.py, session.py (WAL pragmas)
  ingest/            # Pipeline A: base.py (ingester ABC), dto.py, upsert.py, detect.py
  scoring/           # Pipeline A: CVS scoring + board (eligible_latest_scores)
  bot/               # Pipeline A Stage 4: Discord alert/summary logic + discord_bot.py
  factory/           # Pipeline B: extract*, enrich, whop, llm, acquire/, clip/
  jobs/              # Pipeline B: poll.py (scheduler), clipfactory.py (clip-job runner)
  web/               # Pipeline B4: FastAPI dashboard — app.py, queries.py, warnings.py,
                     #   actions.py, templates/ (Jinja2 + HTMX), static/
alembic/             # env.py + versions/ (0001 … 0006_add_outcome_clip_id.py)
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
clipscore extract [--report]   # Pipeline B incremental LLM/Whop enrich sweep (--report = coverage spike)
clipscore clip <campaign_id> [--source-type --source-ref]   # queue a clip-factory job
clipscore web [--host 127.0.0.1] [--port 8000]   # run the local review dashboard (Pipeline B4)
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
