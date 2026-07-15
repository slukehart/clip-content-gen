"""Clip -> campaign matching -- Pipeline B Stage B3 Task 4.

For a produced `Clip`, find candidate live campaigns (creator + length
window), score each candidate by CVS niche-percentile x spec-fit, and write
ranked `ClipMatch` rows. Platform is a campaign property (`target_platforms`),
not a clip property, so it is not part of the match gate.

`match_clip` is pure computation (no writes) so it is trivially unit-tested
and reusable. `run_matching` mirrors `factory/clip/produce.py`'s
`run_clipping` guard shape: an inner worker does the real work, and an
outer `try/except Exception` ensures a matching failure never propagates
out of this job -- it is recorded on the `ClipJob` as a `failed` status +
`error` message instead.
"""
import json

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from clipscore.db.models import Campaign, CampaignScore, Clip, ClipJob, ClipMatch, SourceAsset
from clipscore.scoring.board import eligible_latest_scores
from clipscore.time import utcnow_iso

log = structlog.get_logger()


def _as_list(raw) -> list:
    """Parse a JSON-array column defensively: normally a list, but may
    arrive as a JSON-encoded string (hand-built test fixtures, older
    rows) -- normalize either shape to a plain list, else []."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        return val if isinstance(val, list) else []
    return []


def _normalize_creator(value) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lstrip("@").strip().lower()


def _creator_matches(campaign: Campaign, creator: str) -> bool:
    target_creator = _normalize_creator(creator)
    if not target_creator:
        return False
    for entry in _as_list(campaign.target_creator):
        if _normalize_creator(entry) == target_creator:
            return True
    return False


def _length_ok(campaign: Campaign, duration_s) -> bool:
    lo = campaign.clip_min_len_s
    hi = campaign.clip_max_len_s
    if lo is None and hi is None:
        return True
    if duration_s is None:
        return False
    if lo is not None and duration_s < lo:
        return False
    if hi is not None and duration_s > hi:
        return False
    return True


def _eligible(campaign) -> bool:
    return (campaign.status == "active"
            and campaign.access_status == "ingestable"
            and campaign.campaign_type != "ugc")


def _latest_score(session, campaign_id):
    return session.execute(
        select(CampaignScore)
        .where(CampaignScore.campaign_id == campaign_id)
        .order_by(CampaignScore.id.desc())
    ).scalars().first()


def _spec_fit(campaign) -> float:
    has_window = campaign.clip_min_len_s is not None or campaign.clip_max_len_s is not None
    return 1.0 if has_window else 0.9


def match_clip(session: Session, clip: Clip) -> list[dict]:
    """Candidate live campaigns for `clip`, ranked by match_score desc.

    The clip's ORIGINATING campaign (the one its clip_job was created under)
    always matches -- the operator explicitly produced this clip for it, so it
    matches regardless of creator and regardless of whether a CVS score exists
    yet (covers the manual/passthrough flow), subject only to the length
    window + basic eligibility. Discovery then adds OTHER eligible, scored
    campaigns whose target_creator overlaps the source creator and whose length
    window fits. Platform is a campaign property, not a clip property, so it is
    not a matching criterion.
    """
    source_asset = session.execute(
        select(SourceAsset).where(SourceAsset.id == clip.source_asset_id)
    ).scalars().one()

    candidates = []
    seen = set()

    # (1) Originating campaign -- always a match (creator/score-independent).
    clip_job = session.get(ClipJob, source_asset.clip_job_id) if source_asset.clip_job_id else None
    if clip_job is not None and clip_job.campaign_id:
        origin = session.get(Campaign, clip_job.campaign_id)
        if origin is not None and _eligible(origin) and _length_ok(origin, clip.duration_s):
            score = _latest_score(session, origin.id)
            cvs_pct = (score.cvs_niche_percentile or 0.0) if score is not None else 0.0
            candidates.append({"campaign_id": origin.id, "match_score": cvs_pct * _spec_fit(origin)})
            seen.add(origin.id)

    # (2) Discovery -- other eligible, scored campaigns on creator + length.
    for campaign, score in eligible_latest_scores(session):
        if campaign.id in seen:
            continue
        if not _creator_matches(campaign, source_asset.creator):
            continue
        if not _length_ok(campaign, clip.duration_s):
            continue
        cvs_pct = score.cvs_niche_percentile or 0.0
        candidates.append({"campaign_id": campaign.id, "match_score": cvs_pct * _spec_fit(campaign)})

    candidates.sort(key=lambda c: c["match_score"], reverse=True)
    for i, c in enumerate(candidates, start=1):
        c["rank"] = i
        c["meets_requirements"] = 1
    return candidates


def _run_matching_inner(session: Session, clip_job: ClipJob, now: str) -> None:
    source_assets = session.execute(
        select(SourceAsset).where(SourceAsset.clip_job_id == clip_job.id)
    ).scalars().all()
    source_asset_ids = [sa.id for sa in source_assets]

    clips = []
    if source_asset_ids:
        clips = session.execute(
            select(Clip).where(
                Clip.source_asset_id.in_(source_asset_ids),
                Clip.status == "produced",
            )
        ).scalars().all()

    for clip in clips:
        for candidate in match_clip(session, clip):
            session.add(
                ClipMatch(
                    clip_id=clip.id,
                    campaign_id=candidate["campaign_id"],
                    match_score=candidate["match_score"],
                    meets_requirements=candidate["meets_requirements"],
                    rank=candidate["rank"],
                )
            )

    clip_job.status = "matched"
    clip_job.error = None
    session.commit()


def run_matching(session: Session, clip_job: ClipJob, *, now: str | None = None) -> ClipJob:
    """Match every produced `Clip` of `clip_job`'s source asset(s) against
    live campaigns, write ranked `ClipMatch` rows, and set
    `clip_job.status = "matched"`. Never raises -- any failure marks the
    job `failed` with an `error` message and commits, so a matching bug can
    never crash the scheduler."""
    resolved_now = now or utcnow_iso()

    try:
        _run_matching_inner(session, clip_job, resolved_now)
    except Exception as exc:
        # rollback FIRST (mirrors run_clipping): if the failure came from a
        # commit() inside the worker, SQLAlchemy 2.0 has deactivated the
        # transaction, and any ORM read -- even `clip_job.id` for a log
        # line -- would trigger a lazy load that raises PendingRollbackError.
        reason = str(exc)
        try:
            session.rollback()
            clip_job.status = "failed"
            clip_job.error = reason
            session.commit()
            log.error("clip_match_failed", clip_job_id=clip_job.id, error=reason)
        except Exception:
            log.error("clip_match_failure_record_failed", error=reason)

    return clip_job
