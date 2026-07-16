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

**Status (2026-07-16) — built & operational.** Pipeline A Stages 1–4 and **Pipeline B
Stages B1–B5 are merged**, plus post-B5 dashboard usability features. **The real Vizard
integration is proven end-to-end** (manual-acceptance run 2026-07-15): a `/manual` campaign
ran the full `queued→acquired→produced→matched` lifecycle — the passthrough bridge sent a
public YouTube URL to the URL-only Vizard API (no download), Vizard returned ~10 ranked
vertical clips, all downloaded as valid MP4s, each matched its origin campaign with an `#ad`
caption. The rewritten `factory/clip/vizard.py` is correct against the live API; wire
details are in the `vizard-api-contract` memory.

- **B5 — cost & retention hardening (merged):** monthly **credit** cap
  (`CLIPSCORE_MONTHLY_CAP_CREDITS`; 1 credit = 1 minute of *source* video) that sends a job to
  a new **`blocked`** status *before* the paid Vizard call when the ET-month projection would
  exceed it; raw `creditsUsed` persisted on `clip_jobs`; clip retention (`clipscore prune` +
  delete-on-post + age sweep); **`clipscore process`** — on-demand job drain (the fix for
  "web queues but nothing runs"); Vizard virality params (subtitles/hooks/9:16, config
  toggles); migration **`0007`** (`est_minutes`, `credits_used`, `clip_matches` unique).
- **Post-B5 dashboard (merged):** paste a source URL on any ranked row to clip it (the
  "Clip" input replaces the old "no acquirable source" dead-end); campaign **titles link to
  the per-campaign Whop deep link** `{whop_product_route}/{whop_experience_id}/app/` (Whop
  resolves the route→slug redirect itself); a **credits-used-vs-cap** readout on the board;
  a **niche lane filter** (`CLIPSCORE_TARGET_NICHES`, comma list) that restricts rank + the
  dashboard to your lane — **non-destructive** (other niches stay in the DB, survive
  re-polls; empty = all).

**Source-grabbing is inherently manual — the designed norm, not a bug.** Real campaigns are
dominantly "clip a source video"; the operator supplies the public source URL (paste it on a
dashboard row, use `/manual`, or `clipscore clip <id> --source-type passthrough --source-ref
URL`). Extraction auto-discovers a source for ~0% of campaigns (sources are gated behind
joining the campaign). See the `clipping-campaign-source-shapes` and `whop-marketplace-mechanics`
memories.

## Operating model (how this earns)

The marketplace is **Whop** (campaigns ingested from ContentRewards, which is a Whop app;
payout via Whop Payments). Two campaign host shapes: **single-creator whops** (join → that
one campaign) and **aggregator/community whops** (join → a Discord + many campaigns; the
specific campaign lives at the `…/{exp}/app/` deep link). One join can unlock several
campaigns. The system **ranks and produces; the human joins, posts, and submits** — there is
no auto-posting. The daily loop: `clipscore rank` (your lane) → open a ranked campaign's Whop
page and **join** it → copy its public source URL → paste it on the dashboard row (or
`clipscore clip … --source-ref`) → `clipscore process` → review at `clipscore web` → post to
your own account per the campaign's caption rules → **submit the post link in Whop** →
`mark posted`. Captions: Vizard burns in the on-screen subtitles; the post caption is a
deterministic `#ad`-guaranteed floor, optionally LLM-enriched (`CLIPSCORE_LLM_API_KEY`,
optional). Economics + Vizard plan sizing are in the `vizard-api-contract` memory (credits =
source minutes; no per-clip or trim lever).

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
  cli.py             # single argparse CLI (setup/poll/rank/smoke/bot/extract/clip/web/process/prune)
  db/                # base.py, models.py, session.py (WAL pragmas)
  ingest/            # Pipeline A: base.py (ingester ABC), dto.py, upsert.py, detect.py
  scoring/           # Pipeline A: CVS scoring + board (eligible_latest_scores)
  bot/               # Pipeline A Stage 4: Discord alert/summary logic + discord_bot.py
  factory/           # Pipeline B: extract*, enrich, whop, llm, acquire/, clip/
                     #   clip/: base, produce, match, caption, videotype, vizard,
                     #   cost (credit accounting), retention (clip prune)
  jobs/              # Pipeline B: poll.py (scheduler), clipfactory.py (clip-job runner),
                     #   drain.py (clipscore process)
  web/               # Pipeline B4: FastAPI dashboard — app.py, queries.py, warnings.py,
                     #   actions.py, templates/ (Jinja2 + HTMX), static/
alembic/             # env.py + versions/ (0001 … 0007_b5_cost_retention.py)
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
clipscore clip <campaign_id> [--source-type --source-ref --source-minutes N]   # queue a clip-factory job
clipscore process [--once]   # drain in-flight clip jobs to a terminal status (once = single pass)
clipscore prune              # delete clip files older than CLIPSCORE_CLIP_RETENTION_DAYS
clipscore web [--host 127.0.0.1] [--port 8000]   # run the local review dashboard (Pipeline B4)
```

**Job lifecycle:** `clipscore web`/`clipscore clip` only *enqueue* a `ClipJob`. Advancing it
(`queued→acquired→produced→matched`, or `blocked` on the cost cap) happens via **`clipscore
process`** (on demand) or the `bot` scheduler (interval). `process_clip_jobs` advances each
job one stage per pass; `clipscore process` loops until nothing is advanceable.

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
- **Operational (B5 / dashboard) vars:** `CLIPSCORE_VIZARD_API_KEY` (required for real clip runs),
  `CLIPSCORE_CLIP_ENGINE` (default `vizard`; `fake` in CI), `CLIPSCORE_MONTHLY_CAP_CREDITS`
  (0 = uncapped), `CLIPSCORE_VIZARD_USD_PER_CREDIT` (for $ display; cap itself is credit-based),
  `CLIPSCORE_CLIP_RETENTION_DAYS` (14), `CLIPSCORE_TARGET_NICHES` (comma list; empty = all),
  `CLIPSCORE_LLM_API_KEY` (optional — LLM caption/extraction; floor works without it),
  `CLIPSCORE_CLIP_JOBS_PER_TICK` (5).
- **Tests must be hermetic:** construct `Settings(_env_file=None, …)` in tests so the developer's
  live `.env` (e.g. `CLIPSCORE_TARGET_NICHES`) can't leak in and change results.

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
