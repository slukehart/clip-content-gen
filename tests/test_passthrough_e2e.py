"""Integration test for the real PassthroughAcquirer -> match_clip path
(Pipeline B Stage B4.5, C1/C2 fix).

The e2e test in `test_web_e2e.py` uses a `_FakeAcquirer` that hardcodes
`creator="@me"`, so nothing exercises the real `PassthroughAcquirer` (which
never sets `creator` -- Vizard fetches by URL, there is no download to read
metadata from). Before the C1 fix in `factory/acquire/run.py`, a passthrough
source's `SourceAsset.creator` was always `None`, so `match_clip` could never
match any campaign. This test uses the REAL `build_registry()` (real
`PassthroughAcquirer`) end to end and asserts a match is produced.
"""
from clipscore.config import Settings
from clipscore.db.models import Campaign, CampaignScore, ClipMatch
from clipscore.factory.acquire.registry import build_registry
from clipscore.factory.clip.base import FakeClipEngine
from clipscore.jobs.clipfactory import create_clip_job, process_clip_jobs
from clipscore.time import utcnow_iso


def test_passthrough_acquirer_sets_creator_and_matches(session, tmp_path):
    now = utcnow_iso()
    session.add(Campaign(
        id="c1", source="s", external_id="c1", campaign_type="clipping",
        title="Passthrough E2E", niche="gaming", status="active",
        access_status="ingestable", first_seen_at=now, last_seen_at=now,
        content_bank_url="https://www.youtube.com/watch?v=abc",
        target_creator='["@diego"]', target_platforms='["tiktok"]',
    ))
    session.add(CampaignScore(campaign_id="c1", scored_at=now, cvs_niche_percentile=0.9))
    session.commit()

    settings = Settings(_env_file=None, media_dir=str(tmp_path / "media"),
                        clip_engine="fake", clip_est_cost_usd=1.0, max_media_gb=50.0)

    job = create_clip_job(session, "c1", settings)
    assert job.source_type == "passthrough"

    registry = build_registry()
    for _ in range(6):
        res = process_clip_jobs(session, settings, registry=registry, engine=FakeClipEngine())
        if res["advanced"] == 0:
            break

    from clipscore.db.models import Clip, SourceAsset
    source_asset = session.query(SourceAsset).filter_by(clip_job_id=job.id).first()
    assert source_asset is not None
    assert source_asset.creator == "@diego"

    ready_clips = session.query(Clip).filter(Clip.source_asset_id == source_asset.id,
                                             Clip.status == "ready").all()
    assert ready_clips, "expected at least one ready clip"

    matches = session.query(ClipMatch).filter_by(campaign_id="c1").all()
    assert matches, "expected at least one ClipMatch for the campaign"
    rank1 = [m for m in matches if m.rank == 1]
    assert rank1, "expected a rank==1 match"
    assert rank1[0].suggested_caption is not None
    assert "#ad" in rank1[0].suggested_caption
