import os
from fastapi.testclient import TestClient
from clipscore.config import Settings
from clipscore.db.models import Clip, SourceAsset
from clipscore.web.app import create_app, get_db


def _client(session, settings):
    app = create_app(settings)
    def _override():
        yield session
    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def test_media_serves_file_under_media_dir(session, tmp_path):
    media = tmp_path / "media"
    (media / "clips").mkdir(parents=True)
    f = media / "clips" / "c.mp4"
    f.write_bytes(b"\x00\x01\x02")
    sa = SourceAsset(clip_job_id=1); session.add(sa); session.commit()
    clip = Clip(source_asset_id=sa.id, status="ready", storage_uri=str(f),
                created_at="2026-07-10T00:00:00Z"); session.add(clip); session.commit()
    client = _client(session, Settings(media_dir=str(media)))
    resp = client.get(f"/media/{clip.id}")
    assert resp.status_code == 200 and resp.content == b"\x00\x01\x02"


def test_media_404_when_missing_uri(session, tmp_path):
    sa = SourceAsset(clip_job_id=1); session.add(sa); session.commit()
    clip = Clip(source_asset_id=sa.id, status="ready", storage_uri=None,
                created_at="2026-07-10T00:00:00Z"); session.add(clip); session.commit()
    client = _client(session, Settings(media_dir=str(tmp_path / "media")))
    assert client.get(f"/media/{clip.id}").status_code == 404


def test_media_404_on_traversal_outside_media_dir(session, tmp_path):
    outside = tmp_path / "secret.txt"; outside.write_text("nope")
    sa = SourceAsset(clip_job_id=1); session.add(sa); session.commit()
    clip = Clip(source_asset_id=sa.id, status="ready", storage_uri=str(outside),
                created_at="2026-07-10T00:00:00Z"); session.add(clip); session.commit()
    (tmp_path / "media").mkdir()
    client = _client(session, Settings(media_dir=str(tmp_path / "media")))
    assert client.get(f"/media/{clip.id}").status_code == 404
