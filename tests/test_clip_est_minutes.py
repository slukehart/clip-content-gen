from clipscore.config import Settings
from clipscore.db.models import Campaign, ClipJob
from clipscore.jobs.clipfactory import create_clip_job


def test_create_clip_job_persists_est_minutes(session):
    session.add(Campaign(id="c1", source="manual", external_id="c1", campaign_type="clipping",
                         status="active", access_status="ingestable", content_bank_url="https://youtu.be/abc",
                         first_seen_at="2026-07-01T00:00:00Z", last_seen_at="2026-07-01T00:00:00Z"))
    session.commit()
    job = create_clip_job(session, "c1", Settings(_env_file=None), est_minutes=14)
    assert job.est_minutes == 14
