from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from clipscore.scoring.budget import budget_health

def iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)
NOW_ISO = iso(NOW)

@dataclass
class Snap:
    epoch: int
    budget_remaining_usd: float | None
    captured_at: str

def test_none_snapshots_neutral():
    assert budget_health([], NOW_ISO) == 0.7

def test_single_snapshot_neutral():
    assert budget_health([Snap(0, 500.0, iso(NOW))], NOW_ISO) == 0.7

def test_no_snapshot_at_least_48h_old_neutral():
    # two snapshots but both younger than 48h -> can't measure burn
    snaps = [Snap(0, 500.0, iso(NOW - timedelta(hours=10))),
             Snap(0, 450.0, iso(NOW))]
    assert budget_health(snaps, NOW_ISO) == 0.7

def test_healthy_burn():
    # remaining fell 700->500 over ~48h -> daily_burn=100/day, days_left=5 -> 5/7
    snaps = [Snap(0, 700.0, iso(NOW - timedelta(hours=48))),
             Snap(0, 500.0, iso(NOW))]
    assert budget_health(snaps, NOW_ISO) == round(5/7, 10) or abs(budget_health(snaps, NOW_ISO) - 5/7) < 1e-9

def test_days_left_caps_at_one():
    # tiny burn -> days_left huge -> capped 1.0
    snaps = [Snap(0, 1000.0, iso(NOW - timedelta(hours=48))),
             Snap(0, 998.0, iso(NOW))]
    assert budget_health(snaps, NOW_ISO) == 1.0

def test_zero_or_negative_burn_is_healthy():
    # remaining rose (topped up within same epoch, sub-threshold) -> burn<=0 -> 1.0
    snaps = [Snap(0, 400.0, iso(NOW - timedelta(hours=48))),
             Snap(0, 450.0, iso(NOW))]
    assert budget_health(snaps, NOW_ISO) == 1.0

def test_epoch_reset_not_crossed():
    # old snapshot is a PRIOR epoch (topped up -> epoch bumped). Current epoch has
    # only 1 snapshot -> neutral, must NOT reach across the reset to compute burn.
    snaps = [Snap(0, 300.0, iso(NOW - timedelta(hours=48))),   # prior epoch
             Snap(1, 1000.0, iso(NOW))]                        # current epoch
    assert budget_health(snaps, NOW_ISO) == 0.7

def test_picks_snapshot_closest_to_48h():
    # current epoch has three ≥48h-old rows plus now; the one CLOSEST to now-48h
    # (the 49h row, remaining 600) must be chosen, not the oldest (72h, 900).
    snaps = [Snap(0, 900.0, iso(NOW - timedelta(hours=72))),
             Snap(0, 600.0, iso(NOW - timedelta(hours=49))),
             Snap(0, 400.0, iso(NOW))]
    # burn=(600-400)/2=100/day, days_left=4 -> 4/7
    assert abs(budget_health(snaps, NOW_ISO) - 4/7) < 1e-9

def test_missing_remaining_neutral():
    snaps = [Snap(0, None, iso(NOW - timedelta(hours=48))),
             Snap(0, 500.0, iso(NOW))]
    assert budget_health(snaps, NOW_ISO) == 0.7
