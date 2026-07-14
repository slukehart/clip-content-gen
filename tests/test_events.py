from clipscore.ingest.events import log_fetch_event, flip_access_status
from clipscore.ingest.upsert import upsert_campaign
from clipscore.ingest.dto import CampaignUpsert, SnapshotData
from clipscore.db.models import FetchEvent, Campaign
from sqlalchemy import select

def test_log_fetch_event(session):
    log_fetch_event(session, "cr", "https://x/discover", "blocked_403", 403, "Forbidden")
    ev = session.execute(select(FetchEvent)).scalars().one()
    assert ev.url == "https://x/discover" and ev.event_type == "blocked_403"
    assert ev.http_status == 403 and ev.detected_at.endswith("Z")

def test_flip_access_status(session):
    upsert_campaign(session, CampaignUpsert(source="cr", external_id="a",
                    snapshot=SnapshotData()), "2026-07-13T00:00:00Z")
    n = flip_access_status(session, "cr", "tos_restricted")
    assert n == 1
    c = session.execute(select(Campaign)).scalars().one()
    assert c.access_status == "tos_restricted"
