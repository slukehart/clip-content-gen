import pytest
from sqlalchemy import select
from clipscore.db.models import (Campaign, CampaignSnapshot, CampaignScore,
                                 NicheBaseline, PlatformTrust)
from clipscore.scoring.engine import score_all
from clipscore.time import utcnow_iso

def _seed_refs(session):
    session.add(PlatformTrust(source="contentrewards", trust_score=0.8, default_fee_pct=0.10))
    for n in ("gaming", "other"):
        session.add(NicheBaseline(niche=n, e_views_median=8000, p_threshold=0.55))
    session.commit()

def _campaign(session, ext, **kw):
    now = utcnow_iso()
    defaults = dict(id=ext, source="contentrewards", external_id=ext,
                    niche="gaming", cpm_usd=2.0, cap_provenance="absent",
                    campaign_type="clipping", status="active",
                    access_status="ingestable", first_seen_at=now, last_seen_at=now)
    defaults.update(kw)
    c = Campaign(**defaults)
    session.add(c); session.commit()
    return c

def _snap(session, cid, remaining, clippers=10, epoch=0, captured_at=None):
    session.add(CampaignSnapshot(campaign_id=cid, epoch=epoch,
                budget_remaining_usd=remaining, active_clippers=clippers,
                captured_at=captured_at or utcnow_iso()))
    session.commit()

def test_scores_active_ingestable_campaign(session):
    _seed_refs(session)
    _campaign(session, "a"); _snap(session, "a", 500.0)
    res = score_all(session)
    assert res["scored"] == 1
    row = session.execute(select(CampaignScore)).scalars().one()
    assert row.campaign_id == "a"
    assert row.net_cpm == pytest.approx(1.8)         # 2.0*(1-0.10)
    assert row.p_payout == pytest.approx(0.8)         # platform trust
    assert row.p_approval == pytest.approx(0.7)       # guessed default
    assert row.budget_health == pytest.approx(0.7)    # <2 snapshots -> neutral
    assert row.cvs_niche_percentile == pytest.approx(1.0)   # only campaign in niche

def test_ugc_skipped(session):
    _seed_refs(session)
    _campaign(session, "u", campaign_type="ugc"); _snap(session, "u", 500.0)
    res = score_all(session)
    assert res["scored"] == 0 and res["skipped_ugc"] == 1
    assert session.execute(select(CampaignScore)).scalars().first() is None

def test_walled_skipped(session):
    _seed_refs(session)
    _campaign(session, "w", access_status="tos_restricted"); _snap(session, "w", 500.0)
    res = score_all(session)
    assert res["scored"] == 0 and res["skipped_walled"] == 1

def test_ended_not_scored(session):
    _seed_refs(session)
    _campaign(session, "e", status="ended"); _snap(session, "e", 500.0)
    assert score_all(session)["scored"] == 0

def test_zero_cpm_flagged_and_excluded_from_percentile(session):
    _seed_refs(session)
    _campaign(session, "z", cpm_usd=0.0); _snap(session, "z", 500.0)
    _campaign(session, "g", cpm_usd=2.0); _snap(session, "g", 500.0)
    res = score_all(session)
    assert res["scored"] == 2 and res["zero_cpm"] == 1
    rows = {r.campaign_id: r for r in session.execute(select(CampaignScore)).scalars()}
    assert rows["z"].cvs_raw == 0.0
    assert rows["z"].cvs_niche_percentile is None      # excluded from population
    assert rows["z"].p_threshold == 0.0 and rows["z"].p_approval == 0.0 and rows["z"].p_payout == 0.0
    assert rows["g"].cvs_niche_percentile == pytest.approx(1.0)  # sole valid in niche

def test_missing_cpm_flagged(session):
    _seed_refs(session)
    _campaign(session, "m", cpm_usd=None); _snap(session, "m", 500.0)
    res = score_all(session)
    assert res["zero_cpm"] == 1
    row = session.execute(select(CampaignScore)).scalars().one()
    assert row.cvs_raw == 0.0 and row.cvs_niche_percentile is None

def test_null_niche_uses_other_baseline(session):
    _seed_refs(session)
    _campaign(session, "n", niche=None); _snap(session, "n", 500.0)
    assert score_all(session)["scored"] == 1   # resolves to "other" baseline, no crash

def test_unknown_niche_falls_back_to_other(session):
    _seed_refs(session)
    _campaign(session, "x", niche="nonexistent"); _snap(session, "x", 500.0)
    assert score_all(session)["scored"] == 1

def test_percentile_within_niche(session):
    _seed_refs(session)
    # two gaming campaigns, different remaining -> different sat_factor -> different cvs
    _campaign(session, "lo", cpm_usd=2.0); _snap(session, "lo", 100.0, clippers=50)
    _campaign(session, "hi", cpm_usd=2.0); _snap(session, "hi", 5000.0, clippers=1)
    score_all(session)
    rows = {r.campaign_id: r for r in session.execute(select(CampaignScore)).scalars()}
    assert rows["hi"].cvs_raw > rows["lo"].cvs_raw
    assert rows["hi"].cvs_niche_percentile == pytest.approx(1.0)
    assert rows["lo"].cvs_niche_percentile == pytest.approx(0.5)

def test_multi_niche_no_cross_contamination(session):
    _seed_refs(session)
    session.add(NicheBaseline(niche="music", e_views_median=8000, p_threshold=0.55))
    session.commit()
    _campaign(session, "gm", niche="gaming", cpm_usd=2.0); _snap(session, "gm", 500.0)
    _campaign(session, "ms", niche="music", cpm_usd=2.0); _snap(session, "ms", 500.0)
    score_all(session)
    rows = {r.campaign_id: r for r in session.execute(select(CampaignScore)).scalars()}
    assert rows["gm"].cvs_niche_percentile == pytest.approx(1.0)
    assert rows["ms"].cvs_niche_percentile == pytest.approx(1.0)

def test_components_persisted(session):
    _seed_refs(session)
    _campaign(session, "c"); _snap(session, "c", 500.0)
    score_all(session)
    r = session.execute(select(CampaignScore)).scalars().one()
    for col in ("net_cpm", "capped_earnings", "p_threshold", "p_approval",
                "p_payout", "budget_health", "sat_factor", "ev_per_clip", "cvs_raw"):
        assert getattr(r, col) is not None
