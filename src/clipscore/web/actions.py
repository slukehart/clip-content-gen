"""Thin, guarded write layer for the B4 dashboard. Reuses create_clip_job for
job creation (both 'Clip this' and manual entry) and performs the idempotent
mark-posted upsert. Returns ClipResult view models; route handlers translate
these into HTMX partials / redirects."""
import re

from pydantic import BaseModel
from sqlalchemy.orm import Session

from clipscore.config import Settings
from clipscore.db.models import Campaign, ClipMatch, Outcome
from clipscore.jobs.clipfactory import create_clip_job
from clipscore.time import utcnow_iso


class ClipResult(BaseModel):
    ok: bool
    job_id: int | None = None
    status: str | None = None
    error: str | None = None


def clip_this(session: Session, campaign_id: str, settings: Settings) -> ClipResult:
    try:
        job = create_clip_job(session, campaign_id, settings)
    except ValueError as e:
        return ClipResult(ok=False, error=str(e))
    return ClipResult(ok=True, job_id=job.id, status=job.status)


def mark_posted(session: Session, match_id: int, *, now: str | None = None) -> ClipResult:
    match = session.get(ClipMatch, match_id)
    if match is None:
        return ClipResult(ok=False, error="unknown match")
    existing = session.query(Outcome).filter_by(
        clip_id=match.clip_id, campaign_id=match.campaign_id
    ).first()
    if existing is not None:
        existing.clips_posted = 1
    else:
        session.add(Outcome(
            campaign_id=match.campaign_id, clip_id=match.clip_id, clips_posted=1,
            logged_at=now or utcnow_iso(),
        ))
    session.commit()
    return ClipResult(ok=True, status="posted")


def _manual_id(title: str, now: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "campaign").lower()).strip("-") or "campaign"
    return f"manual-{slug}-{re.sub(r'[^0-9]', '', now)}"


def create_manual_campaign(session: Session, *, title: str, niche: str | None,
                           content_bank_url: str | None, target_creator: str | None,
                           settings: Settings, est_minutes: int | None = None,
                           now: str | None = None) -> ClipResult:
    now = now or utcnow_iso()
    cid = _manual_id(title, now)
    session.add(Campaign(
        id=cid, source="manual", external_id=cid, campaign_type="clipping",
        niche=niche, title=title, status="active", access_status="ingestable",
        ingest_method="manual", first_seen_at=now, last_seen_at=now,
        content_bank_url=content_bank_url or None, target_creator=target_creator or None,
    ))
    session.commit()
    try:
        job = create_clip_job(session, cid, settings, est_minutes=est_minutes)
    except ValueError:
        return ClipResult(ok=True, job_id=None, error="campaign created; no acquirable source")
    return ClipResult(ok=True, job_id=job.id, status=job.status)
