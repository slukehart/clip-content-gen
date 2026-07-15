from fastapi.testclient import TestClient
from clipscore.config import Settings
from clipscore.db.models import Campaign, Clip, SourceAsset, ClipMatch, Outcome
from clipscore.web.app import create_app, get_db


def _client(session, settings=None):
    app = create_app(settings or Settings())
    def _override():
        yield session
    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def _ready_clip(session, cid="a"):
    session.add(Campaign(id=cid, source="s", external_id=cid, campaign_type="clipping",
                         title=f"T {cid}", status="active", access_status="ingestable",
                         first_seen_at="2026-01-01T00:00:00Z", last_seen_at="2026-01-01T00:00:00Z"))
    sa = SourceAsset(clip_job_id=1, storage_uri="media/x.mp4"); session.add(sa); session.commit()
    clip = Clip(source_asset_id=sa.id, platform_variant="tiktok", duration_s=60,
                status="ready", cost_usd=0.5, created_at="2026-07-10T00:00:00Z")
    session.add(clip); session.commit()
    m = ClipMatch(clip_id=clip.id, campaign_id=cid, match_score=0.7, meets_requirements=1,
                  suggested_caption="watch #ad", rank=1); session.add(m); session.commit()
    return clip, m


def test_review_list(session):
    _ready_clip(session)
    resp = _client(session).get("/review")
    assert resp.status_code == 200 and "60s" in resp.text


def test_review_detail_renders_video_and_caption(session):
    clip, m = _ready_clip(session)
    resp = _client(session).get(f"/review/{clip.id}")
    assert resp.status_code == 200
    assert f"/media/{clip.id}" in resp.text
    assert "watch #ad" in resp.text
    assert "T a" in resp.text


def test_review_detail_404(session):
    assert _client(session).get("/review/9999").status_code == 404


def test_review_shows_duplicate_warning(session):
    clip, m = _ready_clip(session)
    session.add(Outcome(campaign_id="a", clip_id=clip.id, clips_posted=1,
                        logged_at="2026-07-10T00:00:00Z")); session.commit()
    resp = _client(session).get(f"/review/{clip.id}")
    assert "Already delivered to this campaign" in resp.text


def test_post_posted_writes_outcome(session):
    clip, m = _ready_clip(session)
    resp = _client(session).post(f"/posted/{m.id}")
    assert resp.status_code == 200 and "posted" in resp.text.lower()
    assert session.query(Outcome).filter_by(clip_id=clip.id, campaign_id="a").count() == 1
    # idempotent: second post does not append
    _client(session).post(f"/posted/{m.id}")
    assert session.query(Outcome).filter_by(clip_id=clip.id, campaign_id="a").count() == 1
