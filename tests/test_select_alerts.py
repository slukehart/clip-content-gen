import pytest
from clipscore.db.models import Campaign, CampaignScore, CampaignSnapshot
from clipscore.bot.notify import select_alerts
from clipscore.bot.state import record_alert
from clipscore.time import utcnow_iso

def _camp(session, cid, niche="gaming", **kw):
    now = utcnow_iso()
    d = dict(id=cid, source="contentrewards", external_id=cid, niche=niche, title=f"T{cid}",
             url=f"http://x/{cid}", cpm_usd=2.0, cap_provenance="absent", status="active",
             access_status="ingestable", first_seen_at=now, last_seen_at=now)
    d.update(kw); session.add(Campaign(**d)); session.commit()

def _score(session, cid, pct, cvs=1.0):
    session.add(CampaignScore(campaign_id=cid, scored_at=utcnow_iso(), cvs_raw=cvs,
                              cvs_niche_percentile=pct))
    session.commit()

def _snap(session, cid, epoch=0):
    session.add(CampaignSnapshot(campaign_id=cid, epoch=epoch, captured_at=utcnow_iso()))
    session.commit()

def _niche_of(session, n, count, top_pct):
    # helper: create `count` campaigns in niche n; the first gets top_pct, rest 0.1..
    for i in range(count):
        cid = f"{n}{i}"
        _camp(session, cid, niche=n)
        _score(session, cid, top_pct if i == 0 else 0.1 + i * 0.01)
        _snap(session, cid)
    return f"{n}0"

def test_alerts_top_percentile_in_big_enough_niche(session):
    top = _niche_of(session, "gaming", 5, 0.95)
    out = select_alerts(session, 0.90, 5, utcnow_iso())
    assert any(a["campaign_id"] == top for a in out)

def test_small_niche_suppressed(session):
    _niche_of(session, "music", 3, 0.99)   # only 3 < MIN_NICHE_SAMPLE 5
    out = select_alerts(session, 0.90, 5, utcnow_iso())
    assert out == []

def test_below_threshold_not_alerted(session):
    _niche_of(session, "gaming", 5, 0.80)   # top is only 0.80 < 0.90
    out = select_alerts(session, 0.90, 5, utcnow_iso())
    assert out == []

def test_already_alerted_excluded(session):
    top = _niche_of(session, "gaming", 5, 0.95)
    record_alert(session, top, 0, "gaming", 0.95, utcnow_iso())
    out = select_alerts(session, 0.90, 5, utcnow_iso())
    assert all(a["campaign_id"] != top for a in out)

def test_new_epoch_re_alerts(session):
    top = _niche_of(session, "gaming", 5, 0.95)
    record_alert(session, top, 0, "gaming", 0.95, utcnow_iso())
    # relaunch: latest snapshot now epoch 1
    _snap(session, top, epoch=1)
    out = select_alerts(session, 0.90, 5, utcnow_iso())
    assert any(a["campaign_id"] == top and a["epoch"] == 1 for a in out)

def test_none_percentile_not_counted_or_alerted(session):
    # 4 real + 1 zero-cpm(None) in gaming -> valid population is 4 < 5 -> suppressed
    _niche_of(session, "gaming", 4, 0.95)
    _camp(session, "znull", niche="gaming"); _score(session, "znull", None); _snap(session, "znull")
    out = select_alerts(session, 0.90, 5, utcnow_iso())
    assert out == []
