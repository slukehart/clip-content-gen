from sqlalchemy.orm import Session
from clipscore.db.models import PlatformTrust, NicheBaseline

# NOTE: starting estimates — verify against current platform terms.
PLATFORM_TRUST_SEED = [
    dict(source="contentrewards", trust_score=0.80, default_fee_pct=0.10,
         notes="Whop rails; reflects botting-flag/threshold-ban friction. VERIFY."),
]
NICHE_BASELINE_SEED = [
    dict(niche="gaming", e_views_median=10000, p_threshold=0.6),
    dict(niche="entertainment", e_views_median=12000, p_threshold=0.65),
    dict(niche="podcast", e_views_median=7000, p_threshold=0.55),
    dict(niche="finance", e_views_median=5000, p_threshold=0.5),
    dict(niche="fitness", e_views_median=8000, p_threshold=0.6),
    dict(niche="tech", e_views_median=6000, p_threshold=0.55),
    dict(niche="crypto", e_views_median=6000, p_threshold=0.5),
    dict(niche="other", e_views_median=5000, p_threshold=0.5),
]

def seed_all(session: Session) -> None:
    for row in PLATFORM_TRUST_SEED:
        existing = session.get(PlatformTrust, row["source"])
        if existing is None:
            session.add(PlatformTrust(**row))
        else:
            for k, v in row.items():
                setattr(existing, k, v)
    for row in NICHE_BASELINE_SEED:
        existing = session.get(NicheBaseline, row["niche"])
        if existing is None:
            session.add(NicheBaseline(**row))
        else:
            for k, v in row.items():
                setattr(existing, k, v)
    session.commit()
