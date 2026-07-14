from clipscore.ingest.upsert import upsert_campaign, sweep_ended, run_ingest_batch
from clipscore.ingest.dto import CampaignUpsert, SnapshotData
from clipscore.db.models import Campaign
from tests.conftest import FakeIngester

def _up(external_id):
    return CampaignUpsert(source="fake", external_id=external_id, title="t", niche="gaming",
        cpm_usd=1.0, platform_fee_pct=0.1, budget_total_usd=100.0, status="active",
        snapshot=SnapshotData(budget_remaining_usd=100.0, active_clippers=1, total_views=1))

def test_sweep_marks_ended_after_threshold(session):
    upsert_campaign(session, _up("a"), "2026-07-13T00:00:00Z")
    upsert_campaign(session, _up("b"), "2026-07-13T00:00:00Z")
    misses = {}
    # "b" missing across 3 polls with threshold 3
    for _ in range(3):
        n = sweep_ended(session, "fake", current_ids={"a"}, miss_counts=misses, threshold=3)
    assert session.get(Campaign, session.query(Campaign).filter_by(external_id="b").one().id).status == "ended"
    assert session.query(Campaign).filter_by(external_id="a").one().status == "active"

def test_sweep_not_triggered_before_threshold(session):
    upsert_campaign(session, _up("a"), "2026-07-13T00:00:00Z")
    upsert_campaign(session, _up("b"), "2026-07-13T00:00:00Z")
    misses = {}
    sweep_ended(session, "fake", current_ids={"a"}, miss_counts=misses, threshold=3)  # 1 miss
    assert session.query(Campaign).filter_by(external_id="b").one().status == "active"

def test_run_batch_skips_sweep_when_harvest_too_small(session, monkeypatch):
    # seed one active campaign
    upsert_campaign(session, _up("a"), "2026-07-13T00:00:00Z")
    # fetch returns 0 campaigns; harvest_min_campaigns default 50 => skip
    empty = FakeIngester(raws=[])
    misses = {}
    result = run_ingest_batch(session, empty, "2026-07-13T01:00:00Z", miss_counts=misses)
    assert result["status"] == "harvest_too_small"
    assert session.query(Campaign).filter_by(external_id="a").one().status == "active"
