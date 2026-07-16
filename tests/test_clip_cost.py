from datetime import datetime, timezone

from clipscore.db.models import ClipJob
from clipscore.factory.clip.cost import est_credits, month_credits_used


def test_est_credits():
    assert est_credits(14) == 14
    assert est_credits(0) == 0
    assert est_credits(None) == 0


def test_month_credits_used_sums_current_et_month(session):
    session.add_all([
        ClipJob(campaign_id="c", source_type="passthrough", source_ref="u",
                status="produced", credits_used=14, created_at="2026-07-10T12:00:00Z"),
        ClipJob(campaign_id="c", source_type="passthrough", source_ref="u",
                status="produced", credits_used=6, created_at="2026-07-20T12:00:00Z"),
        ClipJob(campaign_id="c", source_type="passthrough", source_ref="u",
                status="produced", credits_used=99, created_at="2026-06-15T12:00:00Z"),  # prior month
        ClipJob(campaign_id="c", source_type="passthrough", source_ref="u",
                status="queued", credits_used=None, created_at="2026-07-11T12:00:00Z"),  # no credits yet
    ])
    session.commit()
    now = datetime(2026, 7, 25, tzinfo=timezone.utc)
    assert month_credits_used(session, now=now) == 20
