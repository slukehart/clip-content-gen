from datetime import datetime, timedelta, timezone
from clipscore.db.models import Campaign, CampaignScore
from clipscore.bot.notify import compute_movers

def iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)

def _camp(session, cid):
    session.add(Campaign(id=cid, source="contentrewards", external_id=cid, niche="gaming",
                title=f"T{cid}", cpm_usd=2.0, cap_provenance="absent", status="active",
                access_status="ingestable", first_seen_at=iso(NOW), last_seen_at=iso(NOW)))
    session.commit()

def _score(session, cid, pct, at):
    session.add(CampaignScore(campaign_id=cid, scored_at=at, cvs_raw=1.0, cvs_niche_percentile=pct))
    session.commit()

def test_mover_delta_uses_past_ge_24h(session):
    _camp(session, "a")
    _score(session, "a", 0.3, iso(NOW - timedelta(hours=30)))   # past (>=24h)
    _score(session, "a", 0.5, iso(NOW - timedelta(hours=1)))    # between (ignored as past)
    _score(session, "a", 0.9, iso(NOW))                          # current
    m = compute_movers(session, iso(NOW))
    assert len(m) == 1 and abs(m[0]["delta"] - 0.6) < 1e-9       # 0.9 - 0.3

def test_young_campaign_excluded(session):
    _camp(session, "b")
    _score(session, "b", 0.5, iso(NOW - timedelta(hours=2)))    # no score >=24h old
    _score(session, "b", 0.9, iso(NOW))
    assert compute_movers(session, iso(NOW)) == []

def test_none_percentile_endpoint_excluded(session):
    _camp(session, "c")
    _score(session, "c", None, iso(NOW - timedelta(hours=30)))
    _score(session, "c", 0.9, iso(NOW))
    assert compute_movers(session, iso(NOW)) == []

def test_sorted_by_abs_delta_desc(session):
    _camp(session, "up"); _camp(session, "down")
    _score(session, "up", 0.5, iso(NOW - timedelta(hours=30))); _score(session, "up", 0.6, iso(NOW))
    _score(session, "down", 0.9, iso(NOW - timedelta(hours=30))); _score(session, "down", 0.3, iso(NOW))
    m = compute_movers(session, iso(NOW))
    assert m[0]["campaign_id"] == "down"   # |−0.6| > |0.1|
    assert m[0]["delta"] < 0
