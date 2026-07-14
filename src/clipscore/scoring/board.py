"""Single source of truth for 'which scored campaigns are on the board / alertable':
the latest score per campaign, restricted to currently-eligible campaigns. Consumed
by jobs.rank and the bot so the eligibility predicate lives in exactly one place."""
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from clipscore.db.models import Campaign, CampaignScore


def eligible_latest_scores(session: Session) -> list[tuple[Campaign, CampaignScore]]:
    latest_ids = select(func.max(CampaignScore.id)).group_by(CampaignScore.campaign_id)
    scores = session.execute(
        select(CampaignScore).where(CampaignScore.id.in_(latest_ids))
    ).scalars().all()
    camps = {c.id: c for c in session.execute(select(Campaign)).scalars().all()}
    out = []
    for s in scores:
        c = camps.get(s.campaign_id)
        if c is None:
            continue
        if c.status != "active" or c.access_status != "ingestable" or c.campaign_type == "ugc":
            continue
        out.append((c, s))
    return out
