# Pipeline B — Clip Factory (Design Spec)

> Companion to `IMPLEMENTATION_PLAN.md` (Pipeline A — Deal Finder). Pipeline A ranks campaigns by value; **Pipeline B turns the best-ranked campaigns into a review-ready queue of finished clips matched to campaigns**, so the operator does only the manual revenue step (posting). Shares Pipeline A's repo, SQLite database, and single-process topology.

**Date:** 2026-07-13

---

## Purpose & boundary

Pipeline B automates the labor of clip production and leaves the operator in control of spend and of what gets posted. It **does not post** — posting stays manual and human, which is the deliberate line that keeps the operator's accounts clear of the automated-multi-account behavior that triggers payout-platform bans (see Compliance).

**The loop:** A ranks campaigns → operator approves a campaign in the dashboard → B acquires the creator's footage → hands it to a hosted clipping engine → matches finished clips back to all live campaigns → presents a review queue with the best-matched campaign, its requirements, and a suggested caption → operator watches, posts manually, marks posted (logged to A's `outcomes`, closing the ROI loop).

## Locked decisions (from brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Trigger model | **Suggest → operator approves → auto-produce** (Approach 1) | Connects A's rankings to B's queue; spend accrues only on approved campaigns; output is stuff the operator intends to post |
| Source footage | **Creator VODs (Twitch/YouTube/Kick) + campaign-provided + long-form URL** | Matches how clipping actually works; pluggable acquisition layer |
| Clip engine | **Vizard.ai** (hosted AI clip API) behind `BaseClipEngine` | Verified vs official docs: real REST API; accepts uploaded-file **and** YouTube/Twitch/Drive/Vimeo URLs; AI highlight detection; API-controllable 9:16 / length / burned captions / face-reframe; returns clip files + transcript + `viralScore`. Klap = fallback adapter; OpusClip = third; hybrid self-host = future seam |
| Review handoff | **Local web dashboard** | Inline video review with matched campaign + requirements + caption |
| Volume | **~15 clips/day** (~300–450/mo) | Right-sized: ≈ the max one manual poster can post (one account/platform, ~10–15/day across platforms) **and** ≈ the max the budget buys on a managed API. 20–75/day overshoots both. |
| Budget (B) | **~$70–115/mo** on Vizard (separate from A's ~$15/mo) | Vizard bills by **source upload-minutes** (~6–10 min per usable clip), not per clip. Confirm the exact >600-min/mo rate with a real quote in B0. Cost lever = source-minutes processed → be selective about which/how-long VODs get fed in. |
| Posting | **Manual, one account per platform, cross-posted** | Compliant, sustainable; no multi-account plumbing |
| DB / topology | **SQLite (WAL), consolidated single process** | Inherited from Pipeline A |

---

## Architecture

New package `src/clipscore/factory/`. Heavy video work is offloaded to the hosted clip engine, so B is an orchestrator of background jobs plus a small control/review UI. Components:

1. **Target extraction** (extends A's `normalize`): parse `requirements_raw` to pull each campaign's *target creator/source* and *clip specs* (platform, min/max length, aspect, caption/handle rules, banned content). Nullable + provenance-flagged, same partial-coverage discipline as A's cap/threshold extraction.
2. **Acquisition layer** (`factory/acquire/`, pluggable `BaseAcquirer` mirroring A's `BaseIngester`): per-source-type modules — `twitch`, `youtube`, `kick`, `campaign_provided`, `url` — using `yt-dlp` into object storage. Each carries its own ToS gate and drop-don't-evade behavior.
3. **Clip-engine client** (`factory/engine/`, pluggable `BaseClipEngine`): submit a source video + spec, poll, download finished clips. First adapter **Vizard** (`videoUrl` + `videoType`, `ratioOfClip:1`, `preferLength`, `subtitleSwitch`, `maxClipNumber`; returns `videoUrl`/`transcript`/`viralScore`/`duration`); Klap fallback adapter; vendor swappable behind the interface.
4. **Matching** (`factory/matching.py`): for each finished clip, find every live campaign whose target creator + platform + specs it satisfies, rank by A's CVS niche-percentile × spec-fit.
5. **Caption generation** (`factory/captions.py`): LLM-suggested caption per (clip, campaign) from the clip transcript + campaign rules.
6. **Web dashboard** (`factory/web/`, FastAPI + lightweight templates/htmx): the *approval* surface (A's top campaigns + "Clip this"), the *review* surface (watch clip inline, ranked matched campaigns + requirements + caption, download, mark-posted), a *manual-entry form* for walled-source campaigns, and *cost/compliance* readouts.

APScheduler drives the job stages as asyncio tasks in the same process as A's poller/scorer and the Discord bot. Runs on a modest box (not A's e2-micro) with cheap object storage (R2/S3), short retention.

## Data flow (happy path)

```
A ranks campaigns + extracts target creator/specs
        │
        ▼
Operator clicks "Clip this" on a top campaign  ──►  clip_job(queued)   [est_cost shown at click]
        │
        ▼  acquire job
Resolve creator's latest VOD / provided file / URL → download → source_asset  (deduped)
        │
        ▼  clipping job
Submit source_asset to clip engine (per-platform length variants) → poll → download → clip rows (produced)
        │
        ▼  matching job
For each clip: find all live campaigns matching creator+platform+specs, rank by CVS → clip_match rows
        │
        ▼  caption job
Generate suggested caption for top match(es)
        │
        ▼
Clip in review queue (ready) → operator watches, picks ONE campaign, downloads, posts manually
        │
        ▼  "mark posted"
Logs to A's outcomes table (closes the ROI/cost loop)
```

---

## Data model (added to Pipeline A's SQLite schema)

Follows Pipeline A's **Storage conventions** (UUID→TEXT, money→REAL, arrays→JSON TEXT, timestamps→UTC ISO TEXT, serial→INTEGER PK AUTOINCREMENT, boolean→INTEGER).

### `clip_jobs`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| campaign_id | TEXT FK | the campaign the operator approved |
| source_type | TEXT | `twitch` \| `youtube` \| `kick` \| `campaign_provided` \| `url` |
| source_ref | TEXT | creator handle / URL / provided-file ref |
| status | TEXT | `queued` \| `acquiring` \| `acquired` \| `clipping` \| `produced` \| `matched` \| `failed` |
| est_cost_usd | REAL | shown at approval time |
| error | TEXT nullable | failure reason (surfaced in dashboard) |
| created_at | TEXT | UTC ISO |

### `source_assets`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| clip_job_id | INTEGER FK | |
| creator | TEXT | |
| platform | TEXT | origin (twitch/youtube/kick/url/provided) |
| source_url | TEXT | |
| authorizing_campaign_id | TEXT FK | the campaign whose authorization justifies acquiring this creator's content |
| storage_uri | TEXT | object-storage location |
| duration_s | INTEGER | |
| bytes | INTEGER | |
| downloaded_at | TEXT | UTC ISO |

**Dedup:** reuse a recent `source_asset` for the same creator/VOD across jobs — one download + one clip run serves many campaign matches.

### `clips`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| source_asset_id | INTEGER FK | |
| platform_variant | TEXT | `tiktok` \| `reels` \| `shorts` (length-tuned variant) |
| storage_uri | TEXT | |
| duration_s | INTEGER | |
| transcript | TEXT nullable | |
| engine | TEXT | vendor used |
| engine_clip_id | TEXT | |
| cost_usd | REAL | per-clip engine cost |
| status | TEXT | `produced` \| `ready` \| `posted` \| `discarded` |
| created_at | TEXT | UTC ISO |

### `clip_matches`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| clip_id | INTEGER FK | |
| campaign_id | TEXT FK | |
| match_score | REAL | CVS niche-percentile × spec-fit |
| meets_requirements | INTEGER | 0/1 — hard-requirement pass |
| suggested_caption | TEXT nullable | |
| rank | INTEGER | rank among this clip's candidate campaigns |

*(Many-to-many: one clip can match several campaigns — but see the duplicate-deliverable guard under Matching.)*

### `campaigns` — new columns (Pipeline A table)
| Column | Type | Notes |
|---|---|---|
| target_creator | TEXT (JSON array) | creators/sources to clip, extracted from `requirements_raw` |
| target_platforms | TEXT (JSON array) | platforms the campaign accepts |
| clip_min_len_s | INTEGER nullable | extracted; partial coverage |
| clip_max_len_s | INTEGER nullable | extracted; partial coverage |
| caption_rules | TEXT nullable | required handles/hashtags/disclaimers from brief |
| banned_content | TEXT nullable | content prohibitions from brief |

### Reused: `outcomes` (Pipeline A)
"Mark posted" writes `clips_posted` / `campaign_id` here so B's spend is measured against real logged payouts.

---

## Matching / categorization logic

- Each clip inherits `creator` from its `source_asset`.
- **Candidate campaigns** = `status=active` **AND** `target_creator` overlaps the clip's creator **AND** the campaign's platform ∈ the clip's produced `platform_variant`s **AND** clip length ∈ `[clip_min_len_s, clip_max_len_s]`. Hard-requirement failures **exclude** (not downrank).
- **`match_score` = A's CVS niche-percentile × spec-fit.** Rank candidates; dashboard shows each clip with its best campaign + alternatives.
- Manual (`ingest_method='manual'`) and auto campaigns match identically.
- **Duplicate-deliverable guard (critical):** Whop's ToS prohibits duplicate deliverables ("each Deliverable must be unique"); clipping.net requires unique content per account. So although one clip may *match* several campaigns, the dashboard **warns against posting the identical clip file to more than one campaign for pay** — the operator picks the single best-scoring match, or the engine produces a distinct variant per campaign. Matching surfaces options; the compliance guard prevents the violation.

## Cost guardrails (~$70–115/mo, ~15 clips/day)

- **Billing model:** Vizard charges by **source upload-minutes** (1 credit = 1 min), not per output clip. So the cost driver is *how much long-form footage is fed in* (~6–10 min per usable clip). Track `source_asset.duration_s` as the cost basis; `est_cost_usd` on a `clip_job` is derived from the source length, not the clip count.
- `est_cost_usd` surfaced **at the approval click** — operator sees spend before greenlighting.
- `clips.cost_usd` tracked; a **rolling monthly total (in upload-minutes and $)** on the dashboard; `MONTHLY_CAP_USD` config. As projected spend nears the cap, **new `clip_jobs` pause (in-flight finish) and the operator is alerted** — no surprise overage.
- **`source_asset` dedup** bounds cost: same creator across two campaigns = one upload + one clip run.
- **Be selective at the source:** prefer feeding VODs from well-funded, high-CVS campaigns and trimming to the liveliest segments — this pulls upload-minutes (and cost) toward the low end.
- Because the operator approves each campaign (Approach 1), spend is inherently bounded by approvals.

## Error handling & brittleness

- Every job stage is **idempotent and retryable**; a failure sets `clip_job.status=failed` + `error`, surfaces in the dashboard, and **never crashes the scheduler**.
- **Acquisition** is the brittle point (analogous to A's RSC parser): `yt-dlp` breaks when sites change — pin the version, handle private/geoblocked/removed VODs gracefully, guard disk. If a download is **blocked/challenged, log and skip — never circumvent** (mirrors A's `fetch_events` drop-don't-evade rule).
- **Clip engine**: rate-limit / timeout / malformed-video → backoff + retry, then fail the job.
- **Retention**: delete the source VOD immediately after clipping; delete finished clips N days after `posted`/`discarded`; disk-usage guard.

## Compliance & legal posture

- **Posting is manual, one account per platform, cross-posted across platforms** (TikTok/Reels/Shorts), each submission unique. No multi-account plumbing — the multi-account "clip farm" model violates payout-platform unique-deliverable and anti-automation rules and triggers duplicate-hash / coordinated-behavior bans; for a solo human its expected value is negative.
- **Per-source acquisition posture:**
  - **Campaign-provided footage** — cleanest; prefer when offered.
  - **Creator VODs (Twitch/YouTube/Kick)** — downloading third-party VODs is generally against those platforms' ToS; the defensible basis is **the campaign's authorization/content license to clip that creator**. Only acquire a creator that an engaged campaign authorizes; record `authorizing_campaign_id`; honor the campaign's content rules. Genuinely gray and campaign-dependent — flagged, not hand-waved.
  - **URL long-form** — campaign-authorized only.
- Drop-don't-evade applies to acquisition exactly as to A's ingestion: a block/challenge means stop and log, never circumvent.

## Clip output spec (engine defaults)

Research-derived defaults (vendor-sourced — tunable, not laws). One source → per-platform length variants.

```
9:16 vertical, 1080×1920, full-bleed, H.264 MP4 (native upload — no embedded links)
Length:   TikTok ~30s  │  Reels ~7–20s  │  Shorts <60s   (maximize length × retention)
Hook:     peak moment in first 1–3s + text-hook overlay on frame 1, synced to first audio beat
Captions: burned-in ALWAYS (assume muted), word-by-word/karaoke style, inside UI safe zones
Framing:  face-tracked auto-crop; split-screen (facecam + content) for reaction/gameplay/podcast
Audio:    source audio primary (campaigns require it); trending sound only as low bed
Cover:    high-contrast frame + on-screen title; few niche hashtags
```

---

## Phases

### Phase B0 — Clip-engine adapter + price confirmation (do first)
Vendor is **selected: Vizard** (verified against official docs — real REST API, arbitrary source via file/URL, AI highlights, API-controllable 9:16/length/burned-captions/reframe, clip files + `viralScore` returned). Two things remain: (a) **get a real Vizard pricing quote at ~2,700–4,500 upload-min/mo** to confirm the ~$70–115/mo estimate (published tiers cap at 600 min/mo; higher volume is quote-based) — if it comes back materially higher, revisit volume or the Klap fallback; (b) implement `BaseClipEngine` with a **Vizard adapter** (leave a Klap adapter stub and a `HybridSelfHostEngine` seam so the managed-vs-self-host choice stays a config switch). **Acceptance:** one real source video → finished spec-compliant clips via the Vizard API, with source-upload-minute cost measured against the quote.

### Phase B1 — Schema & scaffolding
`factory/` package; Alembic migration for the new tables + `campaigns` columns; extend A's `normalize` with target/spec extraction (regex, provenance-flagged). **Acceptance:** migration applies; extraction unit-tested against fixtures.

### Phase B2 — Acquisition layer
`BaseAcquirer` + `campaign_provided` and `url` acquirers first (cleanest legally), then `youtube`/`twitch`/`kick` via `yt-dlp`; object storage; dedup; drop-don't-evade + retention. **Acceptance:** a source video is fetched to storage from each acquirer type (mock where needed), deduped, and a blocked download is logged-and-skipped.

### Phase B3 — Clip production + matching + captions
Wire acquire → clip → match → caption as APScheduler jobs; implement matching (with duplicate-deliverable guard) and caption generation. **Acceptance:** approving a campaign yields `ready` clips with ranked `clip_matches` and suggested captions; full `queued→ready` lifecycle passes on mocks.

### Phase B4 — Review dashboard
FastAPI app: approval surface (A's top campaigns + est-cost + "Clip this"), review surface (inline video, ranked matches, requirements, caption, download, mark-posted), manual-entry form, cost/compliance readouts. **Acceptance:** end-to-end — approve → review → mark-posted writes an `outcomes` row; monthly cost readout accurate; duplicate-deliverable warning fires.

### Phase B5 — Cost & retention hardening
`MONTHLY_CAP_USD` pause + alert; retention/cleanup jobs; disk guard. **Acceptance:** simulated spend nearing cap pauses new jobs and alerts; retention deletes aged assets.

---

## Non-goals

- **No auto-posting / auto-scheduling of posts.** Posting is manual.
- **No multi-account plumbing.** One account per platform.
- **No custom video ML.** Hosted engine only.
- **No evasion of any source's ToS or bot-protection** — walled/restricted sources are handled via manual capture in Pipeline A, never automated circumvention.

## Open questions / risks

- **Clip-engine vendor** resolved: **Vizard** (verified vs docs), Klap fallback. Residual: confirm Vizard's exact price above 600 upload-min/mo via a sales quote in Phase B0 (estimate ~$70–115/mo at ~15 clips/day); if materially higher, revisit volume or Klap.
- **Target-creator/spec extraction coverage** from free-text briefs will be partial (same reality as A's cap/threshold extraction); low-coverage campaigns produce weaker matches — acceptable, flagged.
- **Creator-VOD acquisition is legally gray** and campaign-dependent; keep campaign-provided/URL paths as the safer default and treat VOD acquisition as opt-in per authorizing campaign.
- **Storage/bandwidth** for VODs (multi-GB) must be aggressively cleaned; watch cost.
