from clipscore.config import Settings
from clipscore.db.models import Campaign, Clip, SourceAsset, ClipMatch, Outcome
from clipscore.web import actions


def _camp(session, cid, bank="https://drive.google.com/x", creator=None):
    session.add(Campaign(
        id=cid, source="s", external_id=cid, campaign_type="clipping", status="active",
        access_status="ingestable", first_seen_at="2026-01-01T00:00:00Z",
        last_seen_at="2026-01-01T00:00:00Z", content_bank_url=bank, target_creator=creator,
    ))
    session.commit()


def test_clip_this_enqueues(session):
    _camp(session, "a")
    res = actions.clip_this(session, "a", Settings())
    assert res.ok and res.status == "queued" and res.job_id is not None


def test_clip_this_no_source(session):
    _camp(session, "a", bank=None, creator=None)
    res = actions.clip_this(session, "a", Settings())
    assert res.ok is False and "no acquirable source" in res.error


def test_clip_this_unknown_campaign(session):
    res = actions.clip_this(session, "nope", Settings())
    assert res.ok is False and res.error


def test_mark_posted_idempotent(session):
    _camp(session, "a")
    sa = SourceAsset(clip_job_id=1); session.add(sa); session.commit()
    clip = Clip(source_asset_id=sa.id, status="ready", created_at="2026-07-10T00:00:00Z")
    session.add(clip); session.commit()
    m = ClipMatch(clip_id=clip.id, campaign_id="a", rank=1); session.add(m); session.commit()

    r1 = actions.mark_posted(session, m.id, now="2026-07-15T00:00:00Z")
    r2 = actions.mark_posted(session, m.id, now="2026-07-16T00:00:00Z")
    assert r1.ok and r2.ok
    outs = session.query(Outcome).filter_by(clip_id=clip.id, campaign_id="a").all()
    assert len(outs := outs) == 1                       # upsert, not append
    assert outs[0].clips_posted == 1


def test_mark_posted_unknown_match(session):
    assert actions.mark_posted(session, 9999).ok is False


def test_create_manual_campaign(session):
    res = actions.create_manual_campaign(
        session, title="My Manual", niche="gaming",
        content_bank_url="https://drive.google.com/y", target_creator=None,
        settings=Settings(), now="2026-07-15T00:00:00Z",
    )
    assert res.ok and res.job_id is not None
    assert session.query(Campaign).filter_by(source="manual").count() == 1
