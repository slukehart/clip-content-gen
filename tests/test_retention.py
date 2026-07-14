from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from clipscore.db.models import CampaignSnapshot
from clipscore.jobs.retention import rollup_snapshots

def iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)

def _snap(session, cid, dt):
    s = CampaignSnapshot(campaign_id=cid, epoch=0, budget_remaining_usd=100.0,
                         captured_at=iso(dt))
    session.add(s); session.commit(); return s

def test_recent_snapshots_untouched(session):
    # three snapshots within the same hour but < 14 days old -> all kept
    for m in (0, 20, 40):
        _snap(session, "a", NOW - timedelta(days=1, minutes=m))
    res = rollup_snapshots(session, iso(NOW))
    assert res["deleted"] == 0
    assert len(session.execute(select(CampaignSnapshot)).scalars().all()) == 3

def test_old_same_hour_rolled_up_to_one(session):
    old = NOW - timedelta(days=20)
    for m in (0, 20, 40):
        _snap(session, "a", old + timedelta(minutes=m))
    res = rollup_snapshots(session, iso(NOW))
    assert res["deleted"] == 2
    remaining = session.execute(select(CampaignSnapshot)).scalars().all()
    assert len(remaining) == 1

def test_old_different_hours_all_kept(session):
    old = NOW - timedelta(days=20)
    for h in (0, 1, 2):
        _snap(session, "a", old + timedelta(hours=h))
    res = rollup_snapshots(session, iso(NOW))
    assert res["deleted"] == 0

def test_per_campaign_isolation(session):
    old = NOW - timedelta(days=20)
    for m in (0, 30):
        _snap(session, "a", old + timedelta(minutes=m))
        _snap(session, "b", old + timedelta(minutes=m))
    rollup_snapshots(session, iso(NOW))
    a = session.execute(select(CampaignSnapshot).where(CampaignSnapshot.campaign_id == "a")).scalars().all()
    b = session.execute(select(CampaignSnapshot).where(CampaignSnapshot.campaign_id == "b")).scalars().all()
    assert len(a) == 1 and len(b) == 1
