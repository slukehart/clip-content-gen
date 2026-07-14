from clipscore.ingest.upsert import upsert_campaign, sweep_ended, run_ingest_batch
from clipscore.ingest.dto import CampaignUpsert, SnapshotData
from clipscore.db.models import Campaign, CampaignSnapshot
from tests.conftest import FakeIngester
from clipscore import config

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

def test_run_batch_ok_path_creates_campaigns_and_snapshots(session):
    raws = [
        {"external_id": f"c{i}", "cpm": 1.0 + i * 0.1, "budget": 1000 + i * 10,
         "spent": 100 + i, "clippers": 10 + i, "views": 50000 + i * 100}
        for i in range(50)
    ]
    ingester = FakeIngester(raws=raws)
    result = run_ingest_batch(session, ingester, "2026-07-13T00:00:00Z")
    assert result == {"status": "ok", "count": 50, "ended": 0}
    assert session.query(Campaign).count() == 50
    assert session.query(CampaignSnapshot).count() == 50

def test_run_batch_ends_campaign_across_polls(session, monkeypatch):
    monkeypatch.setenv("CLIPSCORE_HARVEST_MIN_CAMPAIGNS", "2")
    monkeypatch.setenv("CLIPSCORE_UNSEEN_POLLS_TO_END", "2")
    config.get_settings.cache_clear()
    try:
        miss_counts = {}

        raws_abc = [
            {"external_id": "a", "cpm": 1.0, "budget": 1000, "spent": 100, "clippers": 10, "views": 50000},
            {"external_id": "b", "cpm": 1.5, "budget": 1100, "spent": 200, "clippers": 20, "views": 60000},
            {"external_id": "c", "cpm": 2.0, "budget": 1200, "spent": 300, "clippers": 30, "views": 70000},
        ]
        raws_ab = raws_abc[:2]

        # Batch 1: a, b, c all present
        batch1 = FakeIngester(raws=raws_abc)
        result1 = run_ingest_batch(session, batch1, "2026-07-13T00:00:00Z", miss_counts=miss_counts)
        assert result1["status"] == "ok"

        # Batch 2: c missing -> miss count 1, still active
        batch2 = FakeIngester(raws=raws_ab)
        result2 = run_ingest_batch(session, batch2, "2026-07-13T01:00:00Z", miss_counts=miss_counts)
        assert result2["status"] == "ok"
        assert session.query(Campaign).filter_by(external_id="c").one().status == "active"

        # Batch 3: c missing again -> miss count 2 == threshold -> ended
        batch3 = FakeIngester(raws=raws_ab)
        result3 = run_ingest_batch(session, batch3, "2026-07-13T02:00:00Z", miss_counts=miss_counts)
        assert result3["status"] == "ok"
        assert session.query(Campaign).filter_by(external_id="c").one().status == "ended"
        assert session.query(Campaign).filter_by(external_id="a").one().status == "active"
        assert session.query(Campaign).filter_by(external_id="b").one().status == "active"
    finally:
        config.get_settings.cache_clear()
