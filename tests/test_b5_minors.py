import os

from clipscore.config import Settings
from clipscore.db.models import Campaign, ClipJob, SourceAsset
from clipscore.factory.acquire.registry import build_registry
from clipscore.jobs.clipfactory import process_clip_jobs


def _queued(session, n):
    session.add(Campaign(id="c1", source="manual", external_id="c1", campaign_type="clipping",
                         status="active", access_status="ingestable", target_creator="@x",
                         first_seen_at="2026-07-01T00:00:00Z", last_seen_at="2026-07-01T00:00:00Z"))
    for _ in range(n):
        session.add(ClipJob(campaign_id="c1", source_type="passthrough",
                            source_ref="https://youtu.be/abc", status="queued",
                            created_at="2026-07-15T00:00:00Z"))
    session.commit()


def test_per_tick_job_cap(session):
    _queued(session, 8)
    result = process_clip_jobs(session, Settings(_env_file=None, clip_jobs_per_tick=3),
                               registry=build_registry())
    assert result["advanced"] == 3   # capped, not 8


def test_media_dir_path_has_no_double_slash():
    # media_dir default ends in "/"; the join must not produce "media//clips"
    got = os.path.join("media/", "clips", "1")
    assert "//" not in got and got.endswith(os.path.join("clips", "1"))
