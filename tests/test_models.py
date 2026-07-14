from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from clipscore.db.base import Base
from clipscore.db.models import Campaign, CampaignSnapshot, PlatformTrust

def test_create_and_roundtrip_campaign():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        c = Campaign(
            id="cid-1", source="contentrewards", external_id="ext-1",
            title="Roobet UGC", niche="entertainment", cpm_usd=1.5,
            platform_fee_pct=0.10, allowed_socials=["tiktok", "reels"],
            status="active", ingest_method="auto", access_status="ingestable",
            cap_provenance="absent", first_seen_at="2026-07-13T00:00:00Z",
            last_seen_at="2026-07-13T00:00:00Z",
        )
        s.add(c)
        s.commit()
        got = s.get(Campaign, "cid-1")
        assert got.allowed_socials == ["tiktok", "reels"]
        assert got.cpm_usd == 1.5

def test_snapshot_has_epoch_and_fk():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        snap = CampaignSnapshot(
            campaign_id="cid-1", epoch=0, budget_total_usd=1000.0,
            budget_spent_usd=200.0, budget_remaining_usd=800.0,
            active_clippers=50, total_views=1_000_000,
            success_rate=0.4, engagement=0.1, captured_at="2026-07-13T00:00:00Z",
        )
        s.add(snap)
        s.commit()
        assert snap.id is not None
        assert snap.epoch == 0
