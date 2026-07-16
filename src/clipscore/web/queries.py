"""Pure, read-only queries backing the B4 dashboard. No writes, no network,
no request objects -- takes a Session, returns pydantic view models, and is
fully unit-testable. Reuses A's ranking (`eligible_latest_scores`)."""
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from clipscore.config import Settings
from clipscore.db.models import Campaign, ClipJob, Clip, ClipMatch
from clipscore.factory.clip.cost import month_credits_used
from clipscore.scoring.board import eligible_latest_scores
from clipscore.time import et_month_bounds_utc
from pydantic import BaseModel

_CLIPPING = ("clipping", "both")


class ApprovalRow(BaseModel):
    campaign_id: str
    title: str | None = None
    url: str | None = None
    niche: str | None = None
    campaign_type: str | None = None
    cvs_niche_percentile: float | None = None
    est_cost_usd: float = 0.0
    job_status: str | None = None
    clippable: bool = False


class ReviewClip(BaseModel):
    clip_id: int
    duration_s: int | None = None
    status: str
    cost_usd: float | None = None
    campaign_id_of_job: str | None = None


class MatchRow(BaseModel):
    match_id: int
    campaign_id: str
    campaign_title: str | None = None
    match_score: float | None = None
    meets_requirements: int | None = None
    suggested_caption: str | None = None
    rank: int | None = None


class ReviewDetail(BaseModel):
    clip: ReviewClip
    matches: list[MatchRow]
    requirements: dict
    download_url: str


def _latest_job_status(session: Session, campaign_id: str) -> str | None:
    jid = session.execute(
        select(func.max(ClipJob.id)).where(ClipJob.campaign_id == campaign_id)
    ).scalar_one_or_none()
    if jid is None:
        return None
    return session.get(ClipJob, jid).status


def approval_rows(session: Session, settings: Settings) -> list[ApprovalRow]:
    targets = settings.target_niche_set
    rows: list[ApprovalRow] = []
    for camp, score in eligible_latest_scores(session):
        if camp.campaign_type not in _CLIPPING:
            continue
        if targets and (camp.niche or "other").lower() not in targets:
            continue
        rows.append(ApprovalRow(
            campaign_id=camp.id, title=camp.title, url=camp.url, niche=camp.niche,
            campaign_type=camp.campaign_type,
            cvs_niche_percentile=score.cvs_niche_percentile,
            est_cost_usd=settings.clip_est_cost_usd,
            job_status=_latest_job_status(session, camp.id),
            clippable=bool(camp.content_bank_url or camp.target_creator),
        ))
    rows.sort(key=lambda r: (r.cvs_niche_percentile is None,
                             -(r.cvs_niche_percentile or 0.0)))
    return rows


def _to_review_clip(session: Session, clip: Clip) -> ReviewClip:
    return ReviewClip(
        clip_id=clip.id, duration_s=clip.duration_s,
        status=clip.status, cost_usd=clip.cost_usd,
    )


def ready_clips(session: Session) -> list[ReviewClip]:
    clips = session.execute(
        select(Clip).where(Clip.status == "ready").order_by(Clip.id.desc())
    ).scalars().all()
    return [_to_review_clip(session, c) for c in clips]


def review_detail(session: Session, clip_id: int) -> ReviewDetail | None:
    clip = session.get(Clip, clip_id)
    if clip is None:
        return None
    matches_q = session.execute(
        select(ClipMatch).where(ClipMatch.clip_id == clip_id)
    ).scalars().all()
    rows: list[MatchRow] = []
    for m in matches_q:
        camp = session.get(Campaign, m.campaign_id)
        rows.append(MatchRow(
            match_id=m.id, campaign_id=m.campaign_id,
            campaign_title=camp.title if camp else None,
            match_score=m.match_score, meets_requirements=m.meets_requirements,
            suggested_caption=m.suggested_caption, rank=m.rank,
        ))
    rows.sort(key=lambda r: (r.rank is None, r.rank or 0))

    requirements: dict = {}
    if rows:
        camp = session.get(Campaign, rows[0].campaign_id)
        if camp is not None:
            requirements = {
                "caption_rules": camp.caption_rules,
                "banned_content": camp.banned_content,
                "clip_min_len_s": camp.clip_min_len_s,
                "clip_max_len_s": camp.clip_max_len_s,
                "target_platforms": camp.target_platforms,
            }
    return ReviewDetail(
        clip=_to_review_clip(session, clip), matches=rows,
        requirements=requirements, download_url=f"/media/{clip_id}",
    )


def monthly_cost_usd(session: Session, now=None) -> float:
    start, nxt = et_month_bounds_utc(now)
    clips = session.execute(
        select(Clip.cost_usd).where(
            Clip.created_at >= start, Clip.created_at < nxt
        )
    ).scalars().all()
    return float(sum(c or 0.0 for c in clips))


class CreditStatus(BaseModel):
    used: int
    cap: int                    # 0 = uncapped
    remaining: int | None       # None when uncapped
    pct: float | None           # 0-100, clamped; None when uncapped


def monthly_credit_status(session: Session, settings: Settings, now=None) -> CreditStatus:
    """Vizard credits consumed this ET month vs. the configured monthly cap.
    Mirrors the B5 cost gate's accounting (real `credits_used` on clip_jobs).
    `cap == 0` means uncapped -> remaining/pct are None."""
    used = month_credits_used(session, now)
    cap = settings.monthly_cap_credits
    if cap > 0:
        remaining = max(0, cap - used)
        pct = min(100.0, used / cap * 100.0)
    else:
        remaining = None
        pct = None
    return CreditStatus(used=used, cap=cap, remaining=remaining, pct=pct)
