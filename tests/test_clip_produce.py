import os, uuid
from sqlalchemy import select, text
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
    assert len(clips) == 3
    assert all(c.platform_variant is None for c in clips)
    assert all(c.status == "produced" for c in clips)
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

def test_clipping_commit_failure_never_raises_and_records_failure(session, tmp_path):
    # The clips-write commit inside the worker fails at flush (constraint
    # violation / DB lock / disk-full — simulated here by dropping the clips
    # table so the INSERT errors). In SQLAlchemy 2.0 a failed flush deactivates
    # the transaction, so recording the failure requires session.rollback()
    # FIRST — otherwise the guard's own commit() raises PendingRollbackError
    # and both escapes AND loses the failure record.
    j, src = _setup(session, tmp_path)
    session.execute(text("DROP TABLE clips"))
    session.commit()

    # (a) never raises even though the worker's commit fails hard.
    out = run_clipping(session, j, _settings(tmp_path), engine=FakeClipEngine())
    assert out.status == "failed" and out.error

    # (b) the failure is DURABLY persisted. Rolling back here discards any
    # uncommitted in-memory state, so the re-read reflects only what actually
    # committed: with the guard's rollback() the failed status is persisted
    # ("failed"); without it the failure commit raised PendingRollbackError,
    # nothing committed, and this row is still "acquired" — which is exactly
    # what makes this test discriminate.
    session.rollback()
    session.expire_all()
    fetched = session.get(ClipJob, j.id)
    assert fetched.status == "failed" and fetched.error


def test_run_clipping_passes_source_url_and_writes_platformless_clips(session, tmp_path):
    """Passthrough source (storage_uri=None): engine gets the public URL,
    Clip rows are written with no platform_variant, and no retention delete
    is attempted on a None path."""
    session.add(Campaign(
        id="c1", source="manual", external_id="c1", campaign_type="clipping",
        status="active", first_seen_at="t", last_seen_at="t",
        clip_min_len_s=30, clip_max_len_s=90, target_platforms='["tiktok"]',
    ))
    j = ClipJob(campaign_id="c1", source_type="passthrough",
                source_ref="https://youtu.be/abc", status="acquired",
                created_at="t")
    session.add(j); session.commit()
    session.add(SourceAsset(clip_job_id=j.id, creator="@me",
                            source_url="https://youtu.be/abc",
                            storage_uri=None, downloaded_at="t"))
    session.commit()

    captured = {}
    class _Spy(FakeClipEngine):
        def produce(self, source_uri, spec, *, dest_dir):
            captured["uri"] = source_uri
            return super().produce(source_uri, spec, dest_dir=dest_dir)

    run_clipping(session, j, _settings(tmp_path), engine=_Spy())
    assert captured["uri"] == "https://youtu.be/abc"   # URL, not a local path
    assert j.status == "produced"
    clips = session.query(Clip).all()
    assert clips and all(c.platform_variant is None for c in clips)
