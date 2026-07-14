from sqlalchemy import select
from clipscore.db.models import NicheBaseline
from clipscore.seed import seed_all, NICHE_BASELINE_SEED
from clipscore.config import Settings

REAL_NICHES = {"entertainment", "technology", "product", "music",
               "logo", "personal brand", "slideshow", "gaming", "other"}

def test_seed_loads_real_categories(session):
    seed_all(session)
    got = {n for (n,) in session.execute(select(NicheBaseline.niche)).all()}
    assert got == REAL_NICHES

def test_other_partition_present(session):
    seed_all(session)
    assert session.get(NicheBaseline, "other") is not None

def test_baselines_uniform_guesses(session):
    seed_all(session)
    rows = session.execute(select(NicheBaseline)).scalars().all()
    assert len({r.e_views_median for r in rows}) == 1
    assert len({r.p_threshold for r in rows}) == 1

def test_reseed_prunes_stale_rows(session):
    # a stale topical niche from the old seed must be removed on re-seed
    session.add(NicheBaseline(niche="crypto", e_views_median=6000, p_threshold=0.5))
    session.commit()
    seed_all(session)
    assert session.get(NicheBaseline, "crypto") is None

def test_seed_idempotent(session):
    seed_all(session); seed_all(session)
    rows = session.execute(select(NicheBaseline)).scalars().all()
    assert len(rows) == len(REAL_NICHES)

def test_retention_config_default():
    assert Settings().raw_retention_days == 14
