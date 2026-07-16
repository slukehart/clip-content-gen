# Pipeline B — Clip Factory (Design Spec)

> Companion to `IMPLEMENTATION_PLAN.md` (Pipeline A — Deal Finder). Pipeline A ranks campaigns by value; **Pipeline B turns the best-ranked campaigns into a review-ready queue of finished clips matched to campaigns**, so the operator does only the manual revenue step (posting). Shares Pipeline A's repo, SQLite database, and single-process topology.

**Date:** 2026-07-13 · **Last updated:** 2026-07-15 (B1–B4 merged; live-Vizard + real-data findings; Phase B4.5 added)

---

## Purpose & boundary

Pipeline B automates the labor of clip production and leaves the operator in control of spend and of what gets posted. It **does not post** — posting stays manual and human, which is the deliberate line that keeps the operator's accounts clear of the automated-multi-account behavior that triggers payout-platform bans (see Compliance).

**The loop:** A ranks campaigns → operator approves a campaign in the dashboard → B acquires the creator's footage → hands it to a hosted clipping engine → matches finished clips back to all live campaigns → presents a review queue with the best-matched campaign, its requirements, and a suggested caption → operator watches, posts manually, marks posted (logged to A's `outcomes`, closing the ROI loop).

## Locked decisions (from brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Trigger model | **Suggest → operator approves → auto-produce** (Approach 1) | Connects A's rankings to B's queue; spend accrues only on approved campaigns; output is stuff the operator intends to post |
| Source footage | **Campaign-provided footage bank (Google Drive/link) FIRST; creator VODs (Twitch/YouTube/Kick) + long-form URL as opt-in fallbacks** | Empirically the norm, not the exception — Whop's own docs say *"the brand brings the demand and usually the footage. You bring the cut,"* delivered via Google Drive. Provided-bank is also the cleanest legally. Pluggable acquisition layer. See **Empirical grounding**. |
| Clip engine | **Vizard.ai** (hosted AI clip API) behind `BaseClipEngine` | Verified vs official docs: real REST API; accepts uploaded-file **and** YouTube/Twitch/Drive/Vimeo URLs; AI highlight detection; API-controllable 9:16 / length / burned captions / face-reframe; returns clip files + transcript + `viralScore`. Klap = fallback adapter; OpusClip = third; hybrid self-host = future seam |
| Review handoff | **Local web dashboard** | Inline video review with matched campaign + requirements + caption |
| Volume | **~15 clips/day** (~300–450/mo) | Right-sized: ≈ the max one manual poster can post (one account/platform, ~10–15/day across platforms) **and** ≈ the max the budget buys on a managed API. 20–75/day overshoots both. |
| Budget (B) | **~$70–115/mo** on Vizard (separate from A's ~$15/mo) | Vizard bills by **source upload-minutes** (~6–10 min per usable clip), not per clip. Confirm the exact >600-min/mo rate with a real quote in B0. Cost lever = source-minutes processed → be selective about which/how-long VODs get fed in. |
| Posting | **Manual, one account per platform, cross-posted** | Compliant, sustainable; no multi-account plumbing |
| DB / topology | **SQLite (WAL), consolidated single process** | Inherited from Pipeline A |

---

## Empirical grounding (2026-07-14) — DB audit + web validation

Before building B, we audited the two things a clip engine actually needs — *what footage to feed it* and *at what specs* — against the **real ingested data** (`clipscore.db`: 509 campaigns; **405 `clipping`/`both`**; 365 with a non-empty `description`) and cross-checked the architecture against the open web. This is the evidence base for the reframes below; it replaces the doc's original creator-VOD-first assumption.

**What the ingested `description` actually contains** (clipping/both, n=365):

| Signal the engine needs | Coverage in ingested `description` | Implication |
|---|---|---|
| Points to a provided footage bank (Resources/Drive/Docs/"footage") | **121/365 (33%)** | Footage is usually *brand-provided*, not a VOD to fetch. This is a **floor** — the Drive link lives on the Whop product page, not in the blurb we ingest. |
| Target creator as an `@handle` (regex-findable) | **15/365 (4%)** | Regex floor is ~4%; creator **names** appear in prose in ~half the sample ("James Hype", "Leo Grundström", "Carey James") → LLM ceiling is far higher. |
| Length / aspect spec | **37/365 (10%)** | Specs live in the brief/Drive doc, not the ingested text. |
| Caption / sound / tag rule | **24/365 (6%)** | Same — sparse in the blurb, richer on the product page. |
| Substantive (>200 chars) / near-useless (<40 chars) | 49% / 9% | ~half the descriptions carry real detail; a tail is title-only ("$31"). |

Descriptions are also **multilingual** (Spanish/Arabic/French observed) — which kills the existing regex extractor outright.

**Web validation** (primary + secondary sources):
- **Provided-bank is the norm — confirmed first-party.** Whop's docs: clipping campaigns give clippers *"Access to your video footage and any assets they can use,"* via *"Google Drive or similar";* *"the brand … usually [provides] the footage. You bring the cut."*
- **The spec fields we plan to extract == the fields brands set:** *content-quality standards, brand-mention requirements, prohibited-content guidelines, video length/format specifications, required messaging* (Whop docs) — a near-1:1 match to `caption_rules` / `banned_content` / `clip_*_len_s`.
- **Clip output spec holds:** 9:16 vertical, burned-in captions (≈50% watch muted), hook in first ~3s (2025/2026 short-form guidance).
- **Compliance posture holds:** unique content per account, duplicate-content ban, no multi-account farms, no evasion (clipping.net, clipster.gg, Whop).
- **Vizard capabilities match the doc exactly:** `videoUrl`+`videoType`, `preferLength`, `ratioOfClip:1`, `subtitleSwitch`, `maxClipNumber`, viral-score ranking (Vizard API docs).

**Two web-driven refinements folded into this spec:**
- **(A) Clip length is dynamic, not fixed.** The doc's original numbers (TikTok ~30s, Reels 7–20s) reflect an outdated sweet spot; current guidance is TikTok **60–180s** for substance, Reels 15–30s *or* 60–90s, Shorts <60s. → extract `preferLength` **per campaign** from the brief; treat the numbers under *Clip output spec* as fallback defaults only.
- **(B) FTC disclosure.** Every paid clip is a *"material connection under US FTC rules"* needing disclosure (#ad). Capture it as a `caption_rules` element and surface it on the review dashboard.

**Net effect on the design** (reflected in the sections below):
1. **Acquisition:** `campaign_provided` is the **primary** path; VODs are opt-in per authorizing campaign.
2. **Extraction (B1):** **LLM-based, not regex** (prose creator-names + multilingual), and it must **enrich from the Whop product page**, not just the ingested `description`. The `campaigns.url` fix (2026-07-14) now points at the real `whop.com` product page; its `robots.txt` is `Allow: /` (only `/api/` and `/discover/search/*` disallowed), so the page is fetchable under drop-don't-evade. New column `content_bank_url`.
3. **Clip spec:** length is per-campaign (refinement A).
4. **Compliance:** add FTC disclosure (refinement B).

*Sources:* [Whop Content Rewards docs](https://docs.whop.com/memberships-and-access/third-party-apps/content-rewards) · [Whop blog](https://whop.com/blog/whop-content-rewards/) · [clipster.gg rules](https://www.clipster.gg/general-campaign-rules) · [clipping.net terms](https://clipping.net/policies/clipper-terms-and-conditions) · [Vizard API docs](https://docs.vizard.ai/docs/) · [short-form length 2025 (Shortimize)](https://www.shortimize.com/blog/video-length-sweet-spots-tiktok-reels-shorts)

---

## Architecture

New package `src/clipscore/factory/`. Heavy video work is offloaded to the hosted clip engine, so B is an orchestrator of background jobs plus a small control/review UI. Components:

1. **Target extraction** — a **separate guarded post-ingest step** (`factory/enrich.py` orchestrating `factory/extract.py`), **not inline in A's `normalize`**, so an extraction failure can never break A's ingest. Pulls each campaign's *content bank / target creator* and *clip specs* (platform, min/max length, aspect, caption/handle rules, banned content). **LLM-based, not regex** — creator names arrive as free-text prose and the descriptions are multilingual (see Empirical grounding), so A's regex extractor is a floor, not a solution. Input is the ingested `description` **plus the Whop product page** (`campaigns.url`, robots-cleared), because the footage-bank Drive link and detailed specs live on the page, not in the blurb. Every field nullable + provenance-flagged by source (`description` | `whop_page` | `allowed_socials` | `absent`), same honest partial-coverage discipline as A. Regex remains as a cheap fallback / cross-check.
2. **Acquisition layer** (`factory/acquire/`, pluggable `BaseAcquirer` mirroring A's `BaseIngester`): per-source-type modules — `campaign_provided` (the **primary** path: brand's Drive/link footage bank), `url`, then `twitch`/`youtube`/`kick` (opt-in fallbacks) — using `yt-dlp` into object storage. Each carries its own ToS gate and drop-don't-evade behavior.
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
| content_bank_url | TEXT nullable | **primary acquisition input** — brand's Drive/link footage bank, extracted from the brief/Whop page |
| target_creator | TEXT (JSON array) | creators/sources to clip (for VOD-type campaigns), LLM-extracted from `description` + Whop page |
| target_platforms | TEXT (JSON array) | platforms the campaign accepts |
| clip_min_len_s | INTEGER nullable | extracted; partial coverage; per-campaign `preferLength` (see refinement A) |
| clip_max_len_s | INTEGER nullable | extracted; partial coverage |
| caption_rules | TEXT nullable | required handles/hashtags/disclaimers from brief — **including FTC #ad disclosure** (refinement B) |
| banned_content | TEXT nullable | content prohibitions from brief |
| extract_provenance | TEXT nullable | JSON: per-field **source** (`description` \| `whop_page` \| `allowed_socials` \| `absent`) — honest coverage tracking; records where a value came from, not which extractor found it. `allowed_socials` marks a field defaulted from A's ingested field, not read from brief text |
| extract_input_hash | TEXT nullable | `sha256(EXTRACT_VERSION + requirements_raw)`; the poll re-extracts a campaign when this no longer matches (its brief changed, or `EXTRACT_VERSION` was bumped). Rows extracted before this column existed carry a NULL hash and are grandfathered — the poll never re-extracts them (deliberate: avoids a one-time re-extraction of all ~405 on deploy) (migration `0005`) |

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
- **FTC disclosure.** A paid clip is a *material connection* under US FTC rules; the operator discloses (e.g. `#ad`) on each post. The extractor captures any campaign-required disclosure into `caption_rules`, and the review dashboard surfaces a disclosure reminder on every clip regardless — this is a legal requirement independent of whether a given campaign states it.
- **Per-source acquisition posture:**
  - **Campaign-provided footage** — cleanest; prefer when offered.
  - **Creator VODs (Twitch/YouTube/Kick)** — downloading third-party VODs is generally against those platforms' ToS; the defensible basis is **the campaign's authorization/content license to clip that creator**. Only acquire a creator that an engaged campaign authorizes; record `authorizing_campaign_id`; honor the campaign's content rules. Genuinely gray and campaign-dependent — flagged, not hand-waved.
  - **URL long-form** — campaign-authorized only.
- Drop-don't-evade applies to acquisition exactly as to A's ingestion: a block/challenge means stop and log, never circumvent.

## Clip output spec (engine defaults)

Research-derived defaults (vendor-sourced — tunable, not laws). One source → per-platform length variants.

```
9:16 vertical, 1080×1920, full-bleed, H.264 MP4 (native upload — no embedded links)
Length:   per-campaign preferLength (extracted) │ fallbacks: TikTok 60–180s · Reels 15–90s · Shorts <60s   (maximize length × retention; see refinement A — old ~30s sweet spot is dated)
Hook:     peak moment in first 1–3s + text-hook overlay on frame 1, synced to first audio beat
Captions: burned-in ALWAYS (assume muted), word-by-word/karaoke style, inside UI safe zones
Framing:  face-tracked auto-crop; split-screen (facecam + content) for reaction/gameplay/podcast
Audio:    source audio primary (campaigns require it); trending sound only as low bed
Cover:    high-contrast frame + on-screen title; few niche hashtags
```

---

## Phases

> **Build order (revised 2026-07-14):** B0's *price quote* is an **operator procurement task** (sign up for Vizard, request a quote, obtain an API key) — it gates cost, not code, and runs **in parallel**. The first code we build is **B1 (extraction)** — the clip-**accuracy** crux validated in *Empirical grounding* — because there is no point proving the engine (B0 adapter) until we can determine *what to feed it* for most campaigns. B0's adapter follows once a Vizard key exists.

### Phase B0 — Vizard price confirmation + clip-engine adapter
Vendor is **selected: Vizard** (verified against official docs — real REST API, arbitrary source via file/URL, AI highlights, API-controllable 9:16/length/burned-captions/reframe, clip files + `viralScore` returned).
- **B0a — price quote (operator task, do first, no code):** get a real Vizard pricing quote at ~2,700–4,500 upload-min/mo to confirm the ~$70–115/mo estimate (published tiers cap at 600 min/mo; higher volume is quote-based) and obtain an API key. If materially higher, revisit volume or the Klap fallback.
- **B0b — adapter (code, needs the B0a key):** implement `BaseClipEngine` with a **Vizard adapter** (leave a Klap adapter stub and a `HybridSelfHostEngine` seam so managed-vs-self-host stays a config switch). **Status (2026-07-15): the Vizard API key is obtained (`CLIPSCORE_VIZARD_API_KEY` in `.env`), so B0b is built as part of B3** — `BaseClipEngine` + `FakeClipEngine` for tested job logic, and the real `factory/clip/vizard.py` adapter as a manual-acceptance module.

**Acceptance:** one real source video → finished spec-compliant clips via the Vizard API, with source-upload-minute cost measured against the quote.

### Phase B1 — Schema & extraction (BUILD FIRST — see build-order note)
`factory/` package; Alembic migration `0004` for the new tables + `campaigns` columns (incl. `content_bank_url`, `extract_provenance`); **`factory/extract.py` — LLM-based target/spec extraction** enriched from the Whop product page (not just the ingested `description`), provenance-flagged per field, with A's regex kept as a cheap fallback/cross-check. First task **calibrates against real data** (the folded-in coverage audit): measure extraction coverage — regex floor vs LLM ceiling vs +Whop-page delta — over a stratified sample of the 405 real clipping campaigns, and freeze that sample as the test fixture set. **Acceptance:** migration applies; extraction is unit-tested against fixtures; a coverage report (floor/ceiling/+whop, footage-source distribution) is written to `docs/spikes/`. See `plans/pipeline-b-stage-1-extraction.md`.

### Phase B2 — Acquisition layer
`factory/acquire/`: `BaseAcquirer` ABC (mirrors A's `BaseIngester`) + a `source_type → acquirer` registry, filling the existing `clip_jobs`/`source_assets` tables (no new schema). `campaign_provided` (**primary**) and `url` acquirers first (cleanest legally) — direct-download of *public* links (Drive `uc?export=download` file links, Dropbox `?dl=1`, plain media URLs), robots-checked via `ingest/detect.classify_response`; an auth-walled/folder/challenged link → `status="manual"`, logged, **never evaded** (CLAUDE.md "manual capture"). Then `youtube`/`twitch`/`kick` via **lazy-imported `yt-dlp`** shipped as an optional extra (`[project.optional-dependencies] media`, pinned) — real runs manual-acceptance-only, CI exercises them through an injected fake downloader. **Storage:** local filesystem under new config `media_dir` (default `media/`, gitignored) behind a thin `storage.py` seam (local impl only; cloud slots in later). **Dedup:** content-addressed path `media/<source_type>/<sha256(source_ref)[:16]>.<ext>` — footage authorized by multiple campaigns is fetched once. **ToS gate:** VOD acquirers refuse a job with no `authorizing_campaign_id`. **Orchestrator** `acquire_job()` wraps each job so acquisition never crashes the scheduler (mirrors the `enrich` guard); idempotent/retryable. **Retention (B2 scope):** `sweep_retention()` deletes source files older than `raw_retention_days` (=14) + a pre-download disk-usage guard; immediate-post-clip deletion is deferred to B3. **Acceptance:** a source video is fetched to storage from each acquirer type (mock where needed), deduped, and a blocked download is logged-and-skipped. See `plans/pipeline-b-stage-2-acquisition.md`.

### Phase B3 — Clip production + matching + captions
Wire acquire → clip → match → caption as APScheduler jobs; fills the existing `clips`/`clip_matches` tables (no new schema).

- **Provider-agnostic LLM client** `factory/llm.py`: an OpenAI-compatible `/chat/completions` client over `httpx` (already a dep) driven by config `llm_base_url` (default `https://openrouter.ai/api/v1`), `llm_model` (default `moonshotai/kimi-k2`, overridable), `llm_api_key` (`CLIPSCORE_LLM_API_KEY`). Structured extraction uses JSON mode + pydantic validation (portable across open models). **Retrofit B1's `extract_llm.py`** onto this client and **drop the `anthropic` SDK dep** — extraction stays behavior-identical (tested against a fake client in CI). Covers Kimi/DeepSeek/Groq/local/Claude by config alone.
- **Clip engine** `factory/clip/base.py`: `BaseClipEngine.produce(source_uri, specs) -> list[ProducedClip]` (encapsulates submit → poll-with-backoff → download; timeout/error → job fails). `FakeClipEngine` for CI. Real **Vizard adapter** `factory/clip/vizard.py` reads `vizard_api_key` (`CLIPSCORE_VIZARD_API_KEY`), manual-acceptance-only — this **is B0b**. ⚠️ **The committed adapter does NOT work against the live API** (see the 2026-07-15 findings below) — the passthrough bridge in "Phase B4.5" replaces it. Per-platform variants (`tiktok`/`reels`/`shorts`, doc fallback lengths, narrowed by the campaign's `clip_min/max_len_s`).
- **Clipping job** `factory/clip/produce.py`: `acquired` job → load `source_asset` → `engine.produce()` → write `clips` rows (`produced`) → **delete the source VOD file** (the immediate-post-clip retention deferred from B2; clips kept). Never-raise guard.
- **Matching** `factory/clip/match.py` (pure, CI-tested): candidates = `status=active` AND `target_creator` overlaps clip creator AND campaign platform ∈ produced variants AND clip length ∈ `[clip_min_len_s, clip_max_len_s]` (hard failures exclude); `match_score` = CVS niche-percentile × spec-fit; write ranked `clip_matches` + `meets_requirements`; clip → `ready`.
- **Captioning** `factory/clip/caption.py`: deterministic floor that ALWAYS injects an FTC `#ad` disclosure + required handles/hashtags from `caption_rules` (regardless of whether the campaign states it — compliance-first); optional LLM enrichment via `factory/llm.py` when a key is set (manual-acceptance).
- **Job runner** `jobs/clipfactory.py`: status-driven `process_clip_jobs` advances each `clip_job` (`queued`→acquire→`clipping`→`matching`→`caption`→`ready`), each stage guarded (failure → `failed`+error, never crashes the scheduler), **idempotent** (only picks jobs in the valid prior status — also closes the B2 idempotency note). APScheduler-wired. Minimal operator trigger `clipscore clip <campaign_id> [--source-type --source-ref]` creates a `queued` job with `est_cost_usd` (exercisable before the B4 dashboard).

**Acceptance:** approving a campaign (via `clipscore clip`) drives the full `queued→ready` lifecycle on the `FakeClipEngine` — `ready` clips with ranked `clip_matches` and `#ad`-bearing suggested captions; extraction unchanged post-retrofit. See `plans/pipeline-b-stage-3-clip-production.md`. ⚠️ **The real Vizard and real OpenRouter/Kimi runs were NOT actually performed** (the earlier wording here was aspirational) — the live Vizard probe on 2026-07-15 revealed the adapter is wrong; see the findings below.

### Phase B4 — Review dashboard
**Planned 2026-07-15** in `plans/pipeline-b-stage-4-review-dashboard.md` — **not yet built.**
FastAPI + Jinja2 (server-rendered) + one vendored `htmx.min.js` (no CDN/build step), **localhost-only, no auth** (single local user). New deps: `fastapi`, `uvicorn`, `jinja2`, `python-multipart`. CI-pure via Starlette `TestClient` (no running server, no network, no real video).

- **One additive migration** `0006_add_outcome_clip_id` (`down_revision="0005"`): `outcomes.clip_id INTEGER NULL`. Load-bearing for the footage-reuse warning (join `outcome → clip → source_asset_id → sibling clips' outcomes`). Pipeline A's future campaign-level writes leave it NULL — safe (nothing writes `Outcome` today).
- **`web/queries.py`** (pure, CI-tested): approval list (reuses `scoring/board.eligible_latest_scores`, filtered to `clipping`/`both` + `status=active`, carrying est-cost `settings.clip_est_cost_usd` + current clip_job status); review data (clip + ranked `clip_matches` + requirements + caption); monthly cost readout (**calendar month in ET**, matching the bot's `SUMMARY_HOUR_ET`).
- **`web/warnings.py`** (pure): **advisory** duplicate-deliverable warnings — (1) source-asset reused across a different campaign's outcome, (2) this campaign already has an outcome. Displays only; never blocks a post (hard cap/pause is B5).
- **`web/actions.py`** (guarded): "Clip this" & manual-entry both reuse `create_clip_job` (catch its `ValueError` → inline "no acquirable source"); **mark-posted is an idempotent upsert** on `(clip_id, campaign_id)` (never appends — appending would corrupt the dup-warning and the learning loop), sets `clips_posted=1`, other actuals NULL.
- **Routes:** `GET /` (approval) · `POST /clip/{campaign_id}` (enqueue `queued` job, HTMX swap) · `GET /review`, `GET /review/{clip_id}` (inline `<video>`, matches, requirements, caption, download, dup-warnings, mark-posted) · `POST /posted/{match_id}` · `GET /media/{clip_id}` (`FileResponse`, path resolved **from DB only** — 404 if missing or outside the clips dir; traversal-guarded) · `GET/POST /manual`. Per-request session (never held across a request; SQLite `busy_timeout=5000` already covers the web↔scheduler two-writer case).
- **CLI:** `clipscore web [--host 127.0.0.1] [--port 8000]` (uvicorn).
- **"Clip this" only enqueues** — the web layer never produces clips; the scheduler's B3 runner does.

**Acceptance:** e2e — seed a scored clippable campaign → `POST /clip` → run `process_clip_jobs` on `FakeClipEngine` → `GET /review/{clip}` renders → `POST /posted` writes exactly one `outcomes` row + monthly cost readout accurate → a second post fires the duplicate-deliverable warning. Real uvicorn run is manual-acceptance-only.

### Manual-acceptance findings (2026-07-15) — infrastructure reality check
Probing the live Vizard API and the real ingested campaign data (`clipscore.db`, 405 clipping/both campaigns) surfaced three facts that reshape the remaining work:

1. **The committed Vizard adapter is wrong.** Against the live API (`create`→`{code:2000, projectId}`, `query`→`{code:1000}` processing / `{code:2000, videos:[...], creditsUsed}` done): the adapter never sends the **required** `videoType`, polls the wrong status codes (checks `"success"`/`2`, real is `code:2000`), reads `clips` (real field is `videos`), and passes `preferLength` as seconds (it's a category code). It would poll to timeout and find nothing. **Vizard is URL-only** (no upload) but fetches YouTube/Drive-file/Twitch/direct-mp4 by their original URL (`videoType` 2/3/9/1). It returns **N ranked vertical clips of its own choosing** (10 for a ~14-min source), NOT one clip per spec. Full contract in the `vizard-api-contract` memory.
2. **Cost model:** `creditsUsed` is per **source-video length** (~14 credits for a ~14-min source → ~10 clips), not per clip. This is the figure B5's cap must be set against.
3. **Source-grabbing is inherently manual.** 0/405 campaigns had an extracted `content_bank_url`; Google Drive links appear in ~2.7% of ingested text; content banks are gated behind *joining* the campaign. Real campaigns are dominantly "clip a source video" (mine of blurbs: ~98 "clip a video" vs ~16 "pre-approved clips"). The operator supplies the public source URL via B4's `/manual`; auto-discovery is not achievable and manual entry is the designed-for norm.

### Phase B4.5 — Vizard passthrough bridge (next build)
Make a true end-to-end real-Vizard run possible. The committed pipeline's core
mistake is that it **downloads the source to a local file and hands Vizard that
local path** — but Vizard is **URL-only** and fetches the source itself by its
public URL. So the acquire-then-clip model is wrong for URL-fetchable sources;
the fix is a *no-download passthrough*. Scope (build only this; defer the rest):

- **`detect_video_type(url) -> (videoType, ext) | None`** — one pure, CI-tested
  helper mapping a URL to Vizard's `videoType` (2=YouTube, 3=Drive-file,
  9=Twitch, 4=Vimeo, 1=direct-file+`ext`; unsupported → `None`). Used by **both**
  job-routing and the adapter so the mapping can't drift (drift is part of what
  broke the original adapter).
- **`PassthroughAcquirer`** (new `source_type="passthrough"`, **no download**):
  validate the URL via `detect_video_type`, record a `SourceAsset`
  (`source_url=<url>`, `storage_uri=None`) and set the job `acquired`;
  unsupported URL → `manual`/fail with a clear error. CI-tested (pure, no network).
- **`create_clip_job` routing:** when the resolved source URL maps to a
  `videoType`, queue it as `passthrough` (not `campaign_provided`, whose
  `download_direct` can't fetch a YouTube/Twitch URL).
- **`run_clipping` fix:** select the job's `SourceAsset` **without** requiring
  `storage_uri`; pass `source_asset.source_url` (the public URL) to the engine
  **unconditionally** (a URL-only engine never wants a local path); guard the
  retention delete with `if storage_uri:` (a `None` path → `os.remove(None)`
  raises **TypeError**, which the `except OSError` would miss and the outer guard
  would turn into a failed job).
- **Rewrite `factory/clip/vizard.py`** to the real contract: `detect_video_type`
  → send `{videoUrl, videoType, lang, preferLength:[0]}` (+`ext` for direct
  files), poll on `code:2000` (done) / `1000` (processing), read `videos`,
  download each `videoUrl`, record `creditsUsed`. Wire call stays
  manual-acceptance-only; everything around it is CI-tested via `FakeClipEngine`.
- **Engine model reshape:** `produce(source_url, …) -> list[ProducedClip]` returns
  **one clip per Vizard clip** — Vizard picks the clips; we keep them. Vizard
  returns N *format-identical* vertical short-form clips, not one-per-platform.
- **Platform is a campaign property, not a clip property (Decision B, 2026-07-15).**
  Because Vizard's clips are format-identical and postable to any short-form
  platform, `platform_variant` is dropped from the clip-production path:
  - `ProducedClip`/`Clip.platform_variant` is left **nullable and unused** (written
    `NULL`) — **no migration** (dropping a SQLite column is a table rebuild for
    zero gain); the column stays for back-compat.
  - `match.py` **drops the platform gate**: a clip matches a live campaign on
    creator + length (`clip_min/max_len_s`) only; the campaign's
    `target_platforms` says where the operator posts.
  - `web/queries.py`/`review_list.html` show the **matched campaign's** platforms
    instead of a per-clip variant.
- **A clip always matches its originating campaign (2026-07-15, from build review).**
  A manually-entered clip's target campaign is already known — it is the campaign
  the `ClipJob` was created under (`clip → SourceAsset.clip_job_id → ClipJob.campaign_id`).
  So `match_clip` **always includes that originating campaign** (subject only to the
  length window + active/ingestable eligibility), *independent of creator and of
  whether a CVS score exists yet* — routing a clip through creator+score *discovery*
  to re-find its own campaign was a Pipeline-A-era mismatch that silently produced
  **zero matches** on the `/manual` path (manual campaigns are unscored, and
  `target_creator` is optional on the form). Discovery of *other* eligible, scored,
  same-creator campaigns is layered on top with a de-dup. Correspondingly, the
  no-download passthrough sets `SourceAsset.creator` from the campaign's first
  `target_creator` when the source itself yields none.
- **Cost capture:** record Vizard's project-level `creditsUsed`; convert to $ via a
  new `vizard_usd_per_credit` config (default `0.0`, set from the real plan). This
  is the figure B5's cap is set against.
- **Defer:** Drive-*folder* enumeration, a pre-approved-clips (no-engine) review
  path, and the local-download→temp-public-host fallback for non-fetchable sources
  (Kick, private Drive) — build when a real case needs them.
- **Acceptance:** manual-enter a public source URL (`/manual`) → real Vizard render
  → `ready` clips + ranked matches in the dashboard → mark posted; capture the real
  `creditsUsed` cost.

### Phase B5 — Cost & retention hardening
Design approved 2026-07-15 (brainstorm) after the real-Vizard acceptance run proved B4.5
and surfaced concrete gaps. Scope = "full hardening": monthly cost cap, persist raw
`creditsUsed`, clip retention, an on-demand process command, Vizard virality params, and
a batch of carried-over minor fixes. Vizard billing is now known exactly (see Open
questions + the `vizard-api-contract` memory): **1 credit = 1 minute of SOURCE video**,
independent of clip count / `preferLength` / `lang`; there is **no API trim/duration
parameter**, so the only lever to spend less is a shorter source. All new logic is
CI-pure (fakes/MockTransport/in-memory DB); real Vizard stays manual-acceptance-only.

**1. Monthly cost cap — in CREDITS (not USD).** The unit is credits, not dollars,
because $/credit is plan-dependent and defaults to `0.0` (a dollar cap would silently
never fire), whereas `creditsUsed` is exact and 1:1 with source minutes.
- Config `CLIPSCORE_MONTHLY_CAP_CREDITS` (0 = uncapped). A $ figure is shown alongside
  only when `vizard_usd_per_credit` is set.
- **Estimate:** the operator enters source length in minutes (`/manual` form field +
  `clipscore clip --source-minutes`); `est_credits = ceil(minutes)`, persisted on the
  job. This is the estimate that feeds the monthly projection — there is **no** separate
  per-job cap.
- **Gate:** checked in `run_clipping`, immediately before the paid Vizard call (queue +
  acquire stay free). If `month_credits_used + est_credits > cap`, the job transitions to
  a new **`blocked`** status (distinct from `failed`), logs + alerts **once**, and never
  calls Vizard. `blocked` is not in `_ADVANCEABLE_STATUSES`, so it is not retried; the
  operator re-queues after raising the cap or at month rollover.
- **Accounting (honest scoring):** the pre-flight estimate gates; the real `creditsUsed`
  is what accumulates into the month-to-date total after a run. Month bounds reuse the
  existing ET-month helper (`monthly_cost_usd` gains a credits sibling).

**2. Persist raw `creditsUsed`.** New column `clip_jobs.credits_used` (raw int, one
project = one job). `clips.cost_usd` stays derived (`credits × rate`, split across clips).

**3. Retention — after-posted + age fallback (clips only; passthrough keeps no source).**
- On mark-posted → delete that clip's file.
- Age sweep → delete clips older than `CLIPSCORE_CLIP_RETENTION_DAYS` (default 14),
  regardless of posted status.
- Exposed as `clipscore prune` and wired into the scheduler (guarded — never crashes it).

**4. On-demand process command.** `clipscore process` drains all in-flight jobs to a
terminal status in one invocation (loops `process_clip_jobs` until nothing is
advanceable); `--once` runs a single pass. This is the fix for the "web queues but
nothing runs" gap — `clipscore web`/`clip` only enqueue.

**5. Vizard virality params.** The adapter sends (all config-toggleable, sensible
defaults on): `ratioOfClip=1` (9:16), `subtitleSwitch`, `highlightSwitch`,
`headlineSwitch`, `emojiSwitch`, `autoBrollSwitch`, `removeSilenceSwitch`, and `keyword`
derived from the campaign's niche/requirements. None affect credit cost. CI asserts the
outgoing payload via MockTransport.

**6. Carried-over minor fixes.** `clip_matches` UNIQUE(clip_id, campaign_id);
`enrich_campaign` rollback-first alignment; per-tick job cap; `TemplateResponse` argument
order (deprecation); `media//` double-slash path join.

**Schema:** one small migration `0007` — `clip_jobs.est_minutes`, `clip_jobs.credits_used`,
and the `clip_matches` unique constraint.

**Acceptance:** (CI) a job whose estimate would exceed the cap is `blocked`, not sent, and
alerts once; a posted clip's file is deleted and an aged clip is swept; `clipscore process`
drives a queued job to terminal; the Vizard payload carries the virality params. (Manual)
set `CLIPSCORE_MONTHLY_CAP_CREDITS` + `CLIPSCORE_VIZARD_USD_PER_CREDIT` from the real plan
and confirm the cap blocks a would-be over-budget real run.

---

## Non-goals

- **No auto-posting / auto-scheduling of posts.** Posting is manual.
- **No multi-account plumbing.** One account per platform.
- **No custom video ML.** Hosted engine only.
- **No evasion of any source's ToS or bot-protection** — walled/restricted sources are handled via manual capture in Pipeline A, never automated circumvention.

## Open questions / risks

- **Clip-engine vendor** resolved: **Vizard**, Klap fallback. Live API probed 2026-07-15 (see findings above): URL-only, cost = `creditsUsed` per source-video length (~14 credits/~14-min source → ~10 clips). Residual: convert `creditsUsed`→$ from the actual account plan; set the B5 cap against it. The committed adapter needed a rewrite (Phase B4.5).
- **Target-creator/spec extraction coverage** is **thin in reality** (measured 2026-07-15, not just theorized): 0/405 clipping campaigns had an extracted `content_bank_url`; Drive links appear in ~2.7% of ingested `requirements_raw`; content banks are gated behind joining. Conclusion: **manual source-URL entry (B4 `/manual`) is the norm, not a fallback.** `clipscore extract --report` still measures LLM+Whop coverage, but do not expect it to unlock auto-acquisition at scale. Low-coverage campaigns are handled by the operator, flagged via `extract_provenance`.
- **Creator-VOD acquisition is legally gray** and campaign-dependent; keep campaign-provided/URL paths as the safer default and treat VOD acquisition as opt-in per authorizing campaign.
- **Storage/bandwidth** for VODs (multi-GB) must be aggressively cleaned; watch cost.
