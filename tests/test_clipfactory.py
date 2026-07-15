from sqlalchemy import select
from clipscore.db.models import ClipJob, SourceAsset, Clip, Campaign
from clipscore.jobs import clipfactory
from clipscore.factory.clip.base import BaseClipEngine, FakeClipEngine
from clipscore.factory.acquire.base import BaseAcquirer, AcquisitionResult
from clipscore.config import Settings
from clipscore.time import utcnow_iso

def _settings(tmp_path): return Settings(_env_file=None, media_dir=str(tmp_path))

def test_create_clip_job_from_content_bank(session):
    now = utcnow_iso()
    session.add(Campaign(id="c1", source="cr", external_id="e1", status="active",
                         first_seen_at=now, last_seen_at=now,
                         content_bank_url="https://drive.google.com/uc?id=A")); session.commit()
    j = clipfactory.create_clip_job(session, "c1", Settings(_env_file=None))
    assert j.status == "queued" and j.source_type == "campaign_provided"
    assert j.source_ref == "https://drive.google.com/uc?id=A"

def test_create_clip_job_unknown_campaign_raises(session):
    import pytest
    with pytest.raises(ValueError):
        clipfactory.create_clip_job(session, "nope", Settings(_env_file=None))

def test_process_advances_queued_through_matched(session, tmp_path):
    now = utcnow_iso()
    session.add(Campaign(id="c1", source="cr", external_id="e1", status="active",
                         access_status="ingestable", campaign_type="clipping",
                         first_seen_at=now, last_seen_at=now,
                         target_platforms='["tiktok"]', target_creator='["@diego"]')); session.commit()
    j = ClipJob(campaign_id="c1", source_type="campaign_provided", source_ref="ref",
                status="queued", created_at=now); session.add(j); session.commit()
    # fake acquirer writes a file + sets acquired; fake engine produces a clip
    class _Acq(BaseAcquirer):
        source_type = "campaign_provided"; requires_authorization = False
        def acquire(self, source_ref, dest_path, **kw):
            import os; os.makedirs(dest_path.rsplit("/",1)[0], exist_ok=True)
            open(dest_path + ".mp4","wb").write(b"x"*30)
            return AcquisitionResult(status="acquired", storage_uri=dest_path+".mp4", bytes=30,
                                     creator="diego", platform="campaign_provided", duration_s=90)
    reg = {"campaign_provided": _Acq()}
    s = _settings(tmp_path)
    # queued -> acquired
    clipfactory.process_clip_jobs(session, s, registry=reg, engine=FakeClipEngine())
    # acquired -> produced
    clipfactory.process_clip_jobs(session, s, registry=reg, engine=FakeClipEngine())
    # produced -> matched (+captions)
    clipfactory.process_clip_jobs(session, s, registry=reg, engine=FakeClipEngine())
    session.refresh(j)
    assert j.status == "matched"
    assert session.execute(select(Clip)).scalars().first().status == "ready"

def test_matched_job_is_not_repicked(session, tmp_path):
    now = utcnow_iso()
    j = ClipJob(campaign_id="c1", source_type="url", source_ref="u", status="matched", created_at=now)
    session.add(j); session.commit()
    res = clipfactory.process_clip_jobs(session, _settings(tmp_path), engine=FakeClipEngine())
    assert res["advanced"] == 0

def test_produced_job_skips_caption_when_matching_fails(session, tmp_path, monkeypatch):
    now = utcnow_iso()
    session.add(Campaign(id="c1", source="cr", external_id="e1", status="active",
                         access_status="ingestable", campaign_type="clipping",
                         first_seen_at=now, last_seen_at=now,
                         target_platforms='["tiktok"]', target_creator='["@diego"]')); session.commit()
    j = ClipJob(campaign_id="c1", source_type="campaign_provided", source_ref="ref",
                status="produced", created_at=now); session.add(j); session.commit()
    sa = SourceAsset(clip_job_id=j.id, storage_uri="x.mp4", downloaded_at=now)
    session.add(sa); session.commit()
    clip = Clip(source_asset_id=sa.id, platform_variant="tiktok", engine="fake",
                status="produced", created_at=now)
    session.add(clip); session.commit()

    def _fake_run_matching(session, clip_job, *, now=None):
        clip_job.status = "failed"
        clip_job.error = "matching guard fired"
        session.commit()
        return clip_job

    caption_calls = []

    def _fake_run_caption(session, clip_job, settings, *, llm=None):
        caption_calls.append(clip_job.id)
        return clip_job

    monkeypatch.setattr(clipfactory, "run_matching", _fake_run_matching)
    monkeypatch.setattr(clipfactory, "run_caption", _fake_run_caption)

    clipfactory.process_clip_jobs(session, _settings(tmp_path))

    session.refresh(j)
    session.refresh(clip)
    assert j.status == "failed"
    assert caption_calls == []
    assert clip.status == "produced"


def test_stage_crash_marks_failed_never_raises(session, tmp_path):
    now = utcnow_iso()
    j = ClipJob(campaign_id="c1", source_type="campaign_provided", source_ref="ref",
                status="acquired", created_at=now); session.add(j); session.commit()
    class Boom(BaseClipEngine):
        name="boom"
        def produce(self, *a, **k): raise RuntimeError("boom")
    clipfactory.process_clip_jobs(session, _settings(tmp_path), engine=Boom())
    session.refresh(j)
    assert j.status == "failed" and j.error
