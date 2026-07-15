"""Captioning -- Pipeline B Stage B3 Task 5.

Every suggested caption must carry an FTC `#ad` disclosure -- a paid clip is
a "material connection" under US FTC rules, and CLAUDE.md's compliance-first
principle means this is enforced regardless of what the campaign's
`caption_rules` say, and regardless of what an LLM enrichment step returns.

`caption_floor` is the deterministic guarantee: it always contains `#ad`,
with no network call and no way to fail. `suggest_caption` layers optional
LLM enrichment (via `factory/llm.py`) on top of that floor, but re-enforces
`#ad` on the LLM's output and falls back to the floor on any error -- so the
floor is the true guarantee, the LLM is a nice-to-have.

`run_caption` mirrors `factory/clip/match.py`'s `run_matching` guard shape:
an inner worker does the real work, and an outer `try/except Exception`
ensures a captioning failure never propagates out of this job.
"""
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from clipscore.config import Settings
from clipscore.db.models import Campaign, Clip, ClipJob, ClipMatch, SourceAsset
from clipscore.factory.llm import LLMClient

log = structlog.get_logger()

AD_TAG = "#ad"

_SYSTEM_PROMPT = (
    "You write short, engaging social captions for clipped video content. "
    "Follow any brand caption rules given. Keep it concise."
)


def _ensure_ad_tag(text: str) -> str:
    """Append AD_TAG to `text` unless already present (case-insensitive)."""
    if AD_TAG.lower() in text.lower():
        return text
    text = text.rstrip()
    return f"{text} {AD_TAG}".strip()


def caption_floor(campaign: Campaign) -> str:
    """Deterministic floor caption: `campaign.caption_rules` (or empty)
    with `#ad` guaranteed present. Never empty -- absent rules -> `"#ad"`."""
    base = (campaign.caption_rules or "").strip()
    return _ensure_ad_tag(base)


def suggest_caption(campaign: Campaign, clip: Clip, settings: Settings, *, llm=None) -> str:
    """Compute the deterministic floor, then optionally enrich it via an
    LLM. Any LLM failure (missing key, `LLMError`, or any other exception)
    falls back to the floor. Return value always contains `#ad`."""
    floor = caption_floor(campaign)

    if not settings.llm_api_key:
        return floor

    try:
        client = llm or LLMClient(
            settings.llm_base_url, settings.llm_model, settings.llm_api_key,
            settings.http_timeout_s,
        )
        user = (
            f"Transcript: {clip.transcript or ''}\n"
            f"Brand caption rules: {campaign.caption_rules or ''}\n"
            "Write a single short caption for this clip."
        )
        enriched = client.chat_text(_SYSTEM_PROMPT, user)
        if not isinstance(enriched, str) or not enriched.strip():
            return floor
        return _ensure_ad_tag(enriched)
    except Exception:
        # LLMError or any other failure (network, bad response, etc.) --
        # the floor caption is always a safe, compliant fallback.
        return floor


def _run_caption_inner(session: Session, clip_job: ClipJob, settings: Settings, llm) -> None:
    source_asset_ids = session.execute(
        select(SourceAsset.id).where(SourceAsset.clip_job_id == clip_job.id)
    ).scalars().all()

    clips = []
    if source_asset_ids:
        clips = session.execute(
            select(Clip).where(
                Clip.source_asset_id.in_(source_asset_ids),
                Clip.status == "produced",
            )
        ).scalars().all()

    for clip in clips:
        top_match = session.execute(
            select(ClipMatch).where(ClipMatch.clip_id == clip.id, ClipMatch.rank == 1)
        ).scalars().one_or_none()

        if top_match is not None:
            campaign = session.get(Campaign, top_match.campaign_id)
            if campaign is not None:
                top_match.suggested_caption = suggest_caption(campaign, clip, settings, llm=llm)

        # Always advance the clip to the review queue, captioned or not.
        clip.status = "ready"

    session.commit()


def run_caption(session: Session, clip_job: ClipJob, settings: Settings, *, llm=None) -> ClipJob:
    """Caption every produced `Clip` of `clip_job`'s source asset(s) that has
    a rank-1 `ClipMatch`, and advance every produced clip to `status="ready"`
    regardless. Never raises -- any failure marks the job `failed` with an
    `error` message and commits, so a captioning bug can never crash the
    scheduler."""
    try:
        _run_caption_inner(session, clip_job, settings, llm)
    except Exception as exc:
        # rollback FIRST (mirrors run_matching/run_clipping): if the failure
        # came from a commit() inside the worker, SQLAlchemy 2.0 has
        # deactivated the transaction, and any ORM read -- even
        # `clip_job.id` for a log line -- would trigger a lazy load that
        # raises PendingRollbackError.
        reason = str(exc)
        try:
            session.rollback()
            clip_job.status = "failed"
            clip_job.error = reason
            session.commit()
            log.error("clip_caption_failed", clip_job_id=clip_job.id, error=reason)
        except Exception:
            log.error("clip_caption_failure_record_failed", error=reason)

    return clip_job
