from clipscore.config import Settings
from clipscore.db.models import Campaign, Clip, ClipJob, SourceAsset
from clipscore.factory.clip.base import BaseClipEngine, ClipSpec, ProducedClip
from clipscore.factory.clip.produce import run_clipping
from clipscore.time import utcnow_iso


def _seed(session, *, est_minutes, credits_used_prior=0):
    # run_clipping calls month_credits_used(session) with the REAL now, so the
    # current-month rows must be stamped with utcnow_iso() (NOT a hardcoded
    # date) or the test breaks outside July 2026.
    now = utcnow_iso()
    session.add(Campaign(id="c1", source="manual", external_id="c1",
                         campaign_type="clipping", status="active",
                         access_status="ingestable", first_seen_at=now,
                         last_seen_at=now))
    if credits_used_prior:
        session.add(ClipJob(campaign_id="c1", source_type="passthrough", source_ref="u",
                            status="produced", credits_used=credits_used_prior,
                            created_at=now))
    job = ClipJob(campaign_id="c1", source_type="passthrough", source_ref="u",
                  status="acquired", est_minutes=est_minutes, created_at=now)
    session.add(job)
    session.flush()
    session.add(SourceAsset(clip_job_id=job.id, source_url="https://youtu.be/abc",
                            platform="passthrough", storage_uri=None))
    session.commit()
    return job


class _BoomEngine(BaseClipEngine):
    name = "boom"
    def produce(self, source_uri, spec, *, dest_dir):
        raise AssertionError("engine must NOT be called when over the cap")


class _StubEngine(BaseClipEngine):
    name = "stub"
    def produce(self, source_uri, spec, *, dest_dir):
        return [ProducedClip(storage_uri=f"{dest_dir}/clip-0.mp4", duration_s=30,
                             engine="stub", engine_clip_id="s0", cost_usd=0.0, credits_used=14)]


def test_over_cap_blocks_without_calling_engine(session):
    job = _seed(session, est_minutes=20)
    settings = Settings(_env_file=None, monthly_cap_credits=10)
    run_clipping(session, job, settings, engine=_BoomEngine())
    session.refresh(job)
    assert job.status == "blocked"
    assert session.query(Clip).count() == 0


def test_projection_includes_prior_spend(session):
    job = _seed(session, est_minutes=5, credits_used_prior=8)  # 8 (spent) + 5 (est) = 13 > 10
    settings = Settings(_env_file=None, monthly_cap_credits=10)
    run_clipping(session, job, settings, engine=_BoomEngine())
    session.refresh(job)
    assert job.status == "blocked"


def test_under_cap_runs_and_persists_credits_used(session):
    job = _seed(session, est_minutes=5)
    settings = Settings(_env_file=None, monthly_cap_credits=0)  # uncapped
    run_clipping(session, job, settings, engine=_StubEngine())
    session.refresh(job)
    assert job.status == "produced"
    assert job.credits_used == 14
