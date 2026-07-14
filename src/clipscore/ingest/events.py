"""Audit + halt side-effects for drop-don't-evade."""
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from clipscore.db.models import FetchEvent, Campaign
from clipscore.time import utcnow_iso

def log_fetch_event(session: Session, source: str, url: str, event_type: str,
                    http_status: int | None = None, detail: str | None = None) -> None:
    session.add(FetchEvent(source=source, url=url, event_type=event_type,
                           http_status=http_status, detail=detail,
                           detected_at=utcnow_iso()))
    session.commit()

def flip_access_status(session: Session, source: str, access_status: str) -> int:
    result = session.execute(
        update(Campaign).where(Campaign.source == source).values(access_status=access_status)
    )
    session.commit()
    return result.rowcount
