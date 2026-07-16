from clipscore.config import Settings
from clipscore.db.models import Campaign, CampaignScore
from clipscore.jobs.rank import ranked_rows
from clipscore.web.queries import approval_rows

LANE = {"personal brand", "technology", "product"}


def _camp(session, cid, niche):
    session.add(Campaign(id=cid, source="manual", external_id=cid, campaign_type="clipping",
                         niche=niche, status="active", access_status="ingestable",
                         first_seen_at="2026-07-01T00:00:00Z", last_seen_at="2026-07-01T00:00:00Z"))
    session.add(CampaignScore(campaign_id=cid, scored_at="2026-07-01T00:00:00Z",
                              cvs_niche_percentile=0.5, cvs_raw=1.0))


def test_target_niche_set_parses_and_normalizes():
    s = Settings(_env_file=None, target_niches="personal brand, technology ,Product")
    assert s.target_niche_set == frozenset({"personal brand", "technology", "product"})


def test_target_niche_set_empty_means_no_filter():
    assert Settings(_env_file=None, target_niches="").target_niche_set == frozenset()


def test_ranked_rows_filters_to_target_niches(session):
    _camp(session, "b1", "personal brand")
    _camp(session, "t1", "technology")
    _camp(session, "m1", "music")
    session.commit()
    rows = ranked_rows(session, niches=LANE)
    assert {r["niche"] for r in rows} == {"personal brand", "technology"}
    assert "m1" not in {r["campaign_id"] for r in rows}


def test_ranked_rows_empty_niches_returns_all(session):
    _camp(session, "b1", "personal brand")
    _camp(session, "m1", "music")
    session.commit()
    rows = ranked_rows(session, niches=set())
    assert {r["niche"] for r in rows} == {"personal brand", "music"}


def test_approval_rows_honors_target_niches(session):
    _camp(session, "b1", "personal brand")
    _camp(session, "m1", "music")
    session.commit()
    s = Settings(_env_file=None, target_niches="personal brand,technology,product")
    rows = approval_rows(session, s)
    assert {r.campaign_id for r in rows} == {"b1"}
