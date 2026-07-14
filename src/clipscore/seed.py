from sqlalchemy import select
from sqlalchemy.orm import Session
from clipscore.db.models import PlatformTrust, NicheBaseline

# NOTE: starting estimates — verify against current platform terms.
PLATFORM_TRUST_SEED = [
    dict(source="contentrewards", trust_score=0.80, default_fee_pct=0.10,
         notes="Whop rails; reflects botting-flag/threshold-ban friction. VERIFY."),
]
# Real source categories (slugified: category.strip().lower()). Uniform placeholder
# guesses — within-niche ranking is partition-agnostic and cross-niche is not
# trustworthy in v1, so differentiated per-niche guesses would be guess-on-guess.
# null category normalizes to niche=None, which scoring maps to "other".
_E_VIEWS_GUESS = 8000
_P_THRESHOLD_GUESS = 0.55
NICHE_BASELINE_SEED = [
    dict(niche=n, e_views_median=_E_VIEWS_GUESS, p_threshold=_P_THRESHOLD_GUESS)
    for n in ("entertainment", "technology", "product", "music",
              "logo", "personal brand", "slideshow", "gaming", "other")
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
    canonical = {row["niche"] for row in NICHE_BASELINE_SEED}
    for existing in session.execute(select(NicheBaseline)).scalars().all():
        if existing.niche not in canonical:
            session.delete(existing)
    session.commit()
