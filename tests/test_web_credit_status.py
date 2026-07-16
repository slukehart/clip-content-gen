from clipscore.config import Settings
from clipscore.db.models import ClipJob
from clipscore.time import utcnow_iso
from clipscore.web.queries import monthly_credit_status


def _job(credits, now):
    return ClipJob(campaign_id="c", source_type="passthrough", source_ref="u",
                   status="produced", credits_used=credits, created_at=now)


def test_credit_status_capped(session):
    now = utcnow_iso()
    session.add_all([_job(300, now), _job(200, now)])
    session.commit()
    st = monthly_credit_status(session, Settings(_env_file=None, monthly_cap_credits=1300))
    assert st.used == 500
    assert st.cap == 1300
    assert st.remaining == 800
    assert round(st.pct, 1) == 38.5


def test_credit_status_uncapped(session):
    st = monthly_credit_status(session, Settings(_env_file=None, monthly_cap_credits=0))
    assert st.used == 0
    assert st.cap == 0
    assert st.remaining is None
    assert st.pct is None


def test_credit_status_over_cap_clamps(session):
    now = utcnow_iso()
    session.add_all([_job(900, now), _job(600, now)])  # 1500 > cap 1300
    session.commit()
    st = monthly_credit_status(session, Settings(_env_file=None, monthly_cap_credits=1300))
    assert st.used == 1500
    assert st.remaining == 0        # clamped, never negative
    assert st.pct == 100.0          # clamped at 100
