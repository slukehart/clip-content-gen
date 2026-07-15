from clipscore.db.models import Outcome, Clip, SourceAsset
from clipscore.web.warnings import duplicate_warnings


def _clip(session, source_asset_id, cid=None):
    c = Clip(source_asset_id=source_asset_id, status="ready", created_at="2026-07-10T00:00:00Z")
    session.add(c); session.commit()
    return c


def test_no_warnings_when_clean(session):
    sa = SourceAsset(clip_job_id=1); session.add(sa); session.commit()
    c = _clip(session, sa.id)
    assert duplicate_warnings(session, c.id, "camp1") == []


def test_repeat_delivery_warning(session):
    sa = SourceAsset(clip_job_id=1); session.add(sa); session.commit()
    c = _clip(session, sa.id)
    session.add(Outcome(campaign_id="camp1", clip_id=c.id, clips_posted=1,
                        logged_at="2026-07-10T00:00:00Z"))
    session.commit()
    warns = duplicate_warnings(session, c.id, "camp1")
    assert any("Already delivered to this campaign" in w for w in warns)


def test_footage_reuse_warning(session):
    sa = SourceAsset(clip_job_id=1); session.add(sa); session.commit()
    c1 = _clip(session, sa.id)      # posted to campA
    c2 = _clip(session, sa.id)      # same footage, about to post to campB
    session.add(Outcome(campaign_id="campA", clip_id=c1.id, clips_posted=1,
                        logged_at="2026-07-10T00:00:00Z"))
    session.commit()
    warns = duplicate_warnings(session, c2.id, "campB")
    assert any("already posted to campaign campA" in w for w in warns)
    # posting the SAME footage to the SAME campA is repeat-delivery, not reuse
    warns_same = duplicate_warnings(session, c2.id, "campA")
    assert any("Already delivered to this campaign" in w for w in warns_same)
    assert not any("already posted to campaign campA" in w for w in warns_same)
