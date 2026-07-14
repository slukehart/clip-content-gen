"""budget_health from a campaign's snapshot series (IMPLEMENTATION_PLAN.md:204-208).
OBSERVED signal. Uses ONLY the latest snapshot's epoch so a budget top-up (which
bumps the epoch at ingest) never lets burn be measured across the reset."""
from datetime import datetime, timedelta


def _parse(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")


def budget_health(snapshots, now_iso: str, neutral: float = 0.7) -> float:
    snaps = list(snapshots)
    if not snaps:
        return neutral
    latest = max(snaps, key=lambda s: s.captured_at)
    epoch = latest.epoch
    in_epoch = [s for s in snaps if s.epoch == epoch]
    if len(in_epoch) < 2:
        return neutral
    now = _parse(now_iso)
    cutoff = now - timedelta(hours=48)
    older = [s for s in in_epoch if _parse(s.captured_at) <= cutoff]
    if not older:
        return neutral
    then = max(older, key=lambda s: s.captured_at)   # closest to now-48h from below
    r_then, r_now = then.budget_remaining_usd, latest.budget_remaining_usd
    if r_then is None or r_now is None:
        return neutral
    daily_burn = (r_then - r_now) / 2.0
    if daily_burn <= 0:
        return 1.0
    days_left = r_now / daily_burn
    return min(1.0, days_left / 7)
