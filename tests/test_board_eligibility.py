from clipscore.db.models import Campaign, CampaignScore
from clipscore.scoring.board import eligible_latest_scores
from clipscore.time import utcnow_iso

def _camp(session, cid, **kw):
    now = utcnow_iso()
    d = dict(id=cid, source="contentrewards", external_id=cid, niche="gaming",
             cpm_usd=2.0, cap_provenance="absent", status="active",
             access_status="ingestable", first_seen_at=now, last_seen_at=now)
    d.update(kw); session.add(Campaign(**d)); session.commit()

def _score(session, cid, sid_hint, scored_at):
    session.add(CampaignScore(campaign_id=cid, scored_at=scored_at, cvs_raw=1.0,
                              cvs_niche_percentile=0.5))
    session.commit()

def test_returns_latest_score_only(session):
    _camp(session, "a")
    _score(session, "a", 1, "2026-07-10T00:00:00Z")
    _score(session, "a", 2, "2026-07-14T00:00:00Z")
    pairs = eligible_latest_scores(session)
    assert len(pairs) == 1
    c, s = pairs[0]
    assert c.id == "a" and s.scored_at == "2026-07-14T00:00:00Z"

def test_excludes_ended_walled_ugc(session):
    _camp(session, "live"); _score(session, "live", 1, "t")
    _camp(session, "ended", status="ended"); _score(session, "ended", 1, "t")
    _camp(session, "walled", access_status="tos_restricted"); _score(session, "walled", 1, "t")
    _camp(session, "ugc", campaign_type="ugc"); _score(session, "ugc", 1, "t")
    ids = {c.id for c, _ in eligible_latest_scores(session)}
    assert ids == {"live"}
