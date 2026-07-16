import pytest
from sqlalchemy.exc import IntegrityError

from clipscore.db.models import ClipJob, ClipMatch


def test_clip_job_has_est_minutes_and_credits_used(session):
    job = ClipJob(campaign_id="c1", source_type="passthrough", source_ref="u",
                  status="queued", est_minutes=14, credits_used=None, created_at="2026-07-15T00:00:00Z")
    session.add(job)
    session.commit()
    assert job.est_minutes == 14 and job.credits_used is None


def test_clip_matches_unique_clip_campaign(session):
    session.add(ClipMatch(clip_id=1, campaign_id="c1", rank=1))
    session.commit()
    session.add(ClipMatch(clip_id=1, campaign_id="c1", rank=1))
    with pytest.raises(IntegrityError):
        session.commit()
