import os, uuid
from sqlalchemy import select
from clipscore.db.models import ClipJob, SourceAsset, Clip, Campaign
from clipscore.factory.clip.produce import run_clipping
from clipscore.factory.clip.base import FakeClipEngine, BaseClipEngine
from clipscore.config import Settings
from clipscore.time import utcnow_iso

def _setup(session, tmp_path, **camp):
    now = utcnow_iso()
    c = Campaign(id="c1", source="cr", external_id="e1", status="active",
                 first_seen_at=now, last_seen_at=now, target_platforms='["tiktok"]', **camp)
    j = ClipJob(campaign_id="c1", source_type="campaign_provided", source_ref="ref",
                status="acquired", created_at=now)
    session.add_all([c, j]); session.commit()
    src = tmp_path / "src.mp4"; src.write_bytes(b"x" * 50)
    sa = SourceAsset(clip_job_id=j.id, creator="diego", platform="campaign_provided",
                     source_url="ref", storage_uri=str(src), duration_s=600, downloaded_at=now)
    session.add(sa); session.commit()
    return j, src

def _settings(tmp_path): return Settings(_env_file=None, media_dir=str(tmp_path))

def test_clipping_writes_clips_and_deletes_source(session, tmp_path):
    j, src = _setup(session, tmp_path)
    run_clipping(session, j, _settings(tmp_path), engine=FakeClipEngine())
    assert j.status == "produced"
    clips = session.execute(select(Clip)).scalars().all()
    assert len(clips) == 1 and clips[0].platform_variant == "tiktok" and clips[0].status == "produced"
    assert not src.exists()  # immediate post-clip retention
    sa = session.execute(select(SourceAsset)).scalars().one()
    assert sa.storage_uri is None

def test_clipping_engine_error_marks_failed_never_raises(session, tmp_path):
    j, src = _setup(session, tmp_path)
    class Boom(BaseClipEngine):
        name = "boom"
        def produce(self, *a, **k): raise RuntimeError("engine down")
    out = run_clipping(session, j, _settings(tmp_path), engine=Boom())
    assert out.status == "failed" and out.error
    assert src.exists()  # source not deleted on failure
