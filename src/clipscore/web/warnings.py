"""Pure, advisory duplicate-deliverable checks for the B4 review surface.
Returns human-readable warning strings; NEVER blocks a post (compliance-first
means we surface the risk and let the operator decide)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from clipscore.db.models import Outcome, Clip


def duplicate_warnings(session: Session, clip_id: int, campaign_id: str) -> list[str]:
    warnings: list[str] = []

    # (1) repeat delivery: this campaign already has an outcome
    existing = session.execute(
        select(Outcome).where(Outcome.campaign_id == campaign_id)
    ).scalars().first()
    if existing is not None:
        warnings.append(
            f"Already delivered to this campaign (outcome logged {existing.logged_at})."
        )

    # (2) footage reuse: another clip from the same source asset was posted to
    #     a DIFFERENT campaign
    clip = session.get(Clip, clip_id)
    if clip is not None and clip.source_asset_id is not None:
        sibling_ids = session.execute(
            select(Clip.id).where(Clip.source_asset_id == clip.source_asset_id)
        ).scalars().all()
        others = session.execute(
            select(Outcome.campaign_id).where(
                Outcome.clip_id.in_(sibling_ids),
                Outcome.campaign_id != campaign_id,
            )
        ).scalars().all()
        for other in dict.fromkeys(others):   # distinct, order-preserving
            warnings.append(f"This source footage was already posted to campaign {other}.")

    return warnings
