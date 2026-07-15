from fastapi.testclient import TestClient
from clipscore.config import Settings
from clipscore.db.models import Campaign
from clipscore.web.app import create_app, get_db


def _client(session):
    app = create_app(Settings())
    def _override():
        yield session
    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def test_manual_form_renders(session):
    resp = _client(session).get("/manual")
    assert resp.status_code == 200 and "<form" in resp.text


def test_manual_post_creates_campaign_and_job(session):
    resp = _client(session).post("/manual", data={
        "title": "Hand Entry", "niche": "gaming",
        "content_bank_url": "https://drive.google.com/z", "target_creator": "",
    })
    assert resp.status_code == 200
    assert session.query(Campaign).filter_by(source="manual").count() == 1
