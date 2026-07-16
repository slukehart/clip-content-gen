"""Clip-factory job runner -- Pipeline B Stage B3 Task 6.

`create_clip_job` queues a new `ClipJob` for a campaign, resolving a
source (campaign-provided content bank link, else first `target_creator`)
when the caller doesn't supply one explicitly.

`process_clip_jobs` is the status-driven runner: it selects every clip_job
still in flight (`queued`/`acquired`/`produced`) and advances each one
stage by exactly one step via `_advance`. It is idempotent -- a job already
`matched` or `failed` is never re-picked -- and it never raises: each job's
`_advance` call is wrapped in its own `try/except` that on failure marks
that single job `failed` + `error` and commits, so one bad job can never
take down the scheduler tick or block the rest of the batch. Note the
individual stage functions (`acquire_job`, `run_clipping`, `run_matching`,
`run_caption`) are already guarded this same way -- `_advance`'s wrapper is
defense-in-depth for anything that slips past those (e.g. a bug in the
dispatch logic itself).
"""
import json

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from clipscore.config import Settings
from clipscore.db.models import Campaign, ClipJob
from clipscore.factory.acquire.run import acquire_job
from clipscore.factory.clip.caption import run_caption
from clipscore.factory.clip.match import run_matching
from clipscore.factory.clip.produce import run_clipping
from clipscore.factory.clip.videotype import detect_video_type
from clipscore.time import utcnow_iso

log = structlog.get_logger()

# `blocked` (B5 monthly-credit cap) is intentionally excluded here: a
# capped-out job stays parked until an operator re-queues it manually.
_ADVANCEABLE_STATUSES = ("queued", "acquired", "produced")


def _as_list(raw) -> list:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        return val if isinstance(val, list) else []
    return []


def create_clip_job(
    session: Session, campaign_id: str, settings: Settings, *,
    source_type: str | None = None, source_ref: str | None = None,
    est_minutes: int | None = None, now: str | None = None,
) -> ClipJob:
    """Resolve `campaign_id` (raises `ValueError` if unknown), pick a
    source (explicit args, else `content_bank_url`, else the first
    `target_creator` entry, else raise), and write a `queued` `ClipJob`."""
    campaign = session.get(Campaign, campaign_id)
    if campaign is None:
        raise ValueError(f"unknown campaign: {campaign_id}")

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

    job = ClipJob(
        campaign_id=campaign_id,
        source_type=source_type,
        source_ref=source_ref,
        status="queued",
        est_cost_usd=settings.clip_est_cost_usd,
        est_minutes=est_minutes,
        created_at=now or utcnow_iso(),
    )
    session.add(job)
    session.commit()
    return job


def _advance(session: Session, job: ClipJob, settings: Settings, *,
             registry, engine, llm, now: str) -> ClipJob:
    if job.status == "queued":
        return acquire_job(session, job, settings, registry=registry, now=now)
    if job.status == "acquired":
        return run_clipping(session, job, settings, engine=engine, now=now)
    if job.status == "produced":
        job = run_matching(session, job, now=now)
        if job.status == "matched":
            job = run_caption(session, job, settings, llm=llm)
        return job
    return job


def process_clip_jobs(
    session: Session, settings: Settings, *,
    registry: dict | None = None, engine=None, llm=None, now: str | None = None,
) -> dict:
    """Select every clip_job still in flight and advance each one stage.
    Never raises -- a per-job failure marks that job `failed` + `error`
    and commits; the rest of the batch proceeds. Returns
    `{"advanced": n, "failed": m}`."""
    resolved_now = now or utcnow_iso()
    jobs = session.execute(
        select(ClipJob).where(ClipJob.status.in_(_ADVANCEABLE_STATUSES))
        .limit(settings.clip_jobs_per_tick)
    ).scalars().all()

    advanced = 0
    failed = 0
    for job in jobs:
        try:
            _advance(session, job, settings, registry=registry, engine=engine, llm=llm, now=resolved_now)
            advanced += 1
        except Exception as exc:
            reason = str(exc)
            try:
                session.rollback()
                job.status = "failed"
                job.error = reason
                session.commit()
                log.error("clip_job_advance_failed", clip_job_id=getattr(job, "id", None), error=reason)
            except Exception:
                log.error("clip_job_advance_failure_record_failed", error=reason)
            failed += 1

    return {"advanced": advanced, "failed": failed}
