from fastapi.testclient import TestClient
from clipscore.config import Settings
from clipscore.db.models import Campaign, CampaignScore
from clipscore.web.app import create_app, get_db


def _client(session):
    app = create_app(Settings(_env_file=None, clip_est_cost_usd=2.0))
    def _override():
        yield session
    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def _camp(session, cid, pct=0.8, bank="https://drive.google.com/x"):
    session.add(Campaign(id=cid, source="s", external_id=cid, campaign_type="clipping",
                         title=f"T {cid}", niche="gaming", status="active",
                         access_status="ingestable", first_seen_at="2026-01-01T00:00:00Z",
                         last_seen_at="2026-01-01T00:00:00Z", content_bank_url=bank))
    session.add(CampaignScore(campaign_id=cid, scored_at="2026-01-01T00:00:00Z",
                              cvs_niche_percentile=pct))
    session.commit()


def test_approval_page_lists_campaigns(session):
    _camp(session, "a")
    resp = _client(session).get("/")
    assert resp.status_code == 200
    assert "T a" in resp.text
    assert 'name="source_ref"' in resp.text   # manual-source clip input renders


def test_post_clip_enqueues(session):
    _camp(session, "a")
    resp = _client(session).post("/clip/a")
    assert resp.status_code == 200
    assert "queued" in resp.text.lower()
    from clipscore.db.models import ClipJob
    assert session.query(ClipJob).filter_by(campaign_id="a").count() == 1


def test_post_clip_no_source_shows_error(session):
    _camp(session, "a", bank=None)
    resp = _client(session).post("/clip/a")
    assert resp.status_code == 200
    assert "no acquirable source" in resp.text
