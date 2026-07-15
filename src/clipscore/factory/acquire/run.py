"""Guarded orchestrator (`acquire_job`) tying the registry (Task 4's
`registry.py`), storage helpers, and individual acquirers (Tasks 1-3)
together, plus the retention sweep (`sweep_retention`).

`acquire_job` is the one rule that matters here: acquisition can NEVER crash
the scheduler. It always returns the (possibly updated) `ClipJob` and never
raises -- any unexpected failure is caught and mapped to
`status="failed"`/`error="acquire_crashed"`. Mirrors the never-raise pattern
in `factory/enrich.py::enrich_campaign`.
"""
import os
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from clipscore.config import Settings
from clipscore.db.models import Campaign, ClipJob, SourceAsset
from clipscore.factory.acquire import storage
from clipscore.factory.acquire.registry import build_registry, select_acquirer
from clipscore.time import utcnow_iso

log = structlog.get_logger()


def _fail(session: Session, clip_job: ClipJob, error: str) -> ClipJob:
    clip_job.status = "failed"
    clip_job.error = error
    session.commit()
    return clip_job


def _acquire_job_inner(session: Session, clip_job: ClipJob, settings: Settings,
                       registry: dict, client, now: str) -> ClipJob:
    acq = select_acquirer(clip_job.source_type, registry)
    if acq is None:
        return _fail(session, clip_job, "unknown_source_type")

    # Auth gate.
    authorizing_campaign_id = None
    if acq.requires_authorization:
        camp = session.get(Campaign, clip_job.campaign_id) if clip_job.campaign_id else None
        if camp is None or camp.status != "active":
            return _fail(session, clip_job, "unauthorized")
        authorizing_campaign_id = clip_job.campaign_id

    # Dedup -- reuse an already-downloaded file without calling the acquirer,
    # but only if a prior SourceAsset actually vouches for that file. A file
    # on disk with no matching SourceAsset row is an orphan (e.g. a completed
    # download whose SourceAsset write failed) and must not be trusted --
    # fall through to a normal (re)acquire instead of fabricating metadata.
    existing = storage.find_existing(settings.media_dir, clip_job.source_type, clip_job.source_ref)
    if existing:
        prior = session.execute(
            select(SourceAsset).where(SourceAsset.storage_uri == existing)
        ).scalars().first()
        if prior is not None:
            session.add(SourceAsset(
                clip_job_id=clip_job.id,
                creator=prior.creator,
                platform=prior.platform,
                duration_s=prior.duration_s,
                source_url=clip_job.source_ref,
                authorizing_campaign_id=authorizing_campaign_id,
                storage_uri=existing,
                bytes=os.path.getsize(existing),
                downloaded_at=now,
            ))
            clip_job.status = "acquired"
            clip_job.error = None
            session.commit()
            return clip_job

    # Disk guard -- refuse to download if we're already over budget.
    if storage.dir_usage_bytes(settings.media_dir) > settings.max_media_gb * 1_000_000_000:
        return _fail(session, clip_job, "disk_guard")

    dest = storage.path_for(
        settings.media_dir, storage.stem_key(clip_job.source_type, clip_job.source_ref), ""
    )
    storage.ensure_parent(dest)

    owns_client = client is None
    http_client = client or httpx.Client(timeout=settings.http_timeout_s, follow_redirects=True)
    robots_cache: dict = {}
    try:
        result = acq.acquire(
            clip_job.source_ref,
            dest,
            authorizing_campaign_id=authorizing_campaign_id,
            client=http_client,
            ua=settings.user_agent,
            robots_cache=robots_cache,
        )
    finally:
        if owns_client:
            http_client.close()

    if result.status == "acquired":
        session.add(SourceAsset(
            clip_job_id=clip_job.id,
            creator=result.creator,
            platform=result.platform,
            source_url=result.source_url or clip_job.source_ref,
            authorizing_campaign_id=authorizing_campaign_id,
            storage_uri=result.storage_uri,
            bytes=result.bytes,
            duration_s=result.duration_s,
            downloaded_at=now,
        ))
        clip_job.status = "acquired"
        clip_job.error = None
    else:
        clip_job.status = "failed"
        clip_job.error = result.error or result.status
    session.commit()
    return clip_job


def acquire_job(session: Session, clip_job: ClipJob, settings: Settings, *,
                registry: dict | None = None, client=None, now: str | None = None) -> ClipJob:
    """Select an acquirer, enforce the authorization gate, dedup, apply the
    disk guard, download, and write the resulting `SourceAsset`/status.
    Never raises."""
    try:
        reg = registry if registry is not None else build_registry()
        now = now or utcnow_iso()
        return _acquire_job_inner(session, clip_job, settings, reg, client, now)
    except Exception:
        log.error("acquire_job_crashed", clip_job_id=getattr(clip_job, "id", None))
        try:
            try:
                session.rollback()
            except Exception:
                pass
            return _fail(session, clip_job, "acquire_crashed")
        except Exception:
            log.error("acquire_job_fail_write_also_failed", clip_job_id=getattr(clip_job, "id", None))
            clip_job.status = "failed"
            clip_job.error = "acquire_crashed"
            return clip_job


def sweep_retention(session: Session, settings: Settings, *, now: str | None = None) -> dict:
    """Delete aged local source files (older than `settings.raw_retention_days`),
    null their `SourceAsset.storage_uri`, and return `{"deleted", "bytes_freed"}`."""
    now = now or utcnow_iso()
    now_dt = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    cutoff = (now_dt - timedelta(days=settings.raw_retention_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    assets = session.execute(
        select(SourceAsset).where(
            SourceAsset.downloaded_at.is_not(None),
            SourceAsset.downloaded_at < cutoff,
            SourceAsset.storage_uri.is_not(None),
        )
    ).scalars().all()

    deleted = 0
    bytes_freed = 0
    for asset in assets:
        if asset.storage_uri and os.path.exists(asset.storage_uri):
            os.remove(asset.storage_uri)
            bytes_freed += asset.bytes or 0
        asset.storage_uri = None
        deleted += 1

    session.commit()
    return {"deleted": deleted, "bytes_freed": bytes_freed}
