"""Alert dedup state: one alert per (campaign_id, epoch). A relaunch bumps the
epoch (see ingest.upsert), so a genuinely relaunched campaign can alert again."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from clipscore.db.models import Alert


def already_alerted(session: Session, campaign_id: str, epoch: int) -> bool:
    row = session.execute(
        select(Alert.id).where(Alert.campaign_id == campaign_id, Alert.epoch == epoch)
    ).first()
    return row is not None


def record_alert(session: Session, campaign_id: str, epoch: int, niche,
                 percentile, alerted_at: str) -> None:
    session.add(Alert(campaign_id=campaign_id, epoch=epoch, niche=niche,
                      cvs_niche_percentile=percentile, alerted_at=alerted_at))
    session.commit()
