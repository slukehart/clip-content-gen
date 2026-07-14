import pytest
from clipscore.db.models import Campaign, CampaignScore
from clipscore.jobs.rank import ranked_rows, format_table
from clipscore.time import utcnow_iso

def _camp(session, cid, niche="gaming", cpm=2.0):
    now = utcnow_iso()
    session.add(Campaign(id=cid, source="contentrewards", external_id=cid, niche=niche,
                cpm_usd=cpm, cap_provenance="absent", status="active",
                access_status="ingestable", first_seen_at=now, last_seen_at=now))
    session.commit()

def _score(session, cid, cvs, pct, scored_at):
    session.add(CampaignScore(campaign_id=cid, scored_at=scored_at, cvs_raw=cvs,
                cvs_niche_percentile=pct, net_cpm=1.8, budget_health=0.7, sat_factor=0.8))
    session.commit()

def test_uses_latest_score_only(session):
    _camp(session, "a")
    _score(session, "a", 1.0, 0.2, "2026-07-10T00:00:00Z")
    _score(session, "a", 9.0, 0.9, "2026-07-13T00:00:00Z")   # latest
    rows = ranked_rows(session)
    assert len(rows) == 1 and rows[0]["cvs_raw"] == 9.0 and rows[0]["cvs_niche_percentile"] == 0.9

def test_sorted_by_percentile_desc(session):
    _camp(session, "a"); _camp(session, "b")
    _score(session, "a", 1.0, 0.3, "2026-07-13T00:00:00Z")
    _score(session, "b", 5.0, 0.8, "2026-07-13T00:00:00Z")
    rows = ranked_rows(session)
    assert [r["campaign_id"] for r in rows] == ["b", "a"]

def test_top_limit(session):
    for i in range(5):
        _camp(session, f"c{i}"); _score(session, f"c{i}", float(i), i/4, "2026-07-13T00:00:00Z")
    assert len(ranked_rows(session, top=2)) == 2

def test_niche_filter(session):
    _camp(session, "g", niche="gaming"); _camp(session, "m", niche="music")
    _score(session, "g", 1.0, 0.5, "2026-07-13T00:00:00Z")
    _score(session, "m", 2.0, 0.5, "2026-07-13T00:00:00Z")
    rows = ranked_rows(session, niche="music")
    assert [r["campaign_id"] for r in rows] == ["m"]

def test_format_table_carries_caveat(session):
    _camp(session, "a"); _score(session, "a", 9.0, 0.9, "2026-07-13T00:00:00Z")
    out = format_table(ranked_rows(session))
    assert "estimated screening signal, not a payout prediction" in out
    assert "$/hr" not in out

def test_none_percentile_sorts_last(session):
    # zero-cpm campaigns get a score row with cvs_niche_percentile=None (excluded
    # from the percentile population) — a genuinely reachable state. Such rows must
    # sort BELOW any campaign with a real percentile, regardless of cvs_raw.
    _camp(session, "real"); _camp(session, "nulled")
    _score(session, "real", 1.0, 0.4, "2026-07-13T00:00:00Z")
    _score(session, "nulled", 9.9, None, "2026-07-13T00:00:00Z")   # higher cvs_raw, but None pct
    rows = ranked_rows(session)
    assert [r["campaign_id"] for r in rows] == ["real", "nulled"]
    assert rows[-1]["cvs_niche_percentile"] is None
