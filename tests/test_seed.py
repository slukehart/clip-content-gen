from clipscore.seed import seed_all
from clipscore.db.models import PlatformTrust, NicheBaseline

def test_seed_is_idempotent(session):
    seed_all(session)
    seed_all(session)  # second call must not duplicate or error
    assert session.get(PlatformTrust, "contentrewards").default_fee_pct == 0.10
    assert session.get(NicheBaseline, "gaming").e_views_median == 8000
    assert session.query(NicheBaseline).count() == 9
