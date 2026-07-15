import os
from datetime import datetime, timedelta, timezone
from clipscore.db.models import ClipJob, SourceAsset
from clipscore.factory.acquire import run
from clipscore.config import Settings
from clipscore.time import utcnow_iso

def _iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def test_retention_deletes_old_source_files(session, tmp_path):
    old_f = tmp_path / "old.mp4"; old_f.write_bytes(b"x" * 10)
    new_f = tmp_path / "new.mp4"; new_f.write_bytes(b"y" * 10)
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    old = _iso(now - timedelta(days=30)); recent = _iso(now - timedelta(days=1))
    session.add_all([
        SourceAsset(clip_job_id=1, storage_uri=str(old_f), bytes=10, downloaded_at=old),
        SourceAsset(clip_job_id=2, storage_uri=str(new_f), bytes=10, downloaded_at=recent),
    ]); session.commit()
    s = Settings(_env_file=None, media_dir=str(tmp_path), raw_retention_days=14)
    res = run.sweep_retention(session, s, now=_iso(now))
    assert res["deleted"] == 1
    assert not old_f.exists() and new_f.exists()  # only the aged file removed
