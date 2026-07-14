from clipscore.ingest.upsert import upsert_campaign
from clipscore.ingest.dto import CampaignUpsert, SnapshotData
from clipscore.db.models import CampaignSnapshot
from sqlalchemy import select

def _up(status, remaining):
    return CampaignUpsert(source="cr", external_id="x", status=status,
                          snapshot=SnapshotData(budget_total_usd=1000,
                                                budget_remaining_usd=remaining))

def _epochs(session):
    return [s.epoch for s in session.execute(
        select(CampaignSnapshot).order_by(CampaignSnapshot.id)).scalars().all()]

def test_present_ended_does_not_inflate_epoch(session):
    for _ in range(3):
        upsert_campaign(session, _up("ended", 500), "2026-07-13T00:00:00Z")
    assert _epochs(session) == [0, 0, 0]

def test_revival_bumps_epoch(session):
    upsert_campaign(session, _up("ended", 500), "2026-07-13T00:00:00Z")
    upsert_campaign(session, _up("active", 500), "2026-07-13T01:00:00Z")
    assert _epochs(session) == [0, 1]

def test_budget_topup_still_bumps(session):
    upsert_campaign(session, _up("active", 100), "2026-07-13T00:00:00Z")
    upsert_campaign(session, _up("active", 1000), "2026-07-13T01:00:00Z")  # >1.10x
    assert _epochs(session)[-1] == 1
