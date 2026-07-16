from datetime import datetime, timezone

from clipscore.config import Settings
from clipscore.db.models import Clip
from clipscore.factory.clip.retention import delete_clip_file, sweep_clip_retention


def _clip(session, path, created_at):
    c = Clip(source_asset_id=1, storage_uri=str(path), status="ready", created_at=created_at)
    session.add(c)
    session.commit()
    return c


def test_delete_clip_file_removes_and_nulls(session, tmp_path):
    f = tmp_path / "clip-0.mp4"
    f.write_bytes(b"x")
    c = _clip(session, f, "2026-07-15T00:00:00Z")
    assert delete_clip_file(c) is True
    assert not f.exists() and c.storage_uri is None


def test_delete_clip_file_missing_is_safe(session, tmp_path):
    c = _clip(session, tmp_path / "gone.mp4", "2026-07-15T00:00:00Z")
    assert delete_clip_file(c) is False  # no crash on a missing file


def test_sweep_prunes_only_aged_clips(session, tmp_path):
    old = tmp_path / "old.mp4"; old.write_bytes(b"x")
    new = tmp_path / "new.mp4"; new.write_bytes(b"x")
    _clip(session, old, "2026-06-01T00:00:00Z")   # >14d before now
    _clip(session, new, "2026-07-14T00:00:00Z")   # within 14d
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    result = sweep_clip_retention(session, Settings(_env_file=None, clip_retention_days=14), now=now)
    assert result == {"pruned": 1}
    assert not old.exists() and new.exists()
