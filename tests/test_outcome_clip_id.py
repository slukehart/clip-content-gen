from clipscore.db.models import Outcome


def test_outcome_has_nullable_clip_id(session):
    o = Outcome(campaign_id="c1", clip_id=None, clips_posted=1, logged_at="2026-07-15T00:00:00Z")
    session.add(o)
    session.commit()
    got = session.get(Outcome, o.id)
    assert got.clip_id is None

    o2 = Outcome(campaign_id="c2", clip_id=42, clips_posted=1, logged_at="2026-07-15T00:00:00Z")
    session.add(o2)
    session.commit()
    assert session.get(Outcome, o2.id).clip_id == 42
