# Phase 0 De-Risking Spike — contentrewards.com/discover

**Date:** 2026-07-13
**Purpose:** Resolve the one finding that can still change the schema before Stage 2 (the stable dedup key), save a golden RSC-payload fixture, and document `stats.successRate`/`engagement` meaning. Corresponds to `IMPLEMENTATION_PLAN.md` Phase 0.

**Method:** Two `curl` GETs of `https://contentrewards.com/discover` a few minutes apart (honest UA, `--compressed`), parsed offline. Raw pages (~8 MB each) live in the session scratchpad only; the committed artifact is the trimmed fixture below.

---

## Acceptance items (all met)

### 1. Stable dedup key — RESOLVED: `external_id` = campaign `id` (UUID)

| Candidate | Present | Distinct (of 502) | Verdict |
|---|---|---|---|
| `id` (UUID, e.g. `dd9f7918-e51d-4935-9f23-5935c783774a`) | 502/502 | **502** | **Unique per campaign → the key** |
| `whopExperienceId` (`exp_ZOGZeyhNIa6vDv`) | 502/502 | 305 | Shared — identifies the Whop *experience/community*, **not** the campaign |
| `whopProductRoute` (`creator-casino-7b`) | 487/502 | 299 | Nullable + non-unique |

**Stability:** two fetches minutes apart returned the **same 502 ids, 100 % intersection**, and each id mapped to the same `whopExperienceId`. This rules out per-request/session id randomization (the common failure). Rebuild-reassignment on a days cadence can't be confirmed in one session, but a UUID that is byte-identical across fetches is a stored business key, not render-time output — high confidence. The upsert would surface any instability on its own (a wave of ~500 duplicate "new" campaigns).

**Schema impact: none.** Stage 1 already shipped `unique(source, external_id)` with `whop_experience_id` as a separate nullable column. `normalize()` fills `external_id` from `id`; `whop_experience_id` from `whopExperienceId`. No migration for the key.

### 2. Golden fixture — SAVED

`tests/fixtures/contentrewards/discover_golden.html` — 5 real campaigns re-encoded in the **exact wire format** (`self.__next_f.push([1,"…"])`, `$$`-money escape, `\"` JSON escaping), nested under the **real observed container key** `initialData.bannerCampaigns` (confirmed present in the live payload — not an invented wrapper). Chosen to exercise: full field set + money; a campaign missing `category`, `whopProductRoute`, and `description`; the rare `programId`/`featuredPriority` extras; and a non-`active` (`completed`) status. A **6th entry duplicates campaign 0** (same `id` serialized twice) so the parser test exercises the **dedup-by-`id`** that the observed 526→502 gap depends on. Round-trips through the decode pipeline (regex → `json.loads` → `$$`→`$` → marker-walk → dedup) to exactly the 5 source campaigns with money preserved.

### 3. `stats.successRate` / `engagement` — DOCUMENTED (decision deferred to Stage 3)

- `stats.successRate` — integer **0–100** (looks like a percentage), present for all campaigns. Sampled values span the range (0, 1, 4, 26, 60, 70, 71). **Meaning undetermined from the payload alone** — could be an approval rate, a view-threshold-clear rate, or an internal health score. Do **not** wire it into `p_approval` yet; the plan (Phase 3 step 3) makes that call after investigation. Capture the raw value.
- `stats.engagement` — a numeric **string** that, on sampled rows, **equals `budgetSpent`** (e.g. `engagement:"86690.35"` vs `budgetSpent:"$86,690.35"`). Suspiciously a restatement of spend, not an engagement rate. Capture raw; investigate in Stage 3; do not treat as a signal until understood.

---

## Payload mechanics (for the Stage 2 parser)

- **Fetch:** HTTP 200, ~8 MB (`--compressed` → ~595 KB on the wire), `text/html`. No challenge markers (no Cloudflare/CAPTCHA/login-redirect). robots.txt: `Allow: /discover`, `Disallow: /api/`.
- **Decode pipeline:** the page carries **44** `self.__next_f.push([1,"<chunk>"])` calls. Extract each chunk's JS string literal → `json.loads` it (unescapes `\"`) → concatenate → **replace `$$` → `$`** (RSC money escape) → the campaign objects are now valid JSON. Money fields are strings: `pricePerView:"$1.50"`, `totalBudget:"$250,000"`, `budgetSpent:"$86,690.35"` → strip `$` and `,` → float.
- **Parser strategy (validated on real data):** the full campaign list is **RSC-streamed, not under a single named array key** — only `bannerCampaigns` (a small featured subset) is a named container. The approach that worked: **find every `whopExperienceId`, brace-walk out to the enclosing `{}` object, then dedup by `id`.** On the live payload this yielded **502 distinct campaigns from 526 raw matches** (24 collapsed — a duplicate SSR/hydration serialization; dedup-by-`id` handles it). Do **not** try to locate "the campaigns array structurally" — there isn't one. After dedup, assert a plausible count to feed the harvest-sanity gate (≈500 normal; `<50` ⇒ treat as parse failure, skip the ended-sweep). The golden fixture's duplicate 6th entry exercises this dedup.

## Actual field set vs. plan assumptions (drives `normalize`)

| Reality found | Plan assumed | Consequence for Stage 2 |
|---|---|---|
| Unique key `id` (UUID); `whopExperienceId` shared | key TBD | Resolved above — no schema change |
| **No `requirements_raw` field.** Only `description` (nullable, 451/502) — a marketing blurb | full brief text in `requirements_raw` | Cap/min-views/min-payout regex runs against `description`; **thin, partial coverage**; `cap_provenance='absent'` will be the common case; ~10 % have no description at all |
| `viewCount` is `stats.viewCount`, a **display string** `"51.4M"`/`"226.2K"` | top-level `viewCount` integer | Parse `M`/`K`/`B` suffixes → approximate int; flag lossy |
| `status` ∈ `{active(501), completed(1)}` | `active/paused/ended` | Map source `completed` → our `ended`; `paused` unseen this snapshot but handle; unknown → flag. (Distinct from the sweep-derived ended state for campaigns that vanish from the feed.) |
| `category` ∈ `{Entertainment, Technology, Product, Music, Logo, Personal Brand, Slideshow, Gaming, Other, null}` | niche enum `gaming/podcast/finance/fitness/tech/entertainment/crypto/other` | **Mismatch.** Real categories are content-**format**-ish, not topic-niche. `niche_baselines` seeded in Stage 1 is misaligned. **Recommendation:** adopt source `category` verbatim (slugified) as the niche partition; re-seed `niche_baselines` to real categories in Stage 3. Within-niche ranking is partition-agnostic; cross-niche baselines need re-seeding regardless. |
| `campaignType` ∈ `{clipping(386), ugc(103), both(13)}` | not modeled | ~20 % are UGC (no clip to produce). **Recommendation:** add a `campaign_type` column (migration `0002`), store it, keep all rows; scoring/Pipeline B filter to `clipping`+`both`. |
| `progressPercentage` (int) ≈ `budgetSpent/totalBudget` | — | Free budget-health-ish signal; capture in snapshot for cross-checking burn math |
| `socialPlatforms` ∈ `{tiktok, instagram, youtube, x, facebook}` | `tiktok/reels/shorts/x/facebook` | Store verbatim; `instagram`/`youtube` are the platform names, not `reels`/`shorts` |
| No per-campaign fee field | already source-default only | Confirmed: fee from `platform_trust.default_fee_pct` |

### Other observed fields (capture-or-ignore)
`experienceId` (a second, internal UUID distinct from `whopExperienceId` — ignore for v1), `companyId`, `brand`, `title`, `creators` (int), `isVerified` (bool), `fundedAt` (ISO ts), `avatar`/`thumbnail`/`bannerImageUrl` (media URLs — ignore for v1), `bannerPriority`, `featuredPriority`/`programId` (rare, 13/502).

---

## Net effect on the Stage 2 plan

1. **No key/schema surprise** — the Stage 1 data layer holds. One additive migration (`0002`) for `campaign_type`.
2. **`normalize` is the real work** and must be defensive: display-string money, `stats.*` nesting, `M/K` view parsing, `completed→ended` status mapping, `category` verbatim as niche, `description` (not `requirements_raw`) as the thin regex source with honest `cap_provenance`.
3. **`niche_baselines` re-seed** (real categories) and the **`successRate`/`engagement` meaning decision** belong to Stage 3, flagged here so they aren't forgotten.
4. **Parser** uses the validated marker-walk + dedup-by-`id` + count assertion (no structural array exists); golden fixture above (with its duplicate entry) is the unit-test input.
