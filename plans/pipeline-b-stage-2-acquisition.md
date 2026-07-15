# Pipeline B — Stage 2 (B2): Acquisition Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give Pipeline B a pluggable **acquisition layer** that fetches a campaign's source footage into local storage — the brand's **campaign-provided** footage bank (primary) and generic **URLs** first, then creator **VODs** (`youtube`/`twitch`/`kick`) via `yt-dlp` — deduped, retention-swept, and **drop-don't-evade** compliant, filling the existing `clip_jobs`/`source_assets` tables.

**Architecture:** A small `BaseAcquirer` ABC (mirroring A's `BaseIngester`) with one method, `acquire(...)`, and a `source_type → acquirer` registry. Direct-download acquirers share one robots-checked, `classify_response`-guarded downloader; VOD acquirers lazily import `yt-dlp` (an **optional** extra) behind an injectable downloader seam so **CI never touches the real network or yt-dlp**. A single `acquire_job()` orchestrator selects the acquirer, enforces the ToS/authorization gate, dedups by content-addressed path, writes the `SourceAsset`, and is wrapped so **acquisition can never crash the scheduler** (mirrors the `enrich` guard). Storage is the local filesystem behind a thin seam.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x, httpx (direct downloads), `yt-dlp` (new **optional** dep, VOD acquirers only, lazy-imported), pydantic, structlog, pytest.

## Context

This is **Phase B2** of `PIPELINE_B_CLIP_FACTORY.md` (source of truth — see its **Phase B2** entry and the **Compliance & legal posture** section). Pipeline A Stages 1–4 and Pipeline B Stage 1 (schema + extraction) are merged. B2 consumes the schema B1 landed (migration `0004`): `clip_jobs` and `source_assets` already exist — **B2 adds no schema**.

**Design decisions this plan encodes** (approved 2026-07-15):
- **Campaign-provided footage is the primary path** and the cleanest legally; VODs are ToS-gray and justified only by an authorizing campaign.
- **Drop-don't-evade** applies exactly as in A's ingestion: a block/challenge → log and skip, never circumvent. An auth-walled or folder share link → mark for **manual capture**, never scrape around it (CLAUDE.md: "Sources that forbid automated access are handled by manual capture").
- **`yt-dlp` is an optional extra**, lazy-imported — the package imports and the suite runs with it absent (mirrors how `extract_llm.py` lazily imports `anthropic`).
- **Local filesystem storage** (small-footprint principle) behind a seam so a cloud backend can slot in later.

## Existing code this builds on

- `src/clipscore/db/models.py` — `ClipJob` (`campaign_id`, `source_type`, `source_ref`, `status`, `est_cost_usd`, `error`, `created_at`) and `SourceAsset` (`clip_job_id`, `creator`, `platform`, `source_url`, `authorizing_campaign_id`, `storage_uri`, `duration_s`, `bytes`, `downloaded_at`) — created by migration `0004`. **B2 fills these; no new columns.** `Campaign` (`.status`) for the authorization gate.
- `src/clipscore/ingest/detect.py` — `classify_response(status_code, body) -> str` and `SourceHalted`. **`classify_response` is HTML-page-specific**: it returns `"ok"` only when the body contains `self.__next_f.push` and is ≥1000 bytes, so it must be used **only on an HTML response** to distinguish a bot-challenge from a plain page — **never** run it on a binary video body (it would always reject it).
- `src/clipscore/factory/whop.py` — `_robots_allowed(client, ua, url, robots_cache)`: the robots.txt check (cached per run) to **reuse** for direct downloads. `fetch_page_text` is the drop-don't-evade fetch pattern to mirror.
- `src/clipscore/config.py` — `Settings` (pydantic-settings, prefix `CLIPSCORE_`; has `user_agent`, `http_timeout_s`, `raw_retention_days=14`). **Add `media_dir`, `max_media_gb`.**
- `src/clipscore/time.py` — `utcnow_iso()` → `"%Y-%m-%dT%H:%M:%SZ"` (lexicographically sortable, so retention cutoffs compare as strings).
- `src/clipscore/factory/enrich.py` — the **never-raise guard** pattern (`try/except` → graceful fallback, `session.commit()`) to mirror in `acquire_job`.
- `tests/conftest.py` — `session` fixture (in-memory SQLite, all ORM tables). `pyproject.toml` — `[project.optional-dependencies]` with a `dev` extra; add a `media` extra.

## Global Constraints

Every task's requirements implicitly include these.

- **Acquisition never crashes the scheduler.** `acquire_job` wraps all work in `try/except`; any unexpected error sets `clip_job.status="failed"` + `clip_job.error`, commits, and returns normally. A failed acquisition never propagates (same guard as `enrich_campaign`).
- **Drop-don't-evade.** On a block/challenge (403/429, CAPTCHA, Cloudflare/DataDome, login-wall bot challenge): **log and stop**, `status="blocked"`, never spoof headers, solve a CAPTCHA, or retry with different tactics. An auth-walled/folder/unsupported share link → `status="manual"` (operator captures by hand). Robots.txt is checked (via `_robots_allowed`, cached per run) before any direct GET; a disallow → skip.
- **`yt-dlp` is optional and lazy.** It appears only in a `[project.optional-dependencies] media` extra and is imported **inside** the VOD download function. `import clipscore.factory.acquire.vod` and the whole suite must succeed with `yt-dlp` uninstalled. If a real VOD download is attempted without it installed → `status="failed"`, `error="yt_dlp_unavailable"`.
- **CI purity.** No test makes a real network call or invokes real `yt-dlp`. Direct downloads are tested with `httpx.MockTransport`; VOD acquirers through an **injected fake downloader**. The real yt-dlp path is manual-acceptance-only.
- **Authorization (ToS) gate.** Acquirers set `requires_authorization`: `campaign_provided` → `False`; `url` and all VODs → `True`. When `True`, `acquire_job` refuses (`failed`, `error="unauthorized"`) unless the job's `campaign_id` resolves to an **existing, `active`** campaign, and records that id as the `SourceAsset.authorizing_campaign_id`.
- **Local FS storage, content-addressed.** Files live under `settings.media_dir` (default `media/`, already gitignored) at `<media_dir>/<source_type>/<sha256(source_ref)[:16]>.<ext>`. Same `source_ref` → same path → **fetched once**; a job whose file already exists reuses it with no re-download.
- **Retention & disk guard.** `sweep_retention` deletes source files older than `raw_retention_days` and nulls their `storage_uri`. `acquire_job` refuses (`failed`, `error="disk_guard"`) when `media_dir` usage already exceeds `max_media_gb`. (Immediate-post-clip deletion is B3, out of scope here.)
- **No new schema.** Fill `clip_jobs`/`source_assets` from `0004`. `clip_job.status` is limited to `queued|acquiring|acquired|clipping|produced|matched|failed`; `blocked`/`manual`/other non-acquired outcomes map to `status="failed"` with the reason in `clip_job.error` (a `SourceAsset` row is written **only** on `acquired`).

---

## Task 1: Acquire package scaffold — `BaseAcquirer`, `AcquisitionResult`, storage seam, config, optional extra

**Files:**
- Create: `src/clipscore/factory/acquire/__init__.py`, `src/clipscore/factory/acquire/base.py`, `src/clipscore/factory/acquire/storage.py`
- Modify: `src/clipscore/config.py`, `pyproject.toml`
- Test: `tests/test_acquire_base.py`, `tests/test_acquire_storage.py`, `tests/test_config_acquire.py`

**Interfaces:**
- Produces `factory/acquire/base.py`:
  - `AcquisitionResult(BaseModel)` — `status: str` (`"acquired" | "blocked" | "manual" | "failed"`), `storage_uri: str | None = None`, `bytes: int | None = None`, `duration_s: int | None = None`, `creator: str | None = None`, `platform: str | None = None`, `source_url: str | None = None`, `error: str | None = None`.
  - `BaseAcquirer(ABC)` — class attrs `source_type: str = ""`, `requires_authorization: bool = False`; abstract `acquire(self, source_ref: str, dest_path: str, *, authorizing_campaign_id: str | None = None, client=None, ua: str = "clipscore", robots_cache: dict | None = None) -> AcquisitionResult`.
- Produces `factory/acquire/storage.py`:
  - `stem_key(source_type: str, source_ref: str) -> str` → `f"{source_type}/{sha256(source_ref)[:16]}"`.
  - `path_for(media_dir: str, stem: str, ext: str) -> str` → `"<media_dir>/<stem><ext>"` (ext includes the dot, or `""`).
  - `find_existing(media_dir: str, source_type: str, source_ref: str) -> str | None` — first non-empty file matching `<media_dir>/<stem>.*` (or the extensionless stem), else `None`.
  - `dir_usage_bytes(media_dir: str) -> int` — total size of files under `media_dir` (0 if absent).
  - `ensure_parent(path: str) -> None` — `mkdir(parents=True, exist_ok=True)` on the parent dir.
- Produces on `Settings`: `media_dir: str = "media/"`, `max_media_gb: float = 50.0`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config_acquire.py
from clipscore.config import Settings

def test_acquire_config_defaults():
    s = Settings(_env_file=None)  # hermetic — ignore the developer's .env
    assert s.media_dir == "media/"
    assert s.max_media_gb == 50.0
    assert s.raw_retention_days == 14  # already present, used by retention sweep
```

```python
# tests/test_acquire_base.py
from clipscore.factory.acquire.base import AcquisitionResult, BaseAcquirer

def test_acquisition_result_defaults():
    r = AcquisitionResult(status="manual", source_url="https://drive.google.com/x")
    assert r.status == "manual"
    assert r.storage_uri is None and r.bytes is None and r.error is None

def test_base_acquirer_is_abstract():
    import pytest
    with pytest.raises(TypeError):
        BaseAcquirer()  # abstract acquire() cannot be instantiated
```

```python
# tests/test_acquire_storage.py
from clipscore.factory.acquire import storage

def test_stem_key_is_stable_and_source_typed():
    k1 = storage.stem_key("campaign_provided", "https://drive.google.com/uc?id=A")
    k2 = storage.stem_key("campaign_provided", "https://drive.google.com/uc?id=A")
    assert k1 == k2 and k1.startswith("campaign_provided/")
    assert k1 != storage.stem_key("youtube", "https://drive.google.com/uc?id=A")

def test_path_for_joins_media_dir_stem_ext():
    assert storage.path_for("media/", "youtube/abc123", ".mp4") == "media/youtube/abc123.mp4"

def test_find_existing_returns_nonempty_match(tmp_path):
    (tmp_path / "campaign_provided").mkdir()
    stem = storage.stem_key("campaign_provided", "ref-1")
    f = tmp_path / f"{stem}.mp4"
    f.write_bytes(b"x" * 10)
    assert storage.find_existing(str(tmp_path), "campaign_provided", "ref-1") == str(f)
    assert storage.find_existing(str(tmp_path), "campaign_provided", "ref-missing") is None

def test_dir_usage_bytes_sums_files(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f.bin").write_bytes(b"x" * 100)
    assert storage.dir_usage_bytes(str(tmp_path)) == 100
    assert storage.dir_usage_bytes(str(tmp_path / "nope")) == 0
```

- [ ] **Step 2: Run to verify they fail** — `pytest tests/test_config_acquire.py tests/test_acquire_base.py tests/test_acquire_storage.py -v` (FAIL: no package/config).
- [ ] **Step 3: Implement** — create the `acquire/` package (`__init__.py` empty). `base.py`: `AcquisitionResult` (pydantic `BaseModel`), `BaseAcquirer(ABC)` with `@abstractmethod acquire(...)` and the two class attrs. `storage.py`: pure `pathlib`/`hashlib`/`glob` helpers (no I/O beyond stat/mkdir). Add the two `Settings` fields. In `pyproject.toml` add:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]
media = ["yt-dlp>=2024.8"]   # optional; VOD acquirers only, lazy-imported. Pin the exact version at install time — yt-dlp breaks often.
```

- [ ] **Step 4: Verify** — the three test files pass; `pytest -q` green.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(b2): acquire package scaffold — BaseAcquirer, AcquisitionResult, storage seam, config"`

---

## Task 2: Direct downloader + `campaign_provided` and `url` acquirers

**Files:**
- Create: `src/clipscore/factory/acquire/download.py`, `src/clipscore/factory/acquire/campaign_provided.py`, `src/clipscore/factory/acquire/url.py`
- Test: `tests/test_acquire_download.py`, `tests/test_acquire_campaign_provided.py`, `tests/test_acquire_url.py`

**Interfaces:**
- Consumes: `AcquisitionResult`/`BaseAcquirer` (Task 1); `storage.path_for`; `clipscore.ingest.detect.classify_response`; `clipscore.factory.whop._robots_allowed`.
- Produces `download.py`:
  - `download_direct(url: str, dest_path_noext: str, *, client: httpx.Client, ua: str, robots_cache: dict | None = None) -> AcquisitionResult` — robots-checks, streams the response, and:
    - robots disallow → `status="manual"`, `error="robots_disallow"` (nothing to evade; operator may capture).
    - status 403/429 → `status="blocked"` (`error="blocked_403"`/`"rate_limited_429"`).
    - status ≥ 400 → `status="failed"`, `error="http_<code>"`.
    - status 200, `Content-Type` **not** `text/html`: stream body to `dest_path_noext + _ext_for(url, content_type)`; `status="acquired"`, `storage_uri`, `bytes`.
    - status 200, `Content-Type` `text/html`: read the body and run `classify_response(200, body)`; `captcha`/`cf_challenge` → `status="blocked"`; anything else (folder page, login wall, empty parse) → `status="manual"`, `error="not_direct_media"`. **Never** saved as media.
  - `_ext_for(url: str, content_type: str) -> str` — map common media content-types (`video/mp4`→`.mp4`, `video/quicktime`→`.mov`, `video/webm`→`.webm`, `audio/mpeg`→`.mp3`, `application/octet-stream`→ url suffix or `.mp4`) else the URL path suffix, else `.bin`.
- Produces `campaign_provided.py`: `CampaignProvidedAcquirer(BaseAcquirer)` — `source_type="campaign_provided"`, `requires_authorization=False`. `acquire()` normalizes a share link via `_normalize_share_url(source_ref)`; `None` (folder / Google-Doc / unsupported) → `AcquisitionResult(status="manual", source_url=source_ref, error="folder_or_unsupported_share_link")`; else delegate to `download_direct` and stamp `platform="campaign_provided"`, `source_url=source_ref`.
- Produces `url.py`: `UrlAcquirer(BaseAcquirer)` — `source_type="url"`, `requires_authorization=True`. `acquire()` delegates straight to `download_direct` (the raw URL is the ref), stamping `platform="url"`, `source_url=source_ref`.

- [ ] **Step 1: Write the failing tests** (all via `httpx.MockTransport`; no real network)

```python
# tests/test_acquire_download.py
import httpx
from clipscore.factory.acquire import download

def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))

def _robots_ok(req):
    if req.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /\n")
    return None

def test_direct_media_is_downloaded(tmp_path):
    def h(req):
        return _robots_ok(req) or httpx.Response(200, content=b"VIDEO" * 100,
                                                 headers={"content-type": "video/mp4"})
    dest = str(tmp_path / "cp" / "abc")
    r = download.download_direct("https://x.test/v.mp4", dest, client=_client(h),
                                 ua="clipscore", robots_cache={})
    assert r.status == "acquired"
    assert r.storage_uri.endswith(".mp4") and r.bytes == 500

def test_403_is_blocked_not_saved(tmp_path):
    def h(req):
        return _robots_ok(req) or httpx.Response(403, text="nope")
    r = download.download_direct("https://x.test/v.mp4", str(tmp_path / "a"),
                                 client=_client(h), ua="clipscore", robots_cache={})
    assert r.status == "blocked" and r.storage_uri is None

def test_html_folder_page_is_manual(tmp_path):
    def h(req):
        return _robots_ok(req) or httpx.Response(200, text="<html>a drive folder</html>",
                                                 headers={"content-type": "text/html"})
    r = download.download_direct("https://drive.google.com/drive/folders/X", str(tmp_path / "a"),
                                 client=_client(h), ua="clipscore", robots_cache={})
    assert r.status == "manual" and r.error == "not_direct_media"

def test_html_captcha_is_blocked(tmp_path):
    def h(req):
        return _robots_ok(req) or httpx.Response(200, text="<html>please solve this recaptcha</html>",
                                                 headers={"content-type": "text/html"})
    r = download.download_direct("https://x.test/v", str(tmp_path / "a"),
                                 client=_client(h), ua="clipscore", robots_cache={})
    assert r.status == "blocked"

def test_robots_disallow_is_manual(tmp_path):
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        raise AssertionError("must not GET the file when robots disallows")
    r = download.download_direct("https://x.test/v.mp4", str(tmp_path / "a"),
                                 client=_client(h), ua="clipscore", robots_cache={})
    assert r.status == "manual" and r.error == "robots_disallow"
```

```python
# tests/test_acquire_campaign_provided.py
from clipscore.factory.acquire.campaign_provided import CampaignProvidedAcquirer, _normalize_share_url

def test_drive_file_link_normalized_to_direct_download():
    u = _normalize_share_url("https://drive.google.com/file/d/ABC123/view?usp=sharing")
    assert u == "https://drive.google.com/uc?export=download&id=ABC123"

def test_dropbox_link_forced_to_direct():
    assert _normalize_share_url("https://www.dropbox.com/s/x/v.mp4?dl=0").endswith("dl=1")

def test_drive_folder_link_is_manual():
    a = CampaignProvidedAcquirer()
    r = a.acquire("https://drive.google.com/drive/folders/XYZ", "/tmp/ignored")
    assert r.status == "manual" and r.error == "folder_or_unsupported_share_link"
    assert a.requires_authorization is False
```

```python
# tests/test_acquire_url.py
import httpx
from clipscore.factory.acquire.url import UrlAcquirer

def test_url_acquirer_downloads_and_requires_auth(tmp_path):
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, content=b"m" * 20, headers={"content-type": "video/mp4"})
    a = UrlAcquirer()
    assert a.requires_authorization is True
    r = a.acquire("https://x.test/clip.mp4", str(tmp_path / "u" / "k"),
                  client=httpx.Client(transport=httpx.MockTransport(h)), ua="clipscore",
                  robots_cache={})
    assert r.status == "acquired" and r.platform == "url"
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** the three modules. `download.py` uses `with client.stream("GET", url, headers={"User-Agent": ua}) as resp:` — read `resp.status_code`/`resp.headers["content-type"]` first; for HTML call `resp.read()` then `classify_response`; for media `storage.ensure_parent(path)` then `for chunk in resp.iter_bytes(): f.write(chunk)`, tracking bytes. Reuse `_robots_allowed(client, ua, url, robots_cache)` from `whop.py` for the robots gate (DRY — do not re-implement it). `_normalize_share_url` handles Drive `file/d/<id>`, Dropbox `dl=`, plain media URLs (pass-through), and returns `None` for `drive.google.com/drive/folders`, `docs.google.com`, and anything else.
- [ ] **Step 4: Verify** — the three test files pass; `pytest -q` green.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(b2): direct downloader + campaign_provided/url acquirers (drop-don't-evade)"`

---

## Task 3: VOD acquirers (`youtube`/`twitch`/`kick`) — lazy `yt-dlp` behind an injectable seam

**Files:**
- Create: `src/clipscore/factory/acquire/vod.py`
- Test: `tests/test_acquire_vod.py`

**Interfaces:**
- Consumes: `AcquisitionResult`/`BaseAcquirer` (Task 1).
- Produces `vod.py`:
  - Exceptions `VodBlocked`, `VodUnavailable`, `YtDlpUnavailable` (all subclass `Exception`).
  - `YtDlpAcquirer(BaseAcquirer)` — `requires_authorization=True`; constructed as `YtDlpAcquirer(source_type: str, downloader=None)` where `downloader` is a callable `(source_ref, dest_path_noext) -> dict` with keys `path, bytes, duration_s, creator` (the DI seam; `None` → the real `_ytdlp_download`). `acquire()` calls the downloader and maps: success → `status="acquired"` (+ fields, `platform=source_type`, `source_url=source_ref`); `VodBlocked` → `status="blocked"`; `VodUnavailable` → `status="failed"`, `error="vod_unavailable"`; `YtDlpUnavailable` → `status="failed"`, `error="yt_dlp_unavailable"`; any other `Exception` → `status="failed"`, `error="download_error"`.
  - `_ytdlp_download(source_ref, dest_path_noext) -> dict` — **lazily** `import yt_dlp` inside the function; on `ImportError` raise `YtDlpUnavailable`; run a download to `dest_path_noext + ".%(ext)s"`; translate `yt_dlp.utils.DownloadError` whose message matches private/removed/unavailable/geo → `VodUnavailable`, and rate-limit/403/challenge → `VodBlocked`. **Manual-acceptance-only; never hit in CI.**

- [ ] **Step 1: Write the failing tests** (inject a fake downloader — no real yt-dlp)

```python
# tests/test_acquire_vod.py
import pytest
from clipscore.factory.acquire.vod import (
    YtDlpAcquirer, VodBlocked, VodUnavailable, YtDlpUnavailable,
)

def test_import_does_not_require_ytdlp():
    import importlib
    importlib.import_module("clipscore.factory.acquire.vod")  # must not raise with yt-dlp absent

def test_success_maps_to_acquired():
    def fake(ref, dest): return {"path": dest + ".mp4", "bytes": 1234, "duration_s": 90, "creator": "diego"}
    a = YtDlpAcquirer("youtube", downloader=fake)
    r = a.acquire("https://youtube.com/watch?v=x", "/m/youtube/abc", authorizing_campaign_id="c1")
    assert r.status == "acquired" and r.platform == "youtube"
    assert r.storage_uri == "/m/youtube/abc.mp4" and r.duration_s == 90 and r.creator == "diego"
    assert a.requires_authorization is True

def test_blocked_maps_to_blocked():
    def fake(ref, dest): raise VodBlocked("429")
    r = YtDlpAcquirer("twitch", downloader=fake).acquire("u", "/m/twitch/abc")
    assert r.status == "blocked" and r.storage_uri is None

def test_unavailable_maps_to_failed():
    def fake(ref, dest): raise VodUnavailable("private video")
    r = YtDlpAcquirer("kick", downloader=fake).acquire("u", "/m/kick/abc")
    assert r.status == "failed" and r.error == "vod_unavailable"

def test_missing_ytdlp_maps_to_failed_unavailable():
    def fake(ref, dest): raise YtDlpUnavailable()
    r = YtDlpAcquirer("youtube", downloader=fake).acquire("u", "/m/youtube/abc")
    assert r.status == "failed" and r.error == "yt_dlp_unavailable"
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** `vod.py`. Keep the real `_ytdlp_download` isolated so the DI seam carries all tested logic; the lazy `import yt_dlp` lives only inside `_ytdlp_download`. No module-level `yt_dlp` import anywhere.
- [ ] **Step 4: Verify** — tests pass; `pytest -q` green; confirm `python -c "import clipscore.factory.acquire.vod"` succeeds with `yt-dlp` **not** installed.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(b2): VOD acquirers via lazy optional yt-dlp behind an injectable seam"`

---

## Task 4: Registry + `acquire_job` orchestrator (auth gate, dedup, never-raise) + retention sweep

**Files:**
- Create: `src/clipscore/factory/acquire/registry.py`, `src/clipscore/factory/acquire/run.py`
- Test: `tests/test_acquire_run.py`, `tests/test_acquire_retention.py`

**Interfaces:**
- Consumes: everything above; `ClipJob`/`SourceAsset`/`Campaign` models; `storage`; `clipscore.time.utcnow_iso`.
- Produces `registry.py`:
  - `build_registry(*, ytdlp_downloader=None) -> dict[str, BaseAcquirer]` → `{"campaign_provided": CampaignProvidedAcquirer(), "url": UrlAcquirer(), "youtube": YtDlpAcquirer("youtube", ytdlp_downloader), "twitch": YtDlpAcquirer("twitch", ytdlp_downloader), "kick": YtDlpAcquirer("kick", ytdlp_downloader)}`.
  - `select_acquirer(source_type: str, registry: dict) -> BaseAcquirer | None`.
- Produces `run.py`:
  - `acquire_job(session, clip_job: ClipJob, settings, *, registry=None, client=None, now=None) -> ClipJob` — the guarded orchestrator (see steps). Never raises.
  - `sweep_retention(session, settings, *, now=None) -> dict` — deletes files for `SourceAsset` rows whose `downloaded_at < cutoff` (`cutoff` = now − `raw_retention_days`, formatted with the `utcnow_iso` pattern), nulls their `storage_uri`, returns `{"deleted": n, "bytes_freed": b}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_acquire_run.py
import uuid
import httpx
from clipscore.db.models import ClipJob, SourceAsset, Campaign
from clipscore.factory.acquire import run, registry
from clipscore.factory.acquire.base import AcquisitionResult, BaseAcquirer
from clipscore.config import Settings
from clipscore.time import utcnow_iso
from sqlalchemy import select

def _settings(tmp_path):
    return Settings(_env_file=None, media_dir=str(tmp_path), max_media_gb=50.0)

def _job(session, **kw):
    now = utcnow_iso()
    defaults = dict(campaign_id="c1", source_type="campaign_provided",
                    source_ref="https://drive.google.com/uc?export=download&id=A",
                    status="queued", created_at=now)
    defaults.update(kw)
    j = ClipJob(**defaults); session.add(j); session.commit()
    return j

class _FakeAcquirer(BaseAcquirer):
    source_type = "campaign_provided"
    requires_authorization = False
    def __init__(self, result): self._result = result
    def acquire(self, source_ref, dest_path, **kw):
        # simulate a real acquirer writing the file
        if self._result.status == "acquired":
            import os
            os.makedirs(os.path.dirname(dest_path + ".mp4"), exist_ok=True)
            open(dest_path + ".mp4", "wb").write(b"x" * 42)
            self._result.storage_uri = dest_path + ".mp4"; self._result.bytes = 42
        return self._result

def _reg(acq): return {acq.source_type: acq}

def test_acquired_writes_source_asset_and_sets_status(session, tmp_path):
    j = _job(session)
    reg = _reg(_FakeAcquirer(AcquisitionResult(status="acquired", platform="campaign_provided")))
    run.acquire_job(session, j, _settings(tmp_path), registry=reg)
    assert j.status == "acquired"
    sa = session.execute(select(SourceAsset)).scalars().one()
    assert sa.clip_job_id == j.id and sa.bytes == 42 and sa.storage_uri.endswith(".mp4")

def test_blocked_maps_to_failed_no_source_asset(session, tmp_path):
    j = _job(session)
    reg = _reg(_FakeAcquirer(AcquisitionResult(status="blocked", error="blocked_403")))
    run.acquire_job(session, j, _settings(tmp_path), registry=reg)
    assert j.status == "failed" and j.error == "blocked_403"
    assert session.execute(select(SourceAsset)).scalars().first() is None

def test_manual_maps_to_failed_with_reason(session, tmp_path):
    j = _job(session)
    reg = _reg(_FakeAcquirer(AcquisitionResult(status="manual", error="folder_or_unsupported_share_link")))
    run.acquire_job(session, j, _settings(tmp_path), registry=reg)
    assert j.status == "failed" and j.error == "folder_or_unsupported_share_link"

def test_vod_without_active_campaign_is_unauthorized(session, tmp_path):
    # requires_authorization acquirer + campaign_id that doesn't resolve to an active campaign
    j = _job(session, source_type="youtube", source_ref="https://youtube.com/watch?v=x",
             campaign_id="missing")
    class _VodAcq(BaseAcquirer):
        source_type = "youtube"; requires_authorization = True
        def acquire(self, *a, **k): raise AssertionError("must not download when unauthorized")
    run.acquire_job(session, j, _settings(tmp_path), registry={"youtube": _VodAcq()})
    assert j.status == "failed" and j.error == "unauthorized"

def test_vod_with_active_campaign_records_authorizing_id(session, tmp_path):
    session.add(Campaign(id="c1", source="cr", external_id="e1", status="active",
                         first_seen_at=utcnow_iso(), last_seen_at=utcnow_iso())); session.commit()
    j = _job(session, source_type="youtube", source_ref="https://youtube.com/watch?v=x")
    reg = _reg(_FakeAcquirer(AcquisitionResult(status="acquired", platform="youtube")))
    reg["youtube"] = reg.pop("campaign_provided"); reg["youtube"].source_type = "youtube"
    reg["youtube"].requires_authorization = True
    run.acquire_job(session, j, _settings(tmp_path), registry=reg)
    sa = session.execute(select(SourceAsset)).scalars().one()
    assert sa.authorizing_campaign_id == "c1"

def test_dedup_reuses_existing_file_without_calling_acquirer(session, tmp_path):
    from clipscore.factory.acquire import storage
    j = _job(session)
    stem = storage.stem_key("campaign_provided", j.source_ref)
    existing = tmp_path / f"{stem}.mp4"; existing.parent.mkdir(parents=True); existing.write_bytes(b"y" * 7)
    class _Boom(BaseAcquirer):
        source_type = "campaign_provided"; requires_authorization = False
        def acquire(self, *a, **k): raise AssertionError("dedup must skip the download")
    run.acquire_job(session, j, _settings(tmp_path), registry={"campaign_provided": _Boom()})
    assert j.status == "acquired"
    assert session.execute(select(SourceAsset)).scalars().one().storage_uri == str(existing)

def test_unknown_source_type_fails(session, tmp_path):
    j = _job(session, source_type="myspace")
    run.acquire_job(session, j, _settings(tmp_path), registry={})
    assert j.status == "failed" and j.error == "unknown_source_type"

def test_acquirer_crash_never_raises_and_marks_failed(session, tmp_path):
    j = _job(session)
    class _Crash(BaseAcquirer):
        source_type = "campaign_provided"; requires_authorization = False
        def acquire(self, *a, **k): raise RuntimeError("boom")
    j2 = run.acquire_job(session, j, _settings(tmp_path), registry={"campaign_provided": _Crash()})
    assert j2.status == "failed" and j2.error  # did not raise; error recorded

def test_disk_guard_refuses_when_over_budget(session, tmp_path):
    (tmp_path / "big").mkdir(); (tmp_path / "big" / "f").write_bytes(b"x" * 2000)
    s = Settings(_env_file=None, media_dir=str(tmp_path), max_media_gb=0.000001)  # ~1KB budget
    j = _job(session)
    class _Boom(BaseAcquirer):
        source_type = "campaign_provided"; requires_authorization = False
        def acquire(self, *a, **k): raise AssertionError("must not download over budget")
    run.acquire_job(session, j, s, registry={"campaign_provided": _Boom()})
    assert j.status == "failed" and j.error == "disk_guard"
```

```python
# tests/test_acquire_retention.py
import os
from datetime import datetime, timedelta, timezone
from clipscore.db.models import ClipJob, SourceAsset
from clipscore.factory.acquire import run
from clipscore.config import Settings
from clipscore.time import utcnow_iso

def _iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def test_retention_deletes_old_source_files(session, tmp_path):
    old_f = tmp_path / "old.mp4"; old_f.write_bytes(b"x" * 10)
    new_f = tmp_path / "new.mp4"; new_f.write_bytes(b"y" * 10)
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    old = _iso(now - timedelta(days=30)); recent = _iso(now - timedelta(days=1))
    session.add_all([
        SourceAsset(clip_job_id=1, storage_uri=str(old_f), bytes=10, downloaded_at=old),
        SourceAsset(clip_job_id=2, storage_uri=str(new_f), bytes=10, downloaded_at=recent),
    ]); session.commit()
    s = Settings(_env_file=None, media_dir=str(tmp_path), raw_retention_days=14)
    res = run.sweep_retention(session, s, now=_iso(now))
    assert res["deleted"] == 1
    assert not old_f.exists() and new_f.exists()  # only the aged file removed
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** `registry.py` and `run.py`.

  `acquire_job` body (guarded — wrap ALL of the following in `try/except Exception` → set `status="failed"`, `error="acquire_crashed"`, `session.commit()`, return the job):
  1. `reg = registry if registry is not None else build_registry()`; `acq = select_acquirer(clip_job.source_type, reg)`; `None` → `failed`/`unknown_source_type` (commit, return).
  2. `now = now or utcnow_iso()`.
  3. **Auth gate:** if `acq.requires_authorization`: `camp = session.get(Campaign, clip_job.campaign_id) if clip_job.campaign_id else None`; if `camp is None or camp.status != "active"` → `failed`/`unauthorized` (commit, return); else `authorizing_campaign_id = clip_job.campaign_id`. Else `authorizing_campaign_id = None`.
  4. **Dedup:** `existing = storage.find_existing(settings.media_dir, clip_job.source_type, clip_job.source_ref)`; if set, write a `SourceAsset` (`storage_uri=existing`, `bytes=os.path.getsize(existing)`, `authorizing_campaign_id`, `downloaded_at=now`, `source_url=clip_job.source_ref`), `clip_job.status="acquired"`, commit, return (do **not** call the acquirer).
  5. **Disk guard:** if `storage.dir_usage_bytes(settings.media_dir) > settings.max_media_gb * 1_000_000_000` → `failed`/`disk_guard` (commit, return).
  6. `dest = storage.path_for(settings.media_dir, storage.stem_key(clip_job.source_type, clip_job.source_ref), "")` (extensionless stem — acquirers append their own ext). Build/close an `httpx.Client(timeout=settings.http_timeout_s, follow_redirects=True)` if `client is None` (own it in a `finally`), pass `ua=settings.user_agent`, a fresh `robots_cache={}`.
  7. `result = acq.acquire(clip_job.source_ref, dest, authorizing_campaign_id=authorizing_campaign_id, client=client, ua=settings.user_agent, robots_cache=robots_cache)`.
  8. If `result.status == "acquired"`: write `SourceAsset(clip_job_id=clip_job.id, creator=result.creator, platform=result.platform, source_url=result.source_url or clip_job.source_ref, authorizing_campaign_id=authorizing_campaign_id, storage_uri=result.storage_uri, bytes=result.bytes, duration_s=result.duration_s, downloaded_at=now)`; `clip_job.status="acquired"`, `clip_job.error=None`. Else `clip_job.status="failed"`, `clip_job.error=result.error or result.status`. Commit; return.

  `sweep_retention`: `cutoff = (parse(now) - timedelta(days=settings.raw_retention_days))` formatted with `"%Y-%m-%dT%H:%M:%SZ"` (parse `now` with `datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)`; `now` defaults to `utcnow_iso()`). Select `SourceAsset` where `downloaded_at is not None AND downloaded_at < cutoff AND storage_uri is not None`; for each: if the file exists `os.remove` it and add its `bytes` to `bytes_freed`; set `storage_uri=None`; count. Commit; return the dict.

- [ ] **Step 4: Verify** — both test files pass; `pytest -q` green. Confirm the never-raise guard (crash test) and the dedup/disk-guard/auth tests all pass.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(b2): acquire_job orchestrator (auth gate, dedup, disk guard, never-raise) + retention sweep + registry"`

---

## Definition of done

- `factory/acquire/` provides `BaseAcquirer` + a `source_type→acquirer` registry; `campaign_provided`, `url`, `youtube`, `twitch`, `kick` acquirers exist.
- A source video is fetched to local storage from a direct-download acquirer and (via injected fake) a VOD acquirer; a **blocked** download is logged and skipped; an **auth-walled/folder** link is marked **manual**; a duplicate `source_ref` is **deduped** (one download).
- The **ToS/authorization gate** refuses a VOD/url job with no active authorizing campaign and records `authorizing_campaign_id` when it succeeds.
- `acquire_job` **cannot crash the scheduler** — proven by a test where the acquirer raises and the job ends `failed` with an error, no exception propagating.
- `sweep_retention` removes aged source files and nulls their `storage_uri`; the disk guard refuses downloads over `max_media_gb`.
- `yt-dlp` is an **optional** extra, lazy-imported; the package imports and `pytest -q` passes with it uninstalled.
- `pytest -q` green; **no real network or yt-dlp call in CI**.

## Out of scope (later phases)

Wiring acquisition into the scheduler / triggering it on campaign approval, clip production + matching + captions (B3), immediate-post-clip source deletion (B3), the review dashboard (B4), and the Vizard clip-engine adapter + price quote (B0) — see `PIPELINE_B_CLIP_FACTORY.md`.
