from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
import pytest
from clipscore.db.models import Alert

def test_alert_roundtrip(session):
    session.add(Alert(campaign_id="c1", epoch=0, niche="gaming",
                      cvs_niche_percentile=0.95, alerted_at="2026-07-14T00:00:00Z"))
    session.commit()
    a = session.execute(select(Alert)).scalars().one()
    assert a.campaign_id == "c1" and a.epoch == 0 and a.cvs_niche_percentile == 0.95

def test_alert_unique_campaign_epoch(session):
    session.add(Alert(campaign_id="c1", epoch=0, alerted_at="t"))
    session.commit()
    session.add(Alert(campaign_id="c1", epoch=0, alerted_at="t2"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

def test_alert_same_campaign_new_epoch_allowed(session):
    session.add(Alert(campaign_id="c1", epoch=0, alerted_at="t"))
    session.commit()
    session.add(Alert(campaign_id="c1", epoch=1, alerted_at="t2"))
    session.commit()  # different epoch -> allowed
    assert len(session.execute(select(Alert)).scalars().all()) == 2
