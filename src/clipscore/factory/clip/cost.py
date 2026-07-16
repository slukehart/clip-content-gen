"""Credit accounting for the B5 monthly cap. Vizard bills 1 credit = 1 minute
of SOURCE video, so the cap is denominated in credits (not USD, which is
plan-dependent and defaults to 0.0). `month_credits_used` sums the REAL
`creditsUsed` persisted on completed jobs this ET month; `est_credits`
converts an operator-entered source length (minutes) into a pre-flight
estimate. Lives in factory/ so produce.py needs no web import."""
from sqlalchemy import select

from clipscore.db.models import ClipJob
from clipscore.time import et_month_bounds_utc


def est_credits(minutes: int | None) -> int:
    """Pre-flight credit estimate from an operator-entered source length."""
    return int(minutes) if minutes else 0


def month_credits_used(session, now=None) -> int:
    """Sum of actual `credits_used` across clip_jobs created in the current
    ET calendar month. Jobs that have not yet run (credits_used IS NULL) add
    nothing."""
    start, nxt = et_month_bounds_utc(now)
    rows = session.execute(
        select(ClipJob.credits_used).where(
            ClipJob.created_at >= start, ClipJob.created_at < nxt
        )
    ).scalars().all()
    return int(sum(c or 0 for c in rows))
