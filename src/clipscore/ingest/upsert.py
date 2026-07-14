import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from clipscore.ingest.dto import CampaignUpsert
from clipscore.db.models import Campaign, CampaignSnapshot

EPOCH_RESET_RATIO = 1.10

def _latest_snapshot(session: Session, campaign_id: str) -> CampaignSnapshot | None:
    return session.execute(
        select(CampaignSnapshot).where(CampaignSnapshot.campaign_id == campaign_id)
        .order_by(CampaignSnapshot.id.desc()).limit(1)
    ).scalars().first()

def _current_epoch(session: Session, campaign_id: str, new_remaining, was_ended: bool) -> int:
    latest = _latest_snapshot(session, campaign_id)
    if latest is None:
        return 0
    if was_ended:
        return latest.epoch + 1
    prev = latest.budget_remaining_usd
    if prev is not None and new_remaining is not None and prev > 0 and new_remaining > prev * EPOCH_RESET_RATIO:
        return latest.epoch + 1
    return latest.epoch

def upsert_campaign(session: Session, up: CampaignUpsert, seen_at: str) -> Campaign:
    existing = session.execute(
        select(Campaign).where(Campaign.source == up.source, Campaign.external_id == up.external_id)
    ).scalars().first()

    was_ended = existing is not None and existing.status == "ended"

    if existing is None:
        campaign = Campaign(
            id=uuid.uuid4().hex, source=up.source, external_id=up.external_id,
            first_seen_at=seen_at, last_seen_at=seen_at,
        )
        session.add(campaign)
    else:
        campaign = existing
        campaign.last_seen_at = seen_at

    # apply mutable fields
    for field in ("title", "niche", "cpm_usd", "platform_fee_pct", "cap_per_post_usd",
                  "cap_provenance", "min_payout_threshold_usd", "min_views_threshold",
                  "budget_total_usd", "allowed_socials", "requirements_raw", "status",
                  "is_verified", "whop_experience_id", "whop_product_route", "url", "brand"):
        setattr(campaign, field, getattr(up, field))

    session.flush()  # ensure campaign.id available

    epoch = _current_epoch(session, campaign.id, up.snapshot.budget_remaining_usd, was_ended)
    session.add(CampaignSnapshot(
        campaign_id=campaign.id, epoch=epoch,
        budget_total_usd=up.snapshot.budget_total_usd,
        budget_spent_usd=up.snapshot.budget_spent_usd,
        budget_remaining_usd=up.snapshot.budget_remaining_usd,
        active_clippers=up.snapshot.active_clippers,
        total_views=up.snapshot.total_views,
        success_rate=up.snapshot.success_rate,
        engagement=up.snapshot.engagement,
        captured_at=seen_at,
    ))
    session.commit()
    return campaign
