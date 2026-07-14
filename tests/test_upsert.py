from clipscore.ingest.upsert import upsert_campaign
from clipscore.ingest.dto import CampaignUpsert, SnapshotData
from clipscore.db.models import Campaign, CampaignSnapshot

def _up(external_id="x", remaining=800.0, total=1000.0, spent=200.0, status="active"):
    return CampaignUpsert(
        source="fake", external_id=external_id, title="t", niche="gaming",
        cpm_usd=1.5, platform_fee_pct=0.1, budget_total_usd=total, status=status,
        snapshot=SnapshotData(budget_total_usd=total, budget_spent_usd=spent,
                              budget_remaining_usd=remaining, active_clippers=10, total_views=1),
    )

def test_insert_then_update_same_row(session):
    c1 = upsert_campaign(session, _up(remaining=800.0), "2026-07-13T00:00:00Z")
    c2 = upsert_campaign(session, _up(remaining=700.0), "2026-07-13T01:00:00Z")
    assert c1.id == c2.id
    assert session.query(Campaign).count() == 1
    assert session.query(CampaignSnapshot).count() == 2
    assert c2.last_seen_at == "2026-07-13T01:00:00Z"

def test_epoch_stays_when_budget_burns_down(session):
    upsert_campaign(session, _up(remaining=800.0), "2026-07-13T00:00:00Z")
    upsert_campaign(session, _up(remaining=600.0), "2026-07-13T01:00:00Z")
    epochs = [s.epoch for s in session.query(CampaignSnapshot).all()]
    assert epochs == [0, 0]

def test_epoch_increments_on_budget_topup(session):
    upsert_campaign(session, _up(remaining=200.0), "2026-07-13T00:00:00Z")
    # remaining jumps 200 -> 900 (>10% up) => new epoch
    upsert_campaign(session, _up(remaining=900.0, total=1500.0), "2026-07-13T01:00:00Z")
    epochs = [s.epoch for s in session.query(CampaignSnapshot).order_by(CampaignSnapshot.id).all()]
    assert epochs == [0, 1]

def test_ended_campaign_revives_and_new_epoch(session):
    c = upsert_campaign(session, _up(remaining=100.0), "2026-07-13T00:00:00Z")
    c.status = "ended"; session.commit()
    upsert_campaign(session, _up(remaining=100.0, status="active"), "2026-07-13T02:00:00Z")
    latest = session.query(CampaignSnapshot).order_by(CampaignSnapshot.id.desc()).first()
    assert latest.epoch == 1
    assert session.get(Campaign, c.id).status == "active"

def test_campaign_type_is_persisted(session):
    # regression: normalize sets campaign_type on the DTO, but upsert must copy it
    # onto the Campaign row. Previously omitted from the field-copy loop -> all rows
    # persisted campaign_type=None, so UGC campaigns were never distinguished.
    up = _up(); up.campaign_type = "ugc"
    c = upsert_campaign(session, up, "2026-07-13T00:00:00Z")
    assert session.get(Campaign, c.id).campaign_type == "ugc"

def test_campaign_type_updates_on_reupsert(session):
    up1 = _up(); up1.campaign_type = "clipping"
    c = upsert_campaign(session, up1, "2026-07-13T00:00:00Z")
    up2 = _up(); up2.campaign_type = "both"
    upsert_campaign(session, up2, "2026-07-13T01:00:00Z")
    assert session.get(Campaign, c.id).campaign_type == "both"
