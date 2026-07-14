"""End-to-end regression for the branch's load-bearing invariant: real score_all
percentiles feeding select_alerts. Guards that the per-niche alert floor counts
exactly the population empirical_cdf ran over, and that only campaigns actually at
/above ALERT_PERCENTILE (by REAL scoring, not hand-set values) are selected."""
from clipscore.db.models import Campaign, CampaignSnapshot, NicheBaseline, PlatformTrust
from clipscore.scoring.engine import score_all
from clipscore.bot.notify import select_alerts
from clipscore.time import utcnow_iso


def _refs(session):
    session.add(PlatformTrust(source="contentrewards", trust_score=0.8, default_fee_pct=0.10))
    for n in ("gaming", "music"):
        session.add(NicheBaseline(niche=n, e_views_median=8000, p_threshold=0.55))
    session.commit()


def _camp(session, cid, niche, clippers):
    now = utcnow_iso()
    session.add(Campaign(id=cid, source="contentrewards", external_id=cid, niche=niche,
                title=f"T{cid}", url=f"http://x/{cid}", cpm_usd=2.0, cap_provenance="absent",
                campaign_type="clipping", status="active", access_status="ingestable",
                first_seen_at=now, last_seen_at=now))
    # fixed remaining, varied clippers -> distinct sat_factor -> distinct cvs -> distinct pct
    session.add(CampaignSnapshot(campaign_id=cid, epoch=0, budget_remaining_usd=1000.0,
                active_clippers=clippers, captured_at=now))
    session.commit()


def test_real_scoring_feeds_alerts(session):
    _refs(session)
    # gaming: 5 campaigns, clippers 100/50/20/10/5 -> sat 0.05/0.1/0.25/0.5/1.0 ascending
    for i, clippers in enumerate((100, 50, 20, 10, 5)):
        _camp(session, f"g{i}", "gaming", clippers)
    # music: only 4 campaigns -> below MIN_NICHE_SAMPLE=5, must be suppressed
    for i, clippers in enumerate((100, 50, 20, 5)):
        _camp(session, f"m{i}", "music", clippers)

    score_all(session)  # real percentiles via empirical_cdf
    alerts = select_alerts(session, 0.90, 5, utcnow_iso())

    ids = {a["campaign_id"] for a in alerts}
    assert ids == {"g4"}          # only the top gaming campaign (percentile 1.0 >= 0.90)
    assert all(a["niche"] == "gaming" for a in alerts)   # music (4<5) suppressed by floor
    assert alerts[0]["percentile"] >= 0.90
