"""Clipping job — Pipeline B Stage B3 Task 3.

For an `acquired` `ClipJob`, this loads its `SourceAsset`, derives the
platform specs from the job's `Campaign`, hands the source off to a clip
engine (Fake in tests/CI, Vizard in production), persists the produced
clips, and deletes the local source file as an immediate post-clip
retention step.

`run_clipping` mirrors `factory/enrich.py`'s `enrich_campaign` guard shape:
an inner worker does the real work, and an outer `try/except Exception`
ensures a clip-engine failure (network error, bad response, anything)
never propagates out of this job -- it is recorded on the `ClipJob` as a
`failed` status + `error` message instead. A clipping failure must never
crash the scheduler.
"""
import os

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from clipscore.config import Settings
from clipscore.db.models import Campaign, Clip, ClipJob, SourceAsset
from clipscore.factory.clip.base import BaseClipEngine, build_engine, derive_specs
from clipscore.time import utcnow_iso

log = structlog.get_logger()


def _run_clipping_inner(
    session: Session, clip_job: ClipJob, settings: Settings, engine: BaseClipEngine, now: str
) -> None:
    source_asset = session.execute(
        select(SourceAsset).where(
            SourceAsset.clip_job_id == clip_job.id,
            SourceAsset.storage_uri.is_not(None),
        )
    ).scalars().one()

    campaign = session.execute(
        select(Campaign).where(Campaign.id == clip_job.campaign_id)
    ).scalars().one()

    specs = derive_specs(campaign, settings)
    dest_dir = f"{settings.media_dir}/clips/{clip_job.id}"
    os.makedirs(dest_dir, exist_ok=True)

    produced = engine.produce(source_asset.storage_uri, specs, dest_dir=dest_dir)

    for p in produced:
        session.add(
            Clip(
                source_asset_id=source_asset.id,
                platform_variant=p.platform_variant,
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

    # Retention: delete the source file only after the clip rows are
    # durably written, and only on the success path. Best-effort -- a
    # failure to remove the file must not fail the job.
    try:
        os.remove(source_asset.storage_uri)
    except OSError:
        log.warning("clip_source_delete_failed", clip_job_id=clip_job.id,
                    storage_uri=source_asset.storage_uri)

    source_asset.storage_uri = None
    clip_job.status = "produced"
    clip_job.error = None
    session.commit()


def run_clipping(
    session: Session, clip_job: ClipJob, settings: Settings, *, engine=None, now: str | None = None
) -> ClipJob:
    """Produce clips for an `acquired` clip_job, write `Clip` rows, and
    delete the source asset file. Never raises -- any failure marks the
    job `failed` with an `error` message and commits, so a clip-engine
    outage can never crash the scheduler."""
    resolved_engine = engine or build_engine(settings)
    resolved_now = now or utcnow_iso()

    try:
        _run_clipping_inner(session, clip_job, settings, resolved_engine, resolved_now)
    except Exception as exc:
        log.error("clip_job_failed", clip_job_id=clip_job.id, error=str(exc))
        clip_job.status = "failed"
        clip_job.error = str(exc)
        session.commit()

    return clip_job
