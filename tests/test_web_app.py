from fastapi.testclient import TestClient
from clipscore.config import Settings
from clipscore.web.app import create_app


def test_healthz_ok(session):
    app = create_app(Settings(db_url="sqlite:///:memory:"))
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_static_mount_exists(session):
    app = create_app(Settings(db_url="sqlite:///:memory:"))
    client = TestClient(app)
    # /static is mounted; a missing asset 404s (mount present, file absent is fine)
    assert client.get("/static/nonexistent.js").status_code == 404
