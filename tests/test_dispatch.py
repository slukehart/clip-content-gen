import pytest
from unittest.mock import patch
from clipscore.db.models import Campaign, CampaignScore, CampaignSnapshot
from clipscore.bot.dispatch import dispatch_alerts, dispatch_summary, poll_and_alert
from clipscore.config import get_settings
from clipscore.time import utcnow_iso

class FakeNotifier:
    def __init__(self, fail=False):
        self.sent = []; self.fail = fail
    def send(self, text):
        if self.fail:
            raise RuntimeError("discord down")
        self.sent.append(text)

def _big_niche(session, top_pct=0.95, n=5):
    now = utcnow_iso()
    for i in range(n):
        cid = f"g{i}"
        session.add(Campaign(id=cid, source="contentrewards", external_id=cid, niche="gaming",
                    title=f"T{cid}", url=f"http://x/{cid}", cpm_usd=2.0, cap_provenance="absent",
                    status="active", access_status="ingestable", first_seen_at=now, last_seen_at=now))
        session.add(CampaignScore(campaign_id=cid, scored_at=now, cvs_raw=1.0,
                    cvs_niche_percentile=top_pct if i == 0 else 0.1 + i * 0.01))
        session.add(CampaignSnapshot(campaign_id=cid, epoch=0, captured_at=now))
    session.commit()

def test_dispatch_sends_then_dedups(session):
    _big_niche(session)
    n = FakeNotifier()
    r1 = dispatch_alerts(session, n, get_settings())
    assert r1["alerts_sent"] == 1 and len(n.sent) == 1
    r2 = dispatch_alerts(session, n, get_settings())        # already recorded
    assert r2["alerts_sent"] == 0 and len(n.sent) == 1

def test_failed_send_not_recorded_retries(session):
    _big_niche(session)
    bad = FakeNotifier(fail=True)
    r = dispatch_alerts(session, bad, get_settings())
    assert r["alerts_sent"] == 0                             # nothing recorded
    good = FakeNotifier()
    assert dispatch_alerts(session, good, get_settings())["alerts_sent"] == 1  # retried

def test_summary_sends(session):
    _big_niche(session)
    n = FakeNotifier()
    assert dispatch_summary(session, n)["summary_sent"] is True
    assert len(n.sent) == 1

def test_poll_and_alert_survives_notifier_failure(session):
    with patch("clipscore.bot.dispatch.run_once", return_value={"status": "ok", "scored": 5}), \
         patch("clipscore.bot.dispatch.dispatch_alerts", side_effect=RuntimeError("boom")):
        res = poll_and_alert(session, FakeNotifier())
    assert res["status"] == "ok" and res["scored"] == 5     # ingest/score result intact

def test_poll_and_alert_skips_dispatch_on_non_ok(session):
    with patch("clipscore.bot.dispatch.run_once", return_value={"status": "halted"}), \
         patch("clipscore.bot.dispatch.dispatch_alerts") as m:
        res = poll_and_alert(session, FakeNotifier())
    m.assert_not_called()
    assert res["status"] == "halted"
