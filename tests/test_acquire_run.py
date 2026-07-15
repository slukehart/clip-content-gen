import uuid
import httpx
from clipscore.db.models import ClipJob, SourceAsset, Campaign
from clipscore.factory.acquire import run, registry
from clipscore.factory.acquire.base import AcquisitionResult, BaseAcquirer
from clipscore.config import Settings
from clipscore.time import utcnow_iso
from sqlalchemy import select

def _settings(tmp_path):
    return Settings(_env_file=None, media_dir=str(tmp_path), max_media_gb=50.0)

def _job(session, **kw):
    now = utcnow_iso()
    defaults = dict(campaign_id="c1", source_type="campaign_provided",
                    source_ref="https://drive.google.com/uc?export=download&id=A",
                    status="queued", created_at=now)
    defaults.update(kw)
    j = ClipJob(**defaults); session.add(j); session.commit()
    return j

class _FakeAcquirer(BaseAcquirer):
    source_type = "campaign_provided"
    requires_authorization = False
    def __init__(self, result): self._result = result
    def acquire(self, source_ref, dest_path, **kw):
        # simulate a real acquirer writing the file
        if self._result.status == "acquired":
            import os
            os.makedirs(os.path.dirname(dest_path + ".mp4"), exist_ok=True)
            open(dest_path + ".mp4", "wb").write(b"x" * 42)
            self._result.storage_uri = dest_path + ".mp4"; self._result.bytes = 42
        return self._result

def _reg(acq): return {acq.source_type: acq}

def test_acquired_writes_source_asset_and_sets_status(session, tmp_path):
    j = _job(session)
    reg = _reg(_FakeAcquirer(AcquisitionResult(status="acquired", platform="campaign_provided")))
    run.acquire_job(session, j, _settings(tmp_path), registry=reg)
    assert j.status == "acquired"
    sa = session.execute(select(SourceAsset)).scalars().one()
    assert sa.clip_job_id == j.id and sa.bytes == 42 and sa.storage_uri.endswith(".mp4")

def test_blocked_maps_to_failed_no_source_asset(session, tmp_path):
    j = _job(session)
    reg = _reg(_FakeAcquirer(AcquisitionResult(status="blocked", error="blocked_403")))
    run.acquire_job(session, j, _settings(tmp_path), registry=reg)
    assert j.status == "failed" and j.error == "blocked_403"
    assert session.execute(select(SourceAsset)).scalars().first() is None

def test_manual_maps_to_failed_with_reason(session, tmp_path):
    j = _job(session)
    reg = _reg(_FakeAcquirer(AcquisitionResult(status="manual", error="folder_or_unsupported_share_link")))
    run.acquire_job(session, j, _settings(tmp_path), registry=reg)
    assert j.status == "failed" and j.error == "folder_or_unsupported_share_link"

def test_vod_without_active_campaign_is_unauthorized(session, tmp_path):
    # requires_authorization acquirer + campaign_id that doesn't resolve to an active campaign
    j = _job(session, source_type="youtube", source_ref="https://youtube.com/watch?v=x",
             campaign_id="missing")
    class _VodAcq(BaseAcquirer):
        source_type = "youtube"; requires_authorization = True
        def acquire(self, *a, **k): raise AssertionError("must not download when unauthorized")
    run.acquire_job(session, j, _settings(tmp_path), registry={"youtube": _VodAcq()})
    assert j.status == "failed" and j.error == "unauthorized"

def test_vod_with_active_campaign_records_authorizing_id(session, tmp_path):
    session.add(Campaign(id="c1", source="cr", external_id="e1", status="active",
                         first_seen_at=utcnow_iso(), last_seen_at=utcnow_iso())); session.commit()
    j = _job(session, source_type="youtube", source_ref="https://youtube.com/watch?v=x")
    reg = _reg(_FakeAcquirer(AcquisitionResult(status="acquired", platform="youtube")))
    reg["youtube"] = reg.pop("campaign_provided"); reg["youtube"].source_type = "youtube"
    reg["youtube"].requires_authorization = True
    run.acquire_job(session, j, _settings(tmp_path), registry=reg)
    sa = session.execute(select(SourceAsset)).scalars().one()
    assert sa.authorizing_campaign_id == "c1"

def test_dedup_reuses_existing_file_without_calling_acquirer(session, tmp_path):
    from clipscore.factory.acquire import storage
    j = _job(session)
    stem = storage.stem_key("campaign_provided", j.source_ref)
    existing = tmp_path / f"{stem}.mp4"; existing.parent.mkdir(parents=True); existing.write_bytes(b"y" * 7)
    # A prior SourceAsset must vouch for the file on disk for dedup to trust
    # it (an orphan file with no matching row is re-acquired -- see
    # test_orphan_file_without_source_asset_row_is_reacquired).
    session.add(SourceAsset(clip_job_id=0, storage_uri=str(existing), bytes=7,
                             downloaded_at=utcnow_iso())); session.commit()
    class _Boom(BaseAcquirer):
        source_type = "campaign_provided"; requires_authorization = False
        def acquire(self, *a, **k): raise AssertionError("dedup must skip the download")
    run.acquire_job(session, j, _settings(tmp_path), registry={"campaign_provided": _Boom()})
    assert j.status == "acquired"
    sa = session.execute(
        select(SourceAsset).where(SourceAsset.clip_job_id == j.id)
    ).scalars().one()
    assert sa.storage_uri == str(existing)

def test_dedup_preserves_platform_creator_duration(session, tmp_path):
    # First job acquires fresh, recording platform/creator/duration_s.
    j1 = _job(session)
    reg = _reg(_FakeAcquirer(AcquisitionResult(
        status="acquired", platform="youtube", creator="alice", duration_s=99)))
    run.acquire_job(session, j1, _settings(tmp_path), registry=reg)
    sa1 = session.execute(select(SourceAsset)).scalars().one()
    assert sa1.platform == "youtube" and sa1.creator == "alice" and sa1.duration_s == 99

    # Second job with the same source_ref dedups against the file on disk
    # written by the first job -- it must NOT call the acquirer, and its
    # SourceAsset must carry the SAME platform/creator/duration_s (not NULL).
    j2 = _job(session)
    class _Boom(BaseAcquirer):
        source_type = "campaign_provided"; requires_authorization = False
        def acquire(self, *a, **k): raise AssertionError("dedup must skip the download")
    run.acquire_job(session, j2, _settings(tmp_path), registry={"campaign_provided": _Boom()})
    assert j2.status == "acquired"
    sa2 = session.execute(
        select(SourceAsset).where(SourceAsset.clip_job_id == j2.id)
    ).scalars().one()
    assert sa2.platform == "youtube" and sa2.creator == "alice" and sa2.duration_s == 99


def test_orphan_file_without_source_asset_row_is_reacquired(session, tmp_path):
    # A file exists on disk at the content-addressed path (e.g. a prior
    # download whose SourceAsset write failed) but there is NO SourceAsset
    # row referencing it. This must NOT be trusted as a dedup hit -- the
    # acquirer must be called to (re)acquire it properly.
    from clipscore.factory.acquire import storage
    j = _job(session)
    stem = storage.stem_key("campaign_provided", j.source_ref)
    orphan = tmp_path / f"{stem}.mp4"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"orphan" * 3)

    reg = _reg(_FakeAcquirer(AcquisitionResult(status="acquired", platform="campaign_provided")))
    run.acquire_job(session, j, _settings(tmp_path), registry=reg)
    assert j.status == "acquired"
    sa = session.execute(select(SourceAsset)).scalars().one()
    # The fake acquirer writes its own file at dest_path + ".mp4" (same path
    # as the orphan) with bytes == 42, proving the acquirer was actually
    # invoked rather than the orphan being trusted as-is (orphan was 18 bytes).
    assert sa.bytes == 42


def test_inner_commit_crash_rolls_back_before_fallback_and_still_persists_failed(session, tmp_path, monkeypatch):
    # Simulate the acquired-branch commit (run.py's `_acquire_job_inner`,
    # after `session.add(SourceAsset(...))` is pending) raising -- e.g.
    # because the session was poisoned by a prior flush error. The outer
    # except must roll back that pending SourceAsset before attempting the
    # fallback failed-status commit.
    #
    # This is only a real test of the rollback if there's something pending
    # for rollback to discard. WITH `session.rollback()` (current code): the
    # pending SourceAsset add is discarded, then the fallback `_fail` commit
    # persists only the ClipJob as failed -- zero SourceAsset rows. WITHOUT
    # it: the pending SourceAsset add is still attached to the session, so
    # the fallback commit (our flaky_commit's second call, which delegates
    # to the real commit) flushes it right along with the ClipJob update,
    # leaving an orphan SourceAsset row behind. So asserting "zero
    # SourceAsset rows" is what actually distinguishes the two behaviors --
    # the ClipJob-is-failed assertion alone holds either way.
    from clipscore.db.models import ClipJob
    j = _job(session)
    reg = _reg(_FakeAcquirer(AcquisitionResult(status="acquired", platform="campaign_provided")))

    orig_commit = session.commit
    calls = {"n": 0}

    def flaky_commit():
        calls["n"] += 1
        if calls["n"] == 1:
            # Fires on the acquired-branch commit in run.py, i.e. AFTER
            # `session.add(SourceAsset(...))` has made it pending.
            raise RuntimeError("commit boom")
        return orig_commit()

    monkeypatch.setattr(session, "commit", flaky_commit)

    j2 = run.acquire_job(session, j, _settings(tmp_path), registry=reg)
    assert j2.status == "failed" and j2.error == "acquire_crashed"

    monkeypatch.undo()
    session.expire_all()
    reloaded = session.get(ClipJob, j.id)
    assert reloaded.status == "failed" and reloaded.error == "acquire_crashed"

    # Discriminating assertion: the pending SourceAsset from the crashed
    # acquired-branch commit must NOT have survived. Without
    # `session.rollback()` in the outer except, this row would exist
    # (persisted as an orphan by the fallback commit).
    assert session.execute(select(SourceAsset)).scalars().all() == []


def test_unknown_source_type_fails(session, tmp_path):
    j = _job(session, source_type="myspace")
    run.acquire_job(session, j, _settings(tmp_path), registry={})
    assert j.status == "failed" and j.error == "unknown_source_type"

def test_acquirer_crash_never_raises_and_marks_failed(session, tmp_path):
    j = _job(session)
    class _Crash(BaseAcquirer):
        source_type = "campaign_provided"; requires_authorization = False
        def acquire(self, *a, **k): raise RuntimeError("boom")
    j2 = run.acquire_job(session, j, _settings(tmp_path), registry={"campaign_provided": _Crash()})
    assert j2.status == "failed" and j2.error  # did not raise; error recorded

def test_disk_guard_refuses_when_over_budget(session, tmp_path):
    (tmp_path / "big").mkdir(); (tmp_path / "big" / "f").write_bytes(b"x" * 2000)
    s = Settings(_env_file=None, media_dir=str(tmp_path), max_media_gb=0.000001)  # ~1KB budget
    j = _job(session)
    class _Boom(BaseAcquirer):
        source_type = "campaign_provided"; requires_authorization = False
        def acquire(self, *a, **k): raise AssertionError("must not download over budget")
    run.acquire_job(session, j, s, registry={"campaign_provided": _Boom()})
    assert j.status == "failed" and j.error == "disk_guard"
