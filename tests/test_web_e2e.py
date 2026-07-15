import os

from fastapi.testclient import TestClient
from clipscore.config import Settings
from clipscore.db.models import Campaign, CampaignScore, Clip, ClipMatch, Outcome
from clipscore.factory.acquire.base import BaseAcquirer, AcquisitionResult
from clipscore.factory.clip.base import FakeClipEngine
from clipscore.jobs.clipfactory import process_clip_jobs
from clipscore.web.app import create_app, get_db


class _FakeAcquirer(BaseAcquirer):
    """No-network acquirer: writes a tiny local file and reports creator '@me'
    so the produced clip matches the seeded campaign (see match.py criteria)."""
    source_type = "campaign_provided"
    requires_authorization = False

    def acquire(self, source_ref, dest_path, **kw):
        os.makedirs(os.path.dirname(dest_path + ".mp4"), exist_ok=True)
        with open(dest_path + ".mp4", "wb") as fh:
            fh.write(b"x" * 42)
        return AcquisitionResult(status="acquired", platform="campaign_provided",
                                 creator="@me", storage_uri=dest_path + ".mp4", bytes=42)


def _client(session, settings):
    app = create_app(settings)
    def _override():
        yield session
    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def test_approve_produce_review_post_flow(session, tmp_path):
    settings = Settings(_env_file=None, media_dir=str(tmp_path / "media"),
                        clip_engine="fake", clip_est_cost_usd=1.0, max_media_gb=50.0)
    # a scored, clippable, campaign-provided campaign. target_creator '@me' +
    # target_platforms ['tiktok'] + no length window make the produced tiktok
    # clip (creator '@me', 60s) match this campaign in match_clip.
    session.add(Campaign(id="a", source="s", external_id="a", campaign_type="clipping",
                         title="E2E", niche="gaming", status="active",
                         access_status="ingestable", allowed_socials=["tiktok"],
                         first_seen_at="2026-07-01T00:00:00Z", last_seen_at="2026-07-01T00:00:00Z",
                         content_bank_url="https://drive.google.com/e2e",
                         target_creator='["@me"]', target_platforms='["tiktok"]'))
    session.add(CampaignScore(campaign_id="a", scored_at="2026-07-01T00:00:00Z",
                              cvs_niche_percentile=0.9))
    session.commit()

    client = _client(session, settings)

    # approve -> enqueue a queued clip_job
    assert client.post("/clip/a").status_code == 200

    # The scheduler's runner advances ONE stage per call (queued -> acquired ->
    # produced -> matched/ready), so loop until nothing advances. The web layer
    # never produces clips; we inject the fake acquirer + FakeClipEngine so no
    # network / real engine is touched.
    reg = {"campaign_provided": _FakeAcquirer()}
    for _ in range(6):
        res = process_clip_jobs(session, settings, registry=reg, engine=FakeClipEngine())
        if res["advanced"] == 0:
            break

    ready = session.query(Clip).filter_by(status="ready").all()
    assert ready, "expected at least one ready clip"
    clip = ready[0]
    match = session.query(ClipMatch).filter_by(clip_id=clip.id, campaign_id="a").first()
    assert match is not None

    # review renders
    assert client.get(f"/review/{clip.id}").status_code == 200

    # mark posted -> exactly one outcome
    assert client.post(f"/posted/{match.id}").status_code == 200
    assert session.query(Outcome).filter_by(clip_id=clip.id, campaign_id="a").count() == 1

    # a second post is idempotent; the dup warning now fires on the review page
    client.post(f"/posted/{match.id}")
    assert session.query(Outcome).filter_by(clip_id=clip.id, campaign_id="a").count() == 1
    assert "Already delivered to this campaign" in client.get(f"/review/{clip.id}").text
