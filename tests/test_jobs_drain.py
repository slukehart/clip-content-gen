from clipscore.config import Settings
from clipscore.db.models import Campaign, ClipJob, SourceAsset
from clipscore.factory.acquire.registry import build_registry
from clipscore.factory.clip.base import FakeClipEngine
from clipscore.jobs.drain import drain_clip_jobs


def test_drain_drives_queued_job_to_terminal(session):
    session.add(Campaign(id="c1", source="manual", external_id="c1", campaign_type="clipping",
                         status="active", access_status="ingestable", target_creator="@x",
                         first_seen_at="2026-07-01T00:00:00Z", last_seen_at="2026-07-01T00:00:00Z"))
    session.add(ClipJob(campaign_id="c1", source_type="passthrough",
                        source_ref="https://youtu.be/abc", status="queued",
                        created_at="2026-07-15T00:00:00Z"))
    session.commit()
    result = drain_clip_jobs(session, Settings(_env_file=None, clip_engine="fake"),
                             engine=FakeClipEngine(), registry=build_registry())
    assert result["passes"] >= 3           # queued->acquired->produced->matched
    job = session.query(ClipJob).one()
    assert job.status in ("matched", "failed", "blocked")
    assert job.status == "matched"


def test_drain_once_single_pass(session):
    session.add(ClipJob(campaign_id="c1", source_type="passthrough",
                        source_ref="https://youtu.be/abc", status="queued",
                        created_at="2026-07-15T00:00:00Z"))
    session.commit()
    result = drain_clip_jobs(session, Settings(_env_file=None, clip_engine="fake"),
                             engine=FakeClipEngine(), registry=build_registry(), once=True)
    assert result["passes"] == 1
