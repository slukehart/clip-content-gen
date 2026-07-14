# Clipping Campaign Value Aggregator — Implementation Plan

## Project Overview

Build a system that aggregates content-clipping campaigns from clipping campaign marketplaces, scores each campaign by **relative expected value** to a clipper, and surfaces the best opportunities via a Discord bot and daily rankings.

**Core insight:** Raw CPM is a misleading signal. Real value depends on budget pool health, payout caps, approval rates, minimum view thresholds, clipper saturation, and platform payout reliability. This system computes a composite Campaign Value Score (CVS) used to **rank and screen** campaigns — not to predict a guaranteed dollar figure. (See "Scoring Formula" and "What the score is and is not" for why the honest framing is a relative score, not an absolute $/hr promise.)

**Owner context:** Solo developer, running on a single small VPS or GCP free-tier e2-micro. Cost ceiling: ~$15/month. Python + SQLite stack.

### Source reality (validated by direct recon, 2026-07)

The initial premise of "three independent sources (contentrewards.com, clipping.net, Whop)" was **wrong** and has been corrected:

- **contentrewards.com _is_ Whop Content Rewards** — the same ecosystem, same backend, same payout rails. It is not a separate source from Whop. It is the **only source with a clean public data path**: a single server-rendered `/discover` page exposing ~525 campaigns inline, no login, no bot protection, `robots.txt` explicitly allows `/discover`, and its own terms contain no anti-scraping clause. It is also the **highest-volume, most-campaigns platform** in the market (independently corroborated by Forbes: ~480k creators, ~1M videos/month, $1M+/mo brand spend, brands incl. Polymarket, ElevenLabs, Call of Duty, Roobet).
- **clipping.net** — a real, comparably-sized peer (Anthony Fujiwara's "Clipping"/"Clipping Exe" operation; Forbes/NPR-covered). **Its ToS §4 explicitly prohibits "using automated tools to access services."** Per our "drop, don't evade" rule it is **out of scope for automated ingestion** unless an authorized path opens.
- **Whop core site & Vyro** — higher headline CPM (Vyro ~$3 flat) but **fully login-walled**; no public campaign data.
- **Whop official developer API** — has **no content-rewards endpoint**; cannot supply competitor campaign economics. Not a path for this data.

**Consequence:** v1 ingests **one public source (contentrewards.com/discover)**, which is a legitimate, representative, market-leading pool of opportunity — not a compromise. The higher-CPM platforms are precisely the ones locked behind login/ToS walls; their headline CPM is also the exact "misleading signal" the CVS exists to see past. Per owner decision, the ingester is built **pluggable** so walled higher-CPM sources (Vyro, clipping.net, Whop) remain a viable future add — see "Source Roadmap."

---

## Tech Stack

- **Language:** Python 3.11+
- **HTTP:** `httpx` (async where useful). For contentrewards.com, a single plain GET retrieves everything — **no browser automation needed.**
- **Scraping fallback:** `playwright` kept behind `ENABLE_PLAYWRIGHT` flag for _future_ walled/JS-only sources **only**. It is **not used for contentrewards.com** — that page virtualizes its DOM (renders ~20 of 525 cards at a time), so a DOM scrape would silently miss most campaigns, whereas the full dataset ships inline in the page's RSC payload. Do not reach for Playwright on this source.
- **Database:** SQLite (WAL mode) via SQLAlchemy 2.x ORM + Alembic migrations. **Why SQLite over Postgres:** the workload is tiny (one ingest batch per 45 min, ~525 campaigns, ~17k snapshot rows/day) and well within SQLite's limits with WAL; it gives zero-config, single-file backups, and one less service to run on a $15/mo box. SQLite's only real weakness — many processes writing at once — is avoided by the **consolidated single-process topology** below. Keeping the SQLAlchemy ORM (and avoiding Postgres-only features like JSONB/native arrays) makes a later migration to Postgres cheap if volume ever demands it.
- **Process topology:** one process hosts the APScheduler jobs, the Discord bot, and (in Pipeline B) the web dashboard as asyncio tasks, so all DB writes are in-process and serialized cleanly — this is what makes SQLite safe here. Do **not** split writers across independent containers all writing the same SQLite file.
- **Scheduling:** APScheduler (in-process cron) — no external queue needed at this scale
- **Bot:** `discord.py` (or Telegram `python-telegram-bot` — build Discord first)
- **Config:** `.env` via `pydantic-settings`
- **Parsing:** stdlib `json` + `re` to extract the Next.js RSC payload (`self.__next_f.push(...)`) from the discover HTML; `selectolax`/`lxml` optional for any HTML scraping of future sources
- **Testing:** pytest
- **Monitoring:** Sentry free tier (optional, stub it), structured logging via `structlog`

Project layout:

```
clipscore/
├── pyproject.toml
├── .env.example
├── alembic/
├── src/clipscore/
│   ├── config.py
│   ├── db/            # models, session, migrations helpers
│   ├── ingest/        # one module per source
│   │   ├── base.py    # BaseIngester + shared upsert/snapshot/epoch/sweep logic
│   │   └── contentrewards.py
│   ├── scoring/       # CVS engine
│   ├── bot/           # Discord bot + alert logic
│   └── jobs/          # scheduler entrypoints
└── tests/
```

---

## Database Schema

**Storage conventions (SQLite).** The tables below use logical types; map them to SQLite physical types as follows, applied uniformly:
- `UUID PK` / foreign keys → **TEXT** (store the UUID as a string).
- `bigserial` / `serial` PK → **INTEGER PRIMARY KEY AUTOINCREMENT**.
- Monetary fields (`*_usd`, `numeric`) → **REAL**. Acceptable because every score is explicitly an *estimate*, not ledgered accounting — this keeps the CVS formula literal (no cents-conversion). Do not use REAL for anything requiring exact accounting.
- Ratio/probability `numeric` (trust_score, p_threshold, success_rate, percentiles) → **REAL**.
- Counts (`integer`, `bigint`) → **INTEGER**.
- `boolean` → **INTEGER** (0/1).
- `text[]` arrays (allowed_socials, and Pipeline B's target_creator/target_platforms) → **TEXT holding a JSON array**. Avoid Postgres-only array/JSONB operators so the ORM stays portable.
- `timestamptz` → **TEXT** storing UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SSZ`); all times are UTC. Enable WAL mode and a busy_timeout at connection setup.

### `campaigns`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| source | text | v1: only `'contentrewards'`. (Whop == contentrewards; do not model as separate.) |
| external_id | text | source's campaign ID; unique(source, external_id) — **verify stability first, see Phase 1** |
| whop_experience_id | text nullable | `exp_...`; candidate stable key / detail link |
| whop_product_route | text nullable | slug for the Whop community page |
| url | text | link to campaign page |
| brand | text | |
| title | text | |
| niche | text | **populated from the source's structured `category` field**, mapped to enum: gaming, podcast, finance, fitness, tech, entertainment, crypto, other. (Keyword classification is a fallback only.) |
| cpm_usd | numeric | gross CPM per 1,000 views (`pricePerView`) |
| platform_fee_pct | numeric | **source-default only** — never exposed per-campaign publicly; taken from `platform_trust.default_fee_pct`. Do not model as a per-campaign scraped field. |
| cap_per_post_usd | numeric nullable | **not a structured field**; regex-extracted from `requirements_raw` when present (e.g. "Max $500/video"). |
| cap_provenance | text | `observed` \| `absent` — distinguishes "genuinely uncapped" from "cap unknown." Never treat unknown as uncapped (see scoring). |
| min_payout_threshold_usd | numeric nullable | regex-extracted from `requirements_raw` when present; partial coverage. |
| min_views_threshold | integer nullable | regex-extracted from `requirements_raw` when present (e.g. "Minimum Floor: 5,000 views"). |
| budget_total_usd | numeric nullable | `totalBudget` |
| allowed_socials | text[] | from `socialPlatforms`: tiktok, reels, shorts, x, facebook |
| requirements_raw | text | full brief/description text — **the source for cap/threshold regex extraction** |
| status | text | active, paused, ended |
| ingest_method | text | `auto` (scraped) \| `manual` (hand-entered). Walled/restricted-source campaigns are entered by hand and are first-class. |
| access_status | text | `ingestable` \| `login_walled` \| `tos_restricted`. Records *why* a source can't be auto-pulled; flips to walled/restricted when a challenge is detected (see `fetch_events`), triggering the switch to manual capture. |
| is_verified | boolean nullable | source `isVerified` flag |
| first_seen_at | timestamptz | |
| last_seen_at | timestamptz | |

### `campaign_snapshots`
Time series powering burn-rate and saturation calculations. This is the **only** way to get trends — no source exposes historical data; we must poll and persist.
| Column | Type | Notes |
|---|---|---|
| id | bigserial PK | |
| campaign_id | UUID FK | |
| epoch | integer | **increments on relaunch/top-up** (see below); burn-rate is computed only within a single epoch |
| budget_total_usd | numeric nullable | captured each poll (to detect resets) |
| budget_spent_usd | numeric nullable | `budgetSpent` |
| budget_remaining_usd | numeric nullable | derived: `budget_total - budget_spent` |
| active_clippers | integer nullable | `creators` |
| total_views | bigint nullable | `viewCount` (cumulative campaign views; approximate, not exact "paid views") |
| success_rate | numeric nullable | source `stats.successRate` — **candidate observed proxy for `p_approval`** (verify meaning in Phase 0); free to capture, pollable |
| engagement | numeric nullable | source `stats.engagement` — capture for future signal use |
| captured_at | timestamptz | |

Index on (campaign_id, epoch, captured_at). **Epoch rule:** when `budget_remaining` jumps up materially or status transitions `ended → active` for the same `(source, external_id)`, start a new epoch; never difference burn-rate across an epoch boundary. **Retention:** ~525 campaigns × ~32 polls/day ≈ 17k rows/day; keep raw snapshots 14 days, hourly-rollup beyond (retention job in Phase 3).

### `fetch_events`
Audit trail of every fetch, so the exact URL and reason are recorded whenever a poll is blocked or challenged. Powers "drop, don't evade" observability.
| Column | Type | Notes |
|---|---|---|
| id | bigserial PK | |
| source | text | |
| url | text | **the exact URL fetched/challenged** |
| event_type | text | `ok` \| `blocked_403` \| `rate_limited_429` \| `captcha` \| `cf_challenge` \| `login_wall` \| `robots_disallow` \| `empty_parse` \| `error` |
| http_status | integer nullable | |
| detail | text | which marker matched (e.g. "Cloudflare cf-chl", "reCAPTCHA script", "redirect to /login") |
| detected_at | timestamptz | UTC ISO |

Index on (source, detected_at). On any non-`ok` challenge/block event: log with URL → **halt that source** → alert in Discord → flip the source's campaigns to `access_status = login_walled│tos_restricted`, which is the trigger to switch that source to manual capture. **Never** solve a CAPTCHA, rotate identity, use proxies, or retry to force through — a challenge means stop.

### `platform_trust`
Hand-seeded, editable table.
| Column | Type | Notes |
|---|---|---|
| source | text PK | |
| trust_score | numeric | 0–1: payout reliability × tracking accuracy |
| default_fee_pct | numeric | |
| notes | text | |

Seed values: contentrewards 0.80 / fee 0.10 (Whop rails; **verify** — reflects real botting-flag/threshold-ban friction documented for this platform, so trust is not maxed). These are starting estimates — flag clearly in code comments that they need verification against current platform terms.

### `niche_baselines`
Hand-seeded expected-views lookup, replaced by learned values later.
| Column | Type |
|---|---|
| niche | text PK |
| e_views_median | integer |
| p_threshold | numeric |

Seed: gaming 10000/0.6, entertainment 12000/0.65, podcast 7000/0.55, finance 5000/0.5, fitness 8000/0.6, tech 6000/0.55, crypto 6000/0.5, other 5000/0.5. **These are the load-bearing guesses that make _cross-niche_ comparison unreliable — see "What the score is and is not."**

### `campaign_scores`
| Column | Type |
|---|---|
| id | bigserial PK |
| campaign_id | UUID FK |
| scored_at | timestamptz |
| net_cpm | numeric |
| capped_earnings | numeric |
| p_threshold | numeric |
| p_approval | numeric |
| p_payout | numeric |
| budget_health | numeric |
| sat_factor | numeric |
| ev_per_clip | numeric |
| cvs_raw | numeric |
| cvs_niche_percentile | numeric | **rank position within the campaign's niche, 0–1** (the primary user-facing signal) |

Store all components, not just the final score, for debuggability.

### `outcomes` (Phase 5, create table now, populate later)
| Column | Type |
|---|---|
| id | bigserial PK |
| campaign_id | UUID FK |
| clips_posted | integer |
| clips_approved | integer |
| actual_views | bigint |
| actual_payout_usd | numeric |
| payout_days | integer |
| logged_at | timestamptz |

---

## Scoring Formula (implement exactly, all constants in config)

```python
# Inputs per campaign
net_cpm = cpm_usd * (1 - platform_fee_pct)         # platform_fee_pct = source default (never per-campaign)
raw_earnings = net_cpm * (e_views / 1000)          # e_views from niche_baselines (GUESS) or learned

# Cap: unknown != uncapped. If cap is absent from the brief, apply a conservative
# default cap (config: DEFAULT_ASSUMED_CAP_USD) rather than infinity, to avoid
# systematically over-scoring high-CPM campaigns whose caps we simply couldn't parse.
if cap_provenance == "observed":
    capped_earnings = min(raw_earnings, cap_per_post_usd)
else:  # "absent" — cap unknown
    capped_earnings = min(raw_earnings, DEFAULT_ASSUMED_CAP_USD)

p_threshold = niche_baselines.p_threshold           # GUESS: share of clips clearing min-view threshold
p_approval  = campaign_learned or DEFAULT_P_APPROVAL # GUESS default 0.7 until Phase 5 learns it
p_payout    = platform_trust.trust_score            # OBSERVED-ish (hand-seeded per platform)

# Budget health: from snapshots over trailing 48h, WITHIN THE CURRENT EPOCH only.  [OBSERVED]
daily_burn = (budget_remaining[t-48h] - budget_remaining[now]) / 2   # USD/day, same epoch
days_left  = budget_remaining_now / daily_burn if daily_burn > 0 else 30
budget_health = min(1.0, days_left / 7)
# If budget_remaining unavailable OR <2 snapshots in epoch: budget_health = 0.7 (neutral)

# Saturation  [OBSERVED]
saturation = budget_remaining_now / max(active_clippers, 1)
sat_factor = min(1.0, saturation / 200)
# If active_clippers unavailable: sat_factor = 0.8

ev_per_clip = (capped_earnings * p_threshold * p_approval
               * p_payout * budget_health * sat_factor)

HOURS_PER_CLIP = 0.75   # configurable
cvs_raw = ev_per_clip / HOURS_PER_CLIP   # internal scalar — NOT surfaced as a $/hr promise
```

**Factor provenance (be explicit in code comments):**
- **Observed** (trustworthy, from the live feed): `cpm_usd`, `budget_health`, `sat_factor`.
- **Guessed** (hand-seeded, constant across campaigns until Phase 5): `e_views`, `p_threshold`, `p_approval`, and the platform-level `p_payout`, `platform_fee_pct`.

Edge cases to handle: null budget, null/absent cap (→ conservative default cap, not infinity), zero/negative burn (budget increased = topped up → **trigger epoch reset**, then treat as healthy), campaign younger than 48h or <2 snapshots in epoch (budget_health = 0.7), CPM of 0 or missing (score = 0, flag for review).

### What the score is and is not

- **Within a niche**, `e_views`, `p_threshold`, `p_approval`, and (single-source) `p_payout` are identical constants, so ranking is driven purely by the **observed** `cpm × budget_health × sat_factor` (± cap). **Within-niche ranking is trustworthy.**
- **Across niches**, placement is scaled by the pure guesses `e_views(niche) × p_threshold(niche)`. A mis-seeded niche baseline spuriously inflates or suppresses a whole category. **Cross-niche absolute comparison is NOT trustworthy in v1.**
- **Caveat on the default cap:** `DEFAULT_ASSUMED_CAP_USD` fixes the unknown→infinity upward bias, but it compresses cap-absent high-CPM campaigns toward a constant, so within-niche ordering among the top campaigns is sensitive to that guessed value. It is a **tuning knob that affects exactly the campaigns most likely to top the board** — so "within-niche ranking is driven purely by observed factors" holds except at this margin.
- Therefore the user-facing output is a **relative screening score**: rank and alert **within niche** (or present top-N per niche), and express alert thresholds as a **percentile of the live distribution**, not an absolute dollar value. `cvs_raw` is retained internally for debugging and Phase-5 calibration but is **never presented as a guaranteed $/hr figure.** Every user-facing surface carries an "estimated screening signal, not a payout prediction" caveat.

---

## Implementation Phases

### Phase 0 — De-risking spike (do before writing the migration)
1. **Stable-key spike:** fetch `contentrewards.com/discover` twice, several hours apart. Confirm which identifier is stable across fetches — the campaign object `id` vs `whopExperienceId`. Choose the stable one as `external_id` (or pin the unique constraint to `whop_experience_id`). This is the one finding that can still change the schema, so resolve it first.
2. **Payload-shape spike:** save a golden copy of the RSC payload as a test fixture; confirm the field set (title, brand, category, pricePerView, totalBudget, budgetSpent, creators, viewCount, `stats.successRate`, `stats.engagement`, socialPlatforms, status, isVerified, whopExperienceId, whopProductRoute) and the `$$`→`$` money-escape quirk.
3. **`successRate` investigation:** inspect what `stats.successRate` and `stats.engagement` actually contain across campaigns — is `successRate` an approval rate, a view-threshold-clear rate, or something else? Do not assume it maps to `p_approval`; verify. This is decision-relevant because a real per-campaign success signal would move `p_approval` (and possibly `p_threshold`) from **guessed** to **observed**, which is one of the only levers that could make cross-niche comparison trustworthy before the Phase-5 feedback loop accrues data.

**Acceptance:** stable dedup key confirmed with evidence from two time-separated fetches; golden fixture saved; meaning of `stats.successRate`/`engagement` documented.

### Phase 1 — Foundation
1. Scaffold project layout above; pyproject with pinned deps.
2. Alembic migration creating all tables above (schema above, using the Phase-0-confirmed key).
3. `config.py` with pydantic-settings: DB URL, poll interval (default 45 min), scoring constants (incl. `DEFAULT_ASSUMED_CAP_USD`, `DEFAULT_P_APPROVAL`, `HOURS_PER_CLIP`), alert **percentile**, Discord token, feature flags (`ENABLE_PLAYWRIGHT` default off).
4. Seed script for `platform_trust` (contentrewards only) and `niche_baselines`.
5. `BaseIngester` abstract class: `fetch() -> list[RawCampaign]`, `normalize(raw) -> CampaignUpsert`, and shared logic kept concrete and reusable: upsert (match on stable key; update last_seen_at; insert snapshot each poll; **epoch increment on budget reset/relaunch**; **ended-sweep gated by harvest sanity check** — see Phase 2). Keep the abstraction lightweight; its job is to make the walled sources in "Source Roadmap" cheap to add later, not to over-generalize now.

**Acceptance:** `alembic upgrade head` works; seeds load; unit tests pass for upsert, epoch-reset, and sanity-gated ended-sweep logic with fixture data.

### Phase 2 — First ingester: contentrewards.com
1. **Compliance gate (runtime, not one-time):** on every poll, fetch and check `robots.txt`; if `/discover` becomes disallowed, **auto-halt the source** and alert. Record the initial compliance check (robots allows `/discover`; site's own ToS has no anti-scraping clause) in the module docstring with date. Read only the already-served public page; never probe `/api/` (disallowed + ToS bars reverse-engineering).
2. **Challenge/block detection:** classify every response before parsing — 403/429/503, CAPTCHA/Cloudflare/DataDome/PerimeterX body markers, login redirects. On any challenge/block, write a `fetch_events` row with the exact URL and marker, **halt the source, alert in Discord, and flip its campaigns to walled/restricted `access_status`** (→ manual capture). Never solve challenges, rotate identity, use proxies, or force retries. This is the runtime enforcement of "drop, don't evade."
3. **Fetch:** single `httpx` GET of `/discover` with an honest User-Agent and **conditional GET** (`If-None-Match`/ETag) to skip re-downloading ~8 MB when unchanged. No Playwright.
4. **Parse:** extract the `self.__next_f.push(...)` RSC payload, decode the campaign objects, handle the `$$`→`$` money quirk.
5. **Harvest sanity check:** if a poll yields 0 or implausibly few campaigns (config threshold, e.g. <50 when ~525 is normal), treat it as a **fetch/parse failure** — log/alert, **do not** write partial snapshots as authoritative, and **skip the ended-sweep** so a bad parse can never mass-flip campaigns to `ended`.
6. **Normalize:** map structured `category` → niche enum; regex-extract cap/min-views/min-payout from `requirements_raw`, setting `cap_provenance`; capture snapshot fields. Survive a malformed campaign entry without crashing the batch (log + skip).
7. **Rate limiting:** one request per 45-min cycle is already trivially polite (~32/day); exponential backoff on 429/5xx.
8. Wire into APScheduler job.

**Acceptance:** After two poll cycles, `campaigns` has rows with correct fields (niche from `category`, caps flagged by provenance) and `campaign_snapshots` has ≥2 snapshots per active campaign. A simulated malformed entry is skipped; a simulated empty/partial poll does **not** trigger the ended-sweep or write bad snapshots.

### Phase 3 — Scoring engine
1. `scoring/engine.py` implementing the formula verbatim, pure functions, fully unit-tested including all edge cases (capped-observed vs cap-absent-default, missing budget, topped-up budget → epoch reset, young campaign, zero CPM).
2. Scoring job runs after each ingest cycle, writes `campaign_scores` rows including `cvs_niche_percentile`.
3. **Evaluate `stats.successRate` as an observed input** to `p_approval` (and/or `p_threshold`), based on the Phase-0 investigation of what it means. If it is a genuine per-campaign success/approval signal, wire it in to replace the guessed constant for that factor — resolve this here, before the formula is finalized, not in Phase 5.
4. Snapshot **retention/rollup job** (raw 14 days, hourly beyond).
5. CLI command: `python -m clipscore.jobs.rank --top 10 [--niche gaming]` prints ranked table (rich/tabulate) with the **within-niche** screening score and component breakdown, labeled as an estimated screening signal.

**Acceptance:** Unit tests cover all listed edge cases. CLI shows a sensible within-niche ranking against live data. **Cold-start expectation documented:** for the first ~48h, `budget_health`/`sat_factor` fall back to neutral defaults, so early rankings are low-signal.

### Phase 4 — Discord bot
1. Bot with two functions: (a) alert channel post when a newly scored campaign lands in the **top percentile of its niche's live distribution** (`ALERT_PERCENTILE`, default top 10%), dedup so each campaign alerts once; (b) `/top [niche]` slash command returning the current within-niche top 10 with screening scores and links. **Two percentile edge behaviors to handle:** (i) percentile alerts fire on the *relatively* best ~10% of a niche regardless of absolute quality — they are not a quality gate; label them as such. (ii) Small niches (e.g. podcast may have only a handful of live campaigns) make "top 10%" degenerate — enforce a `MIN_NICHE_SAMPLE` floor below which alerts are suppressed (or the niche shows all campaigns) rather than emitting noise.
2. Daily 9am ET summary post: top per-niche, plus "biggest movers" (largest CVS-percentile delta in 24h).
3. Every message carries the "estimated screening signal, not a payout prediction" caveat. Bot must degrade gracefully if Discord is down — never block ingest/scoring.

**Acceptance:** Alerts fire on percentile-crossings exactly once per campaign; `/top` responds under 3s.

### Phase 5 — Feedback loop (scaffold only for now)
1. CLI to log outcomes: `python -m clipscore.jobs.log-outcome --campaign <id> --clips 5 --approved 4 --views 42000 --payout 96.50`.
2. Weekly recalibration job: where a campaign has ≥5 logged clips, override `p_approval` with observed rate; where a niche has ≥20 logged clips, update `niche_baselines.e_views_median` with rolling median (this is what eventually makes cross-niche comparison trustworthy).
3. **Do NOT** derive per-campaign `e_views` from `viewCount / creators` — unit mismatch (views-per-clipper vs per-clip) and `viewCount` is cumulative, so the ratio rewards campaign age, not value. Only an age-normalized version is a candidate here, if ever.

**Acceptance:** Logged outcomes visibly shift subsequent scores.

---

## Source Roadmap (walled higher-CPM sources)

v1 is single-source by necessity, but the `BaseIngester` seam exists so these can be added when a legitimate path opens. Each carries its own access and ToS posture — **document and respect per source; do not evade:**

| Source | Why wanted | Access path | ToS / legal posture |
|---|---|---|---|
| **Vyro** | Highest headline CPM (~$3), marquee brands | Login-walled; would require the owner's **own authenticated session** reading campaigns they're a member of | Check Vyro ToS before building; authenticated own-account reading ≠ bypassing auth, but confirm it's permitted |
| **clipping.net** | Deepest budgets, large operation | Login-gated depth; ~60 public headline pages | **ToS §4 bans automated access outright** — do not ingest even authenticated unless terms change or written consent obtained |
| **Whop (core)** | Broader marketplace | Login wall; API has no content-rewards endpoint | `whop.com/terms` bans scraping; own-session reading is the only conceivable path and still ToS-gray — legal review before building |

Owner decision: keep these viable via the pluggable design. Implementing any of them is a deliberate, per-source decision that must clear its ToS check first — the abstraction makes it cheap to add, not automatically sanctioned.

---

## Constraints & Non-Goals

- **Compliance:** Robots.txt is re-checked at **runtime** every poll (auto-halt on disallow), not just once. Every response is classified for challenges/blocks (403/429, CAPTCHA, Cloudflare/DataDome, login redirect); any challenge is **logged to `fetch_events` with the exact URL, halts the source, and alerts** — never solve, evade, proxy, or force through. Do not bypass auth walls, CAPTCHAs, or bot-detection; polite rate limits are mandatory. When a source becomes inaccessible (blocked, walled, or ToS-restricted — e.g. clipping.net, whose ToS forbids automated access), it drops out of automated ingestion and moves to **manual capture** (`ingest_method='manual'`): campaigns are hand-entered and still flow into scoring and Pipeline B. Manual capture never automates access to a restricted source.
- **No proxies** in v1. If blocked at polite rates, drop the source.
- **No web frontend** in v1. CLI + Discord only.
- **No auto-posting or auto-clipping.** This system ranks campaigns; it does not create content or interact with campaign platforms on the user's behalf.
- **The score is a relative screening signal, not a payout prediction.** Every user-facing number carries that caveat. Cross-niche absolute comparison is explicitly not trustworthy until Phase 5 learns real baselines.
- **Single-box deployment.** Everything runs on one VPS via systemd or a single `docker compose up`. Provide the compose file.

## Definition of Done (v1)
- The single public source (contentrewards.com/discover) ingesting reliably for 7 consecutive days without manual intervention, including surviving at least one empty/partial-poll event without corrupting state
- Scores recomputed every cycle with full component storage and within-niche percentiles
- Discord alerts (percentile-based) + `/top` + daily summary working
- Outcome logging CLI functional
- **Scoring-validity spot-check:** manually compare a handful of top-ranked campaigns against human judgment and confirm the ranking is sensible before declaring done (plumbing working ≠ scores meaningful)
- README covering setup, .env, deployment on a $6 VPS, the honest "screening score" framing, and how to add a new ingester (with the Source Roadmap ToS caveats)
