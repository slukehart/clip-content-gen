# Pipeline B — Stage B4.5: Vizard Passthrough Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make a true end-to-end **real-Vizard** run possible by fixing the committed pipeline's core mistake — it downloads the source to a local file and hands Vizard that local *path*, but Vizard is **URL-only** and fetches the source itself by its public URL. Add a no-download **passthrough** path, rewrite the adapter to the real API contract, and drop the now-vestigial per-clip platform dimension (Vizard returns format-identical vertical clips; **platform is a campaign property**).

**Architecture:** One pure `detect_video_type(url)` helper maps a URL to Vizard's `videoType`; it is the single source of truth used by *both* job-routing and the adapter (mapping drift is what broke the original adapter). A new no-download `PassthroughAcquirer` records the public URL as a `SourceAsset` (`storage_uri=None`) so a YouTube/Twitch/Drive-file URL reaches `acquired` without a (impossible) local download. `run_clipping` hands the engine the public `source_url` unconditionally. The engine returns one `ProducedClip` per Vizard clip (no platform); `match.py` matches a clip to a live campaign on creator + length only. The `vizard.py` wire call stays manual-acceptance for real network, but its request/response handling is CI-tested with `httpx.MockTransport`.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x, httpx (`MockTransport` in CI), pydantic, structlog, pytest.

## Context

This is **Phase B4.5** of `PIPELINE_B_CLIP_FACTORY.md` (source of truth — see its **Phase B4.5** entry and the **Manual-acceptance findings (2026-07-15)** section). Pipeline A Stages 1–4 and Pipeline B Stages B1–B4 are merged. The live Vizard API was probed 2026-07-15; the real contract is in the `vizard-api-contract` memory. **B4.5 adds no schema** — the `clips.platform_variant` column stays (nullable, unused).

**Design decisions this plan encodes (finalized 2026-07-15):**
- **Vizard is URL-only.** It fetches the source by its original public URL (`videoType` 2=YouTube, 3=Drive-file, 9=Twitch, 4=Vimeo, 1=direct-file+`ext`). No upload/multipart. So the local-download acquire step is wrong for URL-fetchable sources → a no-download passthrough is the fix, not an addition.
- **Vizard picks the clips.** One source → N ranked, **format-identical** vertical short-form clips (not one-per-platform). We keep them as-is; we do not label them per platform.
- **Decision B — platform is a campaign property, not a clip property.** `platform_variant` is dropped from the clip-production path (left nullable/unused, no migration); `match.py` matches on creator + length; the campaign's `target_platforms` says where the operator posts.
- **Cost:** record Vizard's project-level `creditsUsed`; convert to $ via `vizard_usd_per_credit` (default `0.0`).
- **Deferred:** Drive-*folder* enumeration, a pre-approved-clips (no-engine) path, and the local→temp-public-host fallback for non-fetchable sources.

## Existing code this builds on

- `src/clipscore/factory/clip/base.py` — `ClipSpec` (`platform_variant`, `min_len_s`, `max_len_s`), `ProducedClip` (`platform_variant`, `storage_uri`, `duration_s`, `transcript`, `engine`, `engine_clip_id`, `cost_usd`), `BaseClipEngine.produce(source_uri, specs, *, dest_dir)`, `FakeClipEngine` (one clip per spec), `derive_specs(campaign, settings) -> list[ClipSpec]`, `build_engine(settings)`. **Reshaped in Task 4.**
- `src/clipscore/factory/clip/produce.py` — `run_clipping` + `_run_clipping_inner`: selects the job's `SourceAsset` **filtered on `storage_uri.is_not(None)`**, calls `engine.produce(source_asset.storage_uri, specs, dest_dir=...)`, writes `Clip` rows, then `os.remove(source_asset.storage_uri)` (retention). Never-raise guard (rollback-FIRST). **Fixed in Task 4.**
- `src/clipscore/factory/clip/match.py` — `match_clip(session, clip)`: gets `platform = _VARIANT_PLATFORM.get(clip.platform_variant)`, `return []` if None, else filters candidates by `_creator_matches` + `_platform_matches` + `_length_ok`; `match_score = cvs_pct * spec_fit` (`spec_fit` 1.0 if the campaign has a length window else 0.9). **Platform gate removed in Task 5.**
- `src/clipscore/jobs/clipfactory.py` — `create_clip_job(session, campaign_id, settings, *, source_type, source_ref, now)`: resolves a source (explicit args → `content_bank_url` → first `target_creator` → `ValueError`) and writes a `queued` `ClipJob`. `_ADVANCEABLE_STATUSES=("queued","acquired","produced")`; `_advance` dispatches acquire→clip→match→caption. **Routing added in Task 3.**
- `src/clipscore/factory/acquire/campaign_provided.py` — `_normalize_share_url`, `CampaignProvidedAcquirer` (downloads via `download_direct`). `src/clipscore/factory/acquire/base.py` — `AcquisitionResult` (`status`, `storage_uri`, `bytes`, `duration_s`, `creator`, `platform`, `source_url`, `error`) + `BaseAcquirer` ABC. `src/clipscore/factory/acquire/registry.py` — `build_registry()` dict + `select_acquirer`. `src/clipscore/factory/acquire/run.py` — `acquire_job` (auth gate, dedup, disk guard, writes `SourceAsset(storage_uri=result.storage_uri, source_url=result.source_url or source_ref, ...)`). **`PassthroughAcquirer` slots in with NO `run.py` change** (its `acquire` returns `storage_uri=None`, and the disk-guard/dedup steps are harmless no-ops for it).
- `src/clipscore/factory/clip/vizard.py` — the committed adapter, **known-wrong** (see the `vizard-api-contract` memory). **Rewritten in Task 6.**
- `src/clipscore/web/queries.py` — `ReviewClip` (has `platform_variant`), `_to_review_clip`, `review_detail` (its `requirements` dict already carries `target_platforms`). `src/clipscore/web/templates/review_list.html` shows `c.platform_variant`. **Updated in Task 5.**
- `src/clipscore/config.py` — `Settings` (prefix `CLIPSCORE_`): has `vizard_api_key`, `clip_engine="vizard"`, `clip_poll_interval_s=10.0`, `clip_poll_timeout_s=1800.0`, `clip_est_cost_usd=0.0`, `http_timeout_s`. **Add `vizard_usd_per_credit` (Task 1).**
- `tests/conftest.py` — `session` fixture (in-memory SQLite, all ORM tables via `StaticPool`).

## Global Constraints

Every task's requirements implicitly include these.

- **No stage crashes the scheduler.** All guard shapes (`run_clipping`, `run_matching`, `run_caption`, `acquire_job`) keep their **rollback-FIRST** never-raise contract exactly as-is. Do not weaken any guard.
- **No new schema / no migration.** `clips.platform_variant` stays as a nullable column; it is simply written `NULL` / no longer read. Adding or dropping a column is out of scope.
- **CI purity.** No test makes a real network call or hits the real Vizard API. The adapter's request/response handling is tested with `httpx.MockTransport`; the rest with the `FakeClipEngine` and pure helpers. The real-network Vizard run is manual-acceptance-only.
- **Compliance-first, unchanged.** `#ad` is still always injected by `caption.py` (untouched here). Passthrough records an operator-supplied public URL; it never scrapes or evades — an unsupported/unfetchable URL is surfaced as `manual`/`failed`, never worked around.
- **`detect_video_type` is the single mapping.** Both `create_clip_job` routing and `vizard.py` submit MUST call the same `detect_video_type`. No second copy of the URL→`videoType` logic anywhere (the original adapter broke partly because the mapping lived nowhere testable).
- **URL-only engine gets a URL.** `run_clipping` passes `source_asset.source_url` to `engine.produce(...)` unconditionally. Passing a local path was the core mistake.
- **Small footprint.** No new dependencies (httpx already present).

---

## Task 1: `detect_video_type` helper + `vizard_usd_per_credit` config

**Files:**
- Create: `src/clipscore/factory/clip/videotype.py`
- Modify: `src/clipscore/config.py` (add one field near the other `vizard_*`/`clip_*` settings, ~line 45)
- Test: `tests/test_clip_videotype.py`

**Interfaces:**
- Produces: `detect_video_type(url: str) -> tuple[int, str | None] | None` — `(videoType, ext)`; `ext` is set only for `videoType==1` (direct file), else `None`; returns `None` for any URL Vizard can't fetch by URL. Consumed by Task 3 (routing) and Task 6 (adapter).
- Produces: `Settings.vizard_usd_per_credit: float` (default `0.0`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clip_videotype.py
import pytest

from clipscore.factory.clip.videotype import detect_video_type


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=NgUNjjV_AkY", (2, None)),
    ("https://youtu.be/NgUNjjV_AkY", (2, None)),
    ("https://m.youtube.com/watch?v=abc", (2, None)),
    ("https://drive.google.com/file/d/1AbC/view?usp=sharing", (3, None)),
    ("https://vimeo.com/123456789", (4, None)),
    ("https://www.twitch.tv/videos/123456789", (9, None)),
    ("https://cdn.example.com/path/clip.mp4", (1, "mp4")),
    ("https://cdn.example.com/path/clip.MOV?token=x", (1, "mov")),
    ("https://cdn.example.com/a.avi", (1, "avi")),
    ("https://cdn.example.com/a.3gp", (1, "3gp")),
])
def test_detects_supported(url, expected):
    assert detect_video_type(url) == expected


@pytest.mark.parametrize("url", [
    "https://drive.google.com/drive/folders/1AbC",   # folder, not a file
    "https://docs.google.com/document/d/1AbC/edit",  # doc
    "https://example.com/page.html",                 # not a media file
    "https://example.com/watch",                     # no extension, unknown host
    "https://example.com/clip.txt",                  # unsupported extension
    "",
    "not a url",
])
def test_rejects_unsupported(url):
    assert detect_video_type(url) is None


def test_config_has_usd_per_credit():
    from clipscore.config import Settings
    assert Settings().vizard_usd_per_credit == 0.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_clip_videotype.py -v`
Expected: FAIL — `ModuleNotFoundError: clipscore.factory.clip.videotype`.

- [ ] **Step 3: Implement**

```python
# src/clipscore/factory/clip/videotype.py
"""URL -> Vizard `videoType` mapping (Pipeline B Stage B4.5).

Single source of truth for "which sources can Vizard fetch by URL, and as
what type". Used by BOTH `jobs/clipfactory.create_clip_job` (to route a
Vizard-fetchable URL to the no-download `passthrough` acquirer) and
`factory/clip/vizard.py` (to send the right `videoType`). Keeping one copy
prevents the mapping drift that broke the original adapter.

Vizard is URL-only. Types (probed 2026-07-15, see the `vizard-api-contract`
memory): 1=direct file (needs `ext`), 2=YouTube, 3=Google Drive *file*,
4=Vimeo, 9=Twitch. A URL we can't classify -> None (caller falls back to a
download path or surfaces it for manual handling).
"""
import re
from urllib.parse import urlparse

_DRIVE_FILE_RE = re.compile(r"/file/d/[^/]+")
_DIRECT_EXTS = ("mp4", "mov", "avi", "3gp")


def detect_video_type(url: str) -> tuple[int, str | None] | None:
    if not isinstance(url, str) or not url.strip():
        return None
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    path = parsed.path

    if "youtube.com" in host or "youtu.be" in host:
        return (2, None)
    if "drive.google.com" in host:
        return (3, None) if _DRIVE_FILE_RE.search(path) else None
    if "docs.google.com" in host:
        return None
    if "vimeo.com" in host:
        return (4, None)
    if "twitch.tv" in host:
        return (9, None)
    if "." in path:
        ext = path.rsplit(".", 1)[-1].lower()
        if ext in _DIRECT_EXTS:
            return (1, ext)
    return None
```

In `src/clipscore/config.py`, add directly under `clip_est_cost_usd`:

```python
    vizard_usd_per_credit: float = 0.0
```

- [ ] **Step 4: Verify** — `pytest tests/test_clip_videotype.py -v` PASS; `pytest -q` green.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(b4.5): detect_video_type URL->videoType helper + vizard_usd_per_credit config"`

---

## Task 2: `PassthroughAcquirer` (no download) + registry wiring

**Files:**
- Create: `src/clipscore/factory/acquire/passthrough.py`
- Modify: `src/clipscore/factory/acquire/registry.py` (add one import + one dict entry)
- Test: `tests/test_acquire_passthrough.py`

**Interfaces:**
- Consumes: `detect_video_type` (Task 1); `AcquisitionResult`/`BaseAcquirer` (existing).
- Produces: `PassthroughAcquirer` with `source_type="passthrough"`, `requires_authorization=False`. Its `acquire(source_ref, dest_path, ...)` **ignores `dest_path`** (no download): a Vizard-fetchable URL → `AcquisitionResult(status="acquired", storage_uri=None, source_url=source_ref, platform="passthrough")`; otherwise → `AcquisitionResult(status="manual", source_url=source_ref, error="unsupported_passthrough_url")`.
- Registered as `"passthrough"` in `build_registry()`.

**Note (why no `run.py` change):** `acquire_job` computes `dest`, runs `find_existing` (matches nothing for a passthrough URL) and the disk guard (a no-op unless already over budget), then calls `acq.acquire(...)`. A returned `storage_uri=None` is written straight through to `SourceAsset.storage_uri`. `requires_authorization=False` mirrors `campaign_provided` (an operator-entered `/manual` URL is explicit authorization).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_acquire_passthrough.py
from clipscore.factory.acquire.passthrough import PassthroughAcquirer
from clipscore.factory.acquire.registry import build_registry, select_acquirer


def test_supported_url_acquires_without_download():
    acq = PassthroughAcquirer()
    res = acq.acquire("https://www.youtube.com/watch?v=abc", "/tmp/should-not-be-used.mp4")
    assert res.status == "acquired"
    assert res.storage_uri is None
    assert res.source_url == "https://www.youtube.com/watch?v=abc"
    assert res.platform == "passthrough"


def test_unsupported_url_is_manual():
    acq = PassthroughAcquirer()
    res = acq.acquire("https://example.com/page.html", "/tmp/x")
    assert res.status == "manual"
    assert res.error == "unsupported_passthrough_url"
    assert res.source_url == "https://example.com/page.html"


def test_no_authorization_required():
    assert PassthroughAcquirer().requires_authorization is False


def test_registered_in_registry():
    reg = build_registry()
    acq = select_acquirer("passthrough", reg)
    assert isinstance(acq, PassthroughAcquirer)
```

- [ ] **Step 2: Run to verify they fail** — `pytest tests/test_acquire_passthrough.py -v` (FAIL: no module / not registered).

- [ ] **Step 3: Implement**

```python
# src/clipscore/factory/acquire/passthrough.py
"""No-download acquirer for Vizard-fetchable public URLs (Pipeline B B4.5).

Vizard fetches the source itself by URL, so for a YouTube/Twitch/Drive-file/
direct-mp4 link there is nothing to download: we simply record the public URL
as a `SourceAsset` (`storage_uri=None`) and let the clip step hand that URL to
the engine. A URL Vizard can't fetch is surfaced as `manual` (operator handles
it) -- never scraped or evaded.
"""
from clipscore.factory.acquire.base import AcquisitionResult, BaseAcquirer
from clipscore.factory.clip.videotype import detect_video_type


class PassthroughAcquirer(BaseAcquirer):
    source_type = "passthrough"
    requires_authorization = False

    def acquire(
        self,
        source_ref: str,
        dest_path: str,
        *,
        authorizing_campaign_id: str | None = None,
        client=None,
        ua: str = "clipscore",
        robots_cache: dict | None = None,
    ) -> AcquisitionResult:
        if detect_video_type(source_ref) is None:
            return AcquisitionResult(
                status="manual",
                source_url=source_ref,
                error="unsupported_passthrough_url",
            )
        return AcquisitionResult(
            status="acquired",
            storage_uri=None,
            source_url=source_ref,
            platform="passthrough",
        )
```

In `registry.py`, add the import and the entry:

```python
from clipscore.factory.acquire.passthrough import PassthroughAcquirer
```
```python
    return {
        "passthrough": PassthroughAcquirer(),
        "campaign_provided": CampaignProvidedAcquirer(),
        "url": UrlAcquirer(),
        "youtube": YtDlpAcquirer("youtube", ytdlp_downloader),
        "twitch": YtDlpAcquirer("twitch", ytdlp_downloader),
        "kick": YtDlpAcquirer("kick", ytdlp_downloader),
    }
```

- [ ] **Step 4: Verify** — `pytest tests/test_acquire_passthrough.py -v` PASS; `pytest -q` green.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(b4.5): no-download PassthroughAcquirer for Vizard-fetchable URLs + registry"`

---

## Task 3: Route Vizard-fetchable URLs to `passthrough` in `create_clip_job`

**Files:**
- Modify: `src/clipscore/jobs/clipfactory.py` (`create_clip_job` source-resolution block, ~lines 61-69)
- Test: `tests/test_clipfactory.py` (add cases; keep existing behavior for non-URL sources)

**Interfaces:**
- Consumes: `detect_video_type` (Task 1).
- Behavior: when `source_type`/`source_ref` are not both supplied AND the resolved source string is a Vizard-fetchable URL (`detect_video_type(...) is not None`), set `source_type="passthrough"`, `source_ref=<url>`. The resolution order becomes: explicit args → `content_bank_url` (passthrough if URL-fetchable, else `campaign_provided`) → first `target_creator` (passthrough if it is a fetchable URL, else `youtube`) → `ValueError`. An explicitly-supplied `source_type` is always respected (no override).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_clipfactory.py`)

```python
def test_create_clip_job_routes_youtube_content_bank_to_passthrough(session):
    from clipscore.config import Settings
    from clipscore.db.models import Campaign
    from clipscore.jobs.clipfactory import create_clip_job
    session.add(Campaign(
        id="c-yt", source="manual", external_id="c-yt", campaign_type="clipping",
        status="active", first_seen_at="2026-07-15T00:00:00Z",
        last_seen_at="2026-07-15T00:00:00Z",
        content_bank_url="https://www.youtube.com/watch?v=abc",
    ))
    session.commit()
    job = create_clip_job(session, "c-yt", Settings())
    assert job.source_type == "passthrough"
    assert job.source_ref == "https://www.youtube.com/watch?v=abc"


def test_create_clip_job_keeps_campaign_provided_for_drive_folder(session):
    # A Drive *folder* is not Vizard-fetchable -> stays campaign_provided.
    from clipscore.config import Settings
    from clipscore.db.models import Campaign
    from clipscore.jobs.clipfactory import create_clip_job
    session.add(Campaign(
        id="c-folder", source="manual", external_id="c-folder", campaign_type="clipping",
        status="active", first_seen_at="2026-07-15T00:00:00Z",
        last_seen_at="2026-07-15T00:00:00Z",
        content_bank_url="https://drive.google.com/drive/folders/1AbC",
    ))
    session.commit()
    job = create_clip_job(session, "c-folder", Settings())
    assert job.source_type == "campaign_provided"


def test_create_clip_job_explicit_source_type_is_respected(session):
    from clipscore.config import Settings
    from clipscore.db.models import Campaign
    from clipscore.jobs.clipfactory import create_clip_job
    session.add(Campaign(
        id="c-x", source="manual", external_id="c-x", campaign_type="clipping",
        status="active", first_seen_at="2026-07-15T00:00:00Z",
        last_seen_at="2026-07-15T00:00:00Z",
        content_bank_url="https://www.youtube.com/watch?v=abc",
    ))
    session.commit()
    job = create_clip_job(session, "c-x", Settings(),
                          source_type="campaign_provided", source_ref="https://x/y.mp4")
    assert job.source_type == "campaign_provided"
    assert job.source_ref == "https://x/y.mp4"
```

- [ ] **Step 2: Run to verify they fail** — `pytest tests/test_clipfactory.py -v` (the passthrough-routing cases FAIL: source_type is `campaign_provided`).

- [ ] **Step 3: Implement** — replace the source-resolution block in `create_clip_job`:

```python
    from clipscore.factory.clip.videotype import detect_video_type

    if source_type is None or source_ref is None:
        if campaign.content_bank_url:
            if detect_video_type(campaign.content_bank_url) is not None:
                source_type, source_ref = "passthrough", campaign.content_bank_url
            else:
                source_type, source_ref = "campaign_provided", campaign.content_bank_url
        else:
            creators = _as_list(campaign.target_creator)
            if creators:
                if detect_video_type(creators[0]) is not None:
                    source_type, source_ref = "passthrough", creators[0]
                else:
                    source_type, source_ref = "youtube", creators[0]
            else:
                raise ValueError("no acquirable source for campaign")
```

(Put the `detect_video_type` import at module top with the others, not inline, if the reviewer prefers — either is acceptable; match the file's existing import style.)

- [ ] **Step 4: Verify** — `pytest tests/test_clipfactory.py tests/test_cli_clip.py -v` PASS; `pytest -q` green. (Confirm no existing `create_clip_job` test regressed — non-URL creators still route to `youtube`, non-URL banks to `campaign_provided`.)

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(b4.5): route Vizard-fetchable URLs to passthrough in create_clip_job"`

---

## Task 4: Engine/spec reshape (`base.py`) + `run_clipping` passthrough & retention fix (`produce.py`)

**Files:**
- Modify: `src/clipscore/factory/clip/base.py` (`ClipSpec`, `ProducedClip`, `derive_specs`, `FakeClipEngine`, `BaseClipEngine.produce` docstring)
- Modify: `src/clipscore/factory/clip/produce.py` (`_run_clipping_inner`)
- Test: `tests/test_clip_base.py`, `tests/test_clip_produce.py`

**Interfaces (post-reshape):**
- `ClipSpec`: `min_len_s: int`, `max_len_s: int` — **`platform_variant` removed** (it is now a length window only).
- `ProducedClip`: `platform_variant: str | None = None` **kept as an optional field but defaulted to `None`** (so nothing breaks if an engine omits it); real engines no longer set it.
- `derive_specs(campaign, settings) -> ClipSpec` — **returns a single `ClipSpec`** (the campaign's `[clip_min_len_s, clip_max_len_s]` if both set, else `(0, 0)` = "no preference"). Consumed by `produce.py` and the engines.
- `BaseClipEngine.produce(source_uri, spec: ClipSpec, *, dest_dir) -> list[ProducedClip]` — takes the single spec; returns N clips of the engine's own count.
- `FakeClipEngine.produce` returns a **fixed list of 3** `ProducedClip`s (duration `spec.min_len_s`, `engine="fake"`, `platform_variant=None`).
- `_run_clipping_inner`: selects the job's `SourceAsset` by `clip_job_id` **without** the `storage_uri` filter; calls `engine.produce(source_asset.source_url, derive_specs(campaign, settings), dest_dir=dest_dir)`; writes `Clip` rows **without** `platform_variant` (leave it `NULL`); guards the retention delete with `if source_asset.storage_uri:`.

- [ ] **Step 1: Write the failing tests** — replace platform-oriented cases in `tests/test_clip_base.py`:

```python
# tests/test_clip_base.py  (reshaped)
from types import SimpleNamespace

from clipscore.config import Settings
from clipscore.factory.clip.base import (
    ClipSpec, FakeClipEngine, derive_specs,
)


def _campaign(**kw):
    base = dict(clip_min_len_s=None, clip_max_len_s=None,
                target_platforms='["tiktok"]')
    base.update(kw)
    return SimpleNamespace(**base)


def test_derive_specs_returns_single_window_from_campaign():
    spec = derive_specs(_campaign(clip_min_len_s=30, clip_max_len_s=90), Settings())
    assert isinstance(spec, ClipSpec)
    assert (spec.min_len_s, spec.max_len_s) == (30, 90)


def test_derive_specs_defaults_when_no_window():
    spec = derive_specs(_campaign(), Settings())
    assert (spec.min_len_s, spec.max_len_s) == (0, 0)


def test_clipspec_has_no_platform_variant():
    assert "platform_variant" not in ClipSpec.model_fields


def test_fake_engine_returns_multiple_platformless_clips():
    spec = ClipSpec(min_len_s=30, max_len_s=90)
    clips = FakeClipEngine().produce("https://youtu.be/abc", spec, dest_dir="/tmp/x")
    assert len(clips) == 3
    assert all(c.platform_variant is None for c in clips)
    assert all(c.engine == "fake" for c in clips)
    assert all(c.duration_s == 30 for c in clips)
```

And in `tests/test_clip_produce.py`, add/adjust:

```python
def test_run_clipping_passes_source_url_and_writes_platformless_clips(session):
    """Passthrough source (storage_uri=None): engine gets the public URL,
    Clip rows are written with no platform_variant, and no retention delete
    is attempted on a None path."""
    from clipscore.config import Settings
    from clipscore.db.models import Campaign, ClipJob, SourceAsset, Clip
    from clipscore.factory.clip.base import FakeClipEngine
    from clipscore.factory.clip.produce import run_clipping

    session.add(Campaign(
        id="c1", source="manual", external_id="c1", campaign_type="clipping",
        status="active", first_seen_at="t", last_seen_at="t",
        clip_min_len_s=30, clip_max_len_s=90, target_platforms='["tiktok"]',
    ))
    job = ClipJob(campaign_id="c1", source_type="passthrough",
                  source_ref="https://youtu.be/abc", status="acquired",
                  created_at="t")
    session.add(job); session.commit()
    session.add(SourceAsset(clip_job_id=job.id, creator="@me",
                            source_url="https://youtu.be/abc",
                            storage_uri=None, downloaded_at="t"))
    session.commit()

    captured = {}
    class _Spy(FakeClipEngine):
        def produce(self, source_uri, spec, *, dest_dir):
            captured["uri"] = source_uri
            return super().produce(source_uri, spec, dest_dir=dest_dir)

    run_clipping(session, job, Settings(), engine=_Spy())
    assert captured["uri"] == "https://youtu.be/abc"   # URL, not a local path
    assert job.status == "produced"
    clips = session.query(Clip).all()
    assert clips and all(c.platform_variant is None for c in clips)
```

Update the one existing assertion that breaks — `test_clipping_writes_clips_and_deletes_source` line 29:

```python
    # was: assert len(clips) == 1 and clips[0].platform_variant == "tiktok" and ...
    assert len(clips) == 3
    assert all(c.platform_variant is None for c in clips)
    assert all(c.status == "produced" for c in clips)
```

Its `_setup` builds a `SourceAsset` with `source_url="ref"` + a local `storage_uri`; `run_clipping` now passes `"ref"` to the (ignoring) `FakeClipEngine`, and retention still deletes the local file (`not src.exists()`, `sa.storage_uri is None` both still hold). The two never-raise tests (`..._engine_error...`, `..._commit_failure...`) pass unchanged — `Boom.produce(self, *a, **k)` already absorbs the single-spec arg, and a 3-clip insert into a dropped `clips` table still fails into the guard.

- [ ] **Step 2: Run to verify they fail** — `pytest tests/test_clip_base.py tests/test_clip_produce.py -v`.

- [ ] **Step 3: Implement** — reshape `base.py`:

```python
class ClipSpec(BaseModel):
    min_len_s: int
    max_len_s: int


class ProducedClip(BaseModel):
    platform_variant: str | None = None
    storage_uri: str
    duration_s: int | None = None
    transcript: str | None = None
    engine: str
    engine_clip_id: str | None = None
    cost_usd: float | None = None
```

`derive_specs` becomes (replace the whole function; drop `_PLATFORM_VARIANT_MAP`/`_FALLBACK_LENGTHS`/`_target_platforms` if now unused — verify with grep before deleting):

```python
def derive_specs(campaign, settings: Settings) -> ClipSpec:
    """The clip-length preference for this campaign as a single window.
    Vizard picks the clips and their count; the window is advisory (used for
    `preferLength` and as a matching hint). Both bounds present -> use them;
    otherwise (0, 0) = 'no preference'."""
    lo = getattr(campaign, "clip_min_len_s", None)
    hi = getattr(campaign, "clip_max_len_s", None)
    if lo is not None and hi is not None:
        return ClipSpec(min_len_s=lo, max_len_s=hi)
    return ClipSpec(min_len_s=0, max_len_s=0)
```

`FakeClipEngine`:

```python
class FakeClipEngine(BaseClipEngine):
    name = "fake"

    def produce(self, source_uri: str, spec: ClipSpec, *, dest_dir: str) -> list[ProducedClip]:
        return [
            ProducedClip(
                platform_variant=None,
                storage_uri=f"{dest_dir}/clip-{i}.mp4",
                duration_s=spec.min_len_s,
                transcript="fake transcript",
                engine="fake",
                engine_clip_id=f"fake-{i}",
                cost_usd=0.0,
            )
            for i in range(3)
        ]
```

Update `BaseClipEngine.produce`'s signature/docstring to `produce(self, source_uri, spec: ClipSpec, *, dest_dir)`.

In `produce.py` `_run_clipping_inner`:

```python
    source_asset = session.execute(
        select(SourceAsset).where(SourceAsset.clip_job_id == clip_job.id)
    ).scalars().one()

    campaign = session.execute(
        select(Campaign).where(Campaign.id == clip_job.campaign_id)
    ).scalars().one()

    spec = derive_specs(campaign, settings)
    dest_dir = f"{settings.media_dir}/clips/{clip_job.id}"
    os.makedirs(dest_dir, exist_ok=True)

    produced = engine.produce(source_asset.source_url, spec, dest_dir=dest_dir)

    for p in produced:
        session.add(
            Clip(
                source_asset_id=source_asset.id,
                platform_variant=None,
                storage_uri=p.storage_uri,
                duration_s=p.duration_s,
                transcript=p.transcript,
                engine=p.engine,
                engine_clip_id=p.engine_clip_id,
                cost_usd=p.cost_usd,
                status="produced",
                created_at=now,
            )
        )
    session.commit()

    # Retention: delete the local source file only if one was downloaded.
    # A passthrough source has storage_uri=None -- os.remove(None) raises
    # TypeError (NOT OSError), which the guard below would miss, so skip it.
    if source_asset.storage_uri:
        try:
            os.remove(source_asset.storage_uri)
        except OSError:
            log.warning("clip_source_delete_failed", clip_job_id=clip_job.id,
                        storage_uri=source_asset.storage_uri)
        source_asset.storage_uri = None

    clip_job.status = "produced"
    clip_job.error = None
    session.commit()
```

- [ ] **Step 4: Verify** — `pytest tests/test_clip_base.py tests/test_clip_produce.py -v` PASS. `pytest -q` will still show failures in `match`/`web`/`e2e` (fixed in Task 5) — that's expected; confirm only Task-4 files' tests pass here.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(b4.5): reshape engine to platformless N-clip output + run_clipping passes source_url, guards retention"`

---

## Task 5: `match.py` drops the platform gate + review surface shows campaign platforms

**Files:**
- Modify: `src/clipscore/factory/clip/match.py` (`match_clip`; remove `_VARIANT_PLATFORM` + `_platform_matches`)
- Modify: `src/clipscore/web/queries.py` (`ReviewClip` / `_to_review_clip`)
- Modify: `src/clipscore/web/templates/review_list.html`
- Test: `tests/test_clip_match.py`, `tests/test_web_queries.py`, `tests/test_web_review.py`, `tests/test_web_e2e.py`

**Interfaces:**
- `match_clip(session, clip)` matches a candidate campaign on **creator + length only** (no platform). `match_score = cvs_pct * spec_fit` unchanged (`spec_fit` = 1.0 if the campaign has a length window, else 0.9). Ranked/`meets_requirements` unchanged.
- `ReviewClip` **drops `platform_variant`** (was always `None` post-Task-4). Review list shows duration only; the detail page's `requirements["target_platforms"]` (already present) is where "which platforms" surfaces.

- [ ] **Step 1: Write/adjust the failing tests**

`tests/test_clip_match.py` uses `_camp(session, cid, pct, **kw)` (seeds an active clipping `Campaign` `target_creator='["@diego"]'`, `target_platforms='["tiktok"]'` + a `CampaignScore`) and `_clip(session, variant=..., dur=..., creator="diego")` (seeds a `ClipJob`/`SourceAsset(creator=...)`/produced `Clip`). Two changes:

**(a) DELETE `test_platform_mismatch_excludes`** — it asserts a `variant="shorts"` clip returns `[]` because shorts→youtube isn't in the campaign's platforms. Under Decision B there is no platform gate, so that clip now *matches* (creator+length ok) — the test's premise is gone. Remove it.

**(b) ADD** a case proving a **platformless** clip (`variant=None`) matches on creator+length:

```python
def test_platformless_clip_matches_on_creator_and_length(session):
    _camp(session, "c1", 0.9, clip_min_len_s=60, clip_max_len_s=120)
    _, clip = _clip(session, variant=None, dur=90)   # no platform_variant
    rows = match_clip(session, clip)
    assert [r["campaign_id"] for r in rows] == ["c1"]
    assert rows[0]["rank"] == 1 and rows[0]["match_score"] == 0.9
```

The remaining cases (`test_match_ranks_by_cvs_percentile_times_specfit`, `test_length_out_of_window_excludes`, `test_run_matching_writes_rows_and_sets_status`) keep passing unchanged — they never depended on the platform gate (their clips use the default `variant="tiktok"` which matched `target_platforms='["tiktok"]'`; with the gate removed they still match).

`tests/test_web_queries.py` / `tests/test_web_review.py` — drop any `platform_variant` assertion on `ReviewClip`; assert the review-detail `requirements` still carries `target_platforms`.

`tests/test_web_e2e.py` — **verify it still passes; it likely needs no change.** Its `content_bank_url="https://drive.google.com/e2e"` is not a `/file/d/` link, so `detect_video_type` returns `None` and routing stays `campaign_provided` (where its `_FakeAcquirer` is registered). Post-reshape `FakeClipEngine` yields 3 platformless clips that each match the campaign on creator+length; the test only asserts "at least one ready clip" (`assert ready`) and operates on `ready[0]`, so it passes as-is. Run it — if the 3-clip fan-out surfaces any incidental assertion (e.g. an exact `Outcome`/match count elsewhere), adjust *that* assertion only; do not weaken the dup-warning check.

- [ ] **Step 2: Run to verify they fail** — `pytest tests/test_clip_match.py tests/test_web_queries.py tests/test_web_review.py tests/test_web_e2e.py -v`.

- [ ] **Step 3: Implement**

`match.py` — delete `_VARIANT_PLATFORM` and `_platform_matches`; in `match_clip` remove the `platform`/`_platform_matches` lines:

```python
def match_clip(session: Session, clip: Clip) -> list[dict]:
    """Pure computation -- no writes. Candidate live campaigns for `clip`,
    ranked by `match_score` descending. Platform is a campaign property, not a
    clip property (Vizard clips are format-identical vertical short-form that
    serve every short-form platform), so matching is on creator + length only;
    the campaign's target_platforms says where to post."""
    source_asset = session.execute(
        select(SourceAsset).where(SourceAsset.id == clip.source_asset_id)
    ).scalars().one()

    candidates = []
    for campaign, score in eligible_latest_scores(session):
        if not _creator_matches(campaign, source_asset.creator):
            continue
        if not _length_ok(campaign, clip.duration_s):
            continue

        has_window = campaign.clip_min_len_s is not None or campaign.clip_max_len_s is not None
        spec_fit = 1.0 if has_window else 0.9
        cvs_pct = score.cvs_niche_percentile or 0.0
        candidates.append({"campaign_id": campaign.id, "match_score": cvs_pct * spec_fit})

    candidates.sort(key=lambda c: c["match_score"], reverse=True)
    for i, c in enumerate(candidates, start=1):
        c["rank"] = i
        c["meets_requirements"] = 1
    return candidates
```

`queries.py` — remove `platform_variant` from `ReviewClip` and `_to_review_clip`:

```python
class ReviewClip(BaseModel):
    clip_id: int
    duration_s: int | None = None
    status: str
    cost_usd: float | None = None
    campaign_id_of_job: str | None = None
```
```python
def _to_review_clip(session: Session, clip: Clip) -> ReviewClip:
    return ReviewClip(
        clip_id=clip.id, duration_s=clip.duration_s,
        status=clip.status, cost_usd=clip.cost_usd,
    )
```

`review_list.html` line 8 — drop the variant token:

```html
  <li><a href="/review/{{ c.clip_id }}">Clip {{ c.clip_id }} — {{ c.duration_s or "?" }}s</a></li>
```

- [ ] **Step 4: Verify** — `pytest -q` **fully green** (this task closes the Task-4 cross-file breakage).

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(b4.5): match on creator+length only (platform is a campaign property); review surface drops clip variant"`

---

## Task 6: Rewrite `factory/clip/vizard.py` to the real API contract (CI-tested via `MockTransport`)

**Files:**
- Modify: `src/clipscore/factory/clip/vizard.py` (rewrite `_submit`/`_poll`/`_download`, use `detect_video_type`, record `creditsUsed`)
- Test: `tests/test_clip_vizard.py` (NEW — `httpx.MockTransport`, **no real network**)

**Interfaces:**
- `VizardEngine(settings).produce(source_uri, spec: ClipSpec, *, dest_dir) -> list[ProducedClip]` — matches the reshaped `BaseClipEngine.produce`.
- Submit: `detect_video_type(source_uri)` → `videoType` (+`ext`); `POST /project/create` with `{"videoUrl", "videoType", "lang":"en", "preferLength":[0]}` (+`"ext"` when `videoType==1`); expect `{"code":2000, "projectId": <int>}`; a missing type → `RuntimeError`.
- Poll: `GET /project/query/{projectId}` → `code==1000` keep polling; `code==2000` done (read `videos`, `creditsUsed`); anything else → `RuntimeError`; timeout → `TimeoutError`.
- Download each `videos[i]["videoUrl"]` to `f"{dest_dir}/clip-{i}.mp4"`; `duration_s` from `videoMsDuration // 1000`; `transcript` from `transcript`; `engine="vizard"`; `engine_clip_id` from `videoId`; `platform_variant=None`; `cost_usd = creditsUsed * settings.vizard_usd_per_credit / len(videos)` (split evenly so the batch sums to the true project cost; `0.0` when the rate is unset).

**Why CI-testable now:** the original adapter shipped broken because nothing exercised its wire handling. `httpx.MockTransport` lets CI drive the exact create/query/download JSON **without any real network**, catching field-name/status-code regressions. The real-key, real-network run stays manual-acceptance.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_clip_vizard.py
import json

import httpx

from clipscore.config import Settings
from clipscore.factory.clip.base import ClipSpec
from clipscore.factory.clip.vizard import VizardEngine


def _engine(handler, tmp_dir, **over):
    settings = Settings(_env_file=None, vizard_api_key="k", clip_poll_interval_s=0.0,
                        vizard_usd_per_credit=0.10, **over)
    eng = VizardEngine(settings)
    eng._transport = httpx.MockTransport(handler)   # test seam (see Step 3)
    return eng


def test_produce_submits_videotype_polls_and_downloads(tmp_path):
    calls = {"create": 0, "query": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/project/create"):
            calls["create"] += 1
            body = json.loads(request.content)
            assert body["videoType"] == 2            # YouTube
            assert body["videoUrl"] == "https://youtu.be/abc"
            assert body["preferLength"] == [0]
            return httpx.Response(200, json={"code": 2000, "projectId": 42})
        if "/project/query/" in request.url.path:
            calls["query"] += 1
            if calls["query"] == 1:
                return httpx.Response(200, json={"code": 1000})   # processing
            return httpx.Response(200, json={
                "code": 2000, "creditsUsed": 14,
                "videos": [
                    {"videoUrl": "https://cdn/v0.mp4", "videoMsDuration": 32000,
                     "transcript": "t0", "videoId": "v0", "viralScore": "9"},
                    {"videoUrl": "https://cdn/v1.mp4", "videoMsDuration": 41000,
                     "transcript": "t1", "videoId": "v1", "viralScore": "7"},
                ],
            })
        # clip download
        return httpx.Response(200, content=b"FAKEMP4")

    eng = _engine(handler, tmp_path)
    clips = eng.produce("https://youtu.be/abc", ClipSpec(min_len_s=0, max_len_s=0),
                        dest_dir=str(tmp_path))
    assert calls["create"] == 1 and calls["query"] == 2
    assert len(clips) == 2
    assert clips[0].engine == "vizard" and clips[0].platform_variant is None
    assert clips[0].duration_s == 32 and clips[0].engine_clip_id == "v0"
    # 14 credits * $0.10 / 2 clips = $0.70 each
    assert round(clips[0].cost_usd, 2) == 0.70
    assert (tmp_path / "clip-0.mp4").read_bytes() == b"FAKEMP4"


def test_produce_raises_on_unsupported_source(tmp_path):
    def handler(request):  # should never be called
        raise AssertionError("no HTTP call expected")
    eng = _engine(handler, tmp_path)
    try:
        eng.produce("https://example.com/page.html", ClipSpec(min_len_s=0, max_len_s=0),
                    dest_dir=str(tmp_path))
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_produce_raises_on_error_code(tmp_path):
    def handler(request):
        if request.url.path.endswith("/project/create"):
            return httpx.Response(200, json={"code": 2000, "projectId": 1})
        return httpx.Response(200, json={"code": 4000, "errMsg": "bad source"})
    eng = _engine(handler, tmp_path)
    try:
        eng.produce("https://youtu.be/abc", ClipSpec(min_len_s=0, max_len_s=0),
                    dest_dir=str(tmp_path))
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
```

- [ ] **Step 2: Run to verify they fail** — `pytest tests/test_clip_vizard.py -v`.

- [ ] **Step 3: Implement** — rewrite `vizard.py`. Add a `_transport` test seam (defaults to `None` → real network; tests inject a `MockTransport`). Update the module docstring (it is now CI-tested via `MockTransport`; only the real-key run is manual-acceptance).

```python
import time

import httpx

from clipscore.config import Settings
from clipscore.factory.acquire import storage
from clipscore.factory.clip.base import BaseClipEngine, ClipSpec, ProducedClip
from clipscore.factory.clip.videotype import detect_video_type

_API_BASE = "https://elb-api.vizard.ai/hvizard-server-front/open-api/v1"


class VizardEngine(BaseClipEngine):
    name = "vizard"

    def __init__(self, settings: Settings):
        if not settings.vizard_api_key:
            raise RuntimeError(
                "VizardEngine requires settings.vizard_api_key (CLIPSCORE_VIZARD_API_KEY)"
            )
        self.settings = settings
        self._headers = {"VIZARDAI_API_KEY": settings.vizard_api_key,
                         "Content-Type": "application/json"}
        self._transport = None  # tests inject an httpx.MockTransport here

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=_API_BASE, headers=self._headers,
                            timeout=self.settings.http_timeout_s,
                            transport=self._transport)

    def produce(self, source_uri: str, spec: ClipSpec, *, dest_dir: str) -> list[ProducedClip]:
        detected = detect_video_type(source_uri)
        if detected is None:
            raise RuntimeError(f"Vizard cannot fetch source by URL: {source_uri!r}")
        video_type, ext = detected
        with self._client() as client:
            project_id = self._submit(client, source_uri, video_type, ext)
            videos, credits_used = self._poll(client, project_id)
            return self._download(client, videos, credits_used, dest_dir=dest_dir)

    def _submit(self, client, source_uri, video_type, ext):
        payload = {"videoUrl": source_uri, "videoType": video_type,
                   "lang": "en", "preferLength": [0]}
        if video_type == 1:
            payload["ext"] = ext or "mp4"
        resp = client.post("/project/create", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 2000 or "projectId" not in data:
            raise RuntimeError(f"Vizard create rejected: {data}")
        return data["projectId"]

    def _poll(self, client, project_id):
        deadline = time.monotonic() + self.settings.clip_poll_timeout_s
        while True:
            resp = client.get(f"/project/query/{project_id}")
            resp.raise_for_status()
            data = resp.json()
            code = data.get("code")
            if code == 2000:
                return data.get("videos", []), data.get("creditsUsed", 0)
            if code != 1000:
                raise RuntimeError(f"Vizard project {project_id} failed: {data}")
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Vizard project {project_id} did not complete within "
                    f"{self.settings.clip_poll_timeout_s}s"
                )
            time.sleep(self.settings.clip_poll_interval_s)

    def _download(self, client, videos, credits_used, *, dest_dir):
        n = len(videos)
        per_clip_cost = (
            credits_used * self.settings.vizard_usd_per_credit / n if n else 0.0
        )
        produced = []
        for i, clip in enumerate(videos):
            video_url = clip.get("videoUrl")
            dest_path = f"{dest_dir}/clip-{i}.mp4"
            if video_url:
                storage.ensure_parent(dest_path)
                with client.stream("GET", video_url) as resp:
                    resp.raise_for_status()
                    with open(dest_path, "wb") as f:
                        for chunk in resp.iter_bytes():
                            f.write(chunk)
            ms = clip.get("videoMsDuration")
            produced.append(ProducedClip(
                platform_variant=None,
                storage_uri=dest_path,
                duration_s=ms // 1000 if ms else None,
                transcript=clip.get("transcript"),
                engine="vizard",
                engine_clip_id=str(clip.get("videoId")) if clip.get("videoId") else None,
                cost_usd=per_clip_cost,
            ))
        return produced
```

Note: the clip-download `client.stream` goes through the same base-URL client. In the test, the download `videoUrl` is absolute (`https://cdn/...`); httpx routes absolute URLs through the same transport, so the `MockTransport` handler receives it. Keep the download on `client` (not a new client) so the seam covers it.

- [ ] **Step 4: Verify** — `pytest tests/test_clip_vizard.py -v` PASS; `pytest -q` fully green. Confirm `python -c "import clipscore.factory.clip.vizard"` succeeds (no import-time network).

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(b4.5): rewrite Vizard adapter to real API contract (videoType/code:2000/videos/creditsUsed), CI-tested via MockTransport"`

---

## Definition of done

- `pytest -q` fully green; `pytest --collect-only -q` clean (no import errors).
- `detect_video_type` is the sole URL→`videoType` mapping, used by both routing and the adapter.
- A manual `/manual` YouTube URL routes to `passthrough`, reaches `acquired` with `storage_uri=None`, and `run_clipping` hands the public URL to the engine.
- With `FakeClipEngine`, the full `queued→ready` lifecycle produces 3 platformless clips, each matched to the seeded campaign on creator+length with an `#ad` caption.
- `VizardEngine` wire handling is CI-verified against the real contract via `MockTransport`; no test touches the real network.
- No new schema/migration; `clips.platform_variant` remains nullable and unused.

## Manual acceptance (operator, not CI)

With a real `CLIPSCORE_VIZARD_API_KEY` and `CLIPSCORE_CLIP_ENGINE=vizard`: `clipscore web` → `/manual` a public YouTube/Drive-file URL → run `process_clip_jobs` → `ready` clips appear in `/review` with ranked matches → mark posted. Record the real `creditsUsed` and set `CLIPSCORE_VIZARD_USD_PER_CREDIT` from the account plan (feeds the B5 cost cap).

## Out of scope (later phases)

- Drive-*folder* enumeration; a pre-approved-clips (no-engine) review path; local-download→temp-public-host fallback for non-fetchable sources (Kick, private Drive).
- `MONTHLY_CAP_USD` pause/alert + retention hardening (Phase B5).
- Dropping the now-unused `clips.platform_variant` column (a table rebuild; not worth it).
