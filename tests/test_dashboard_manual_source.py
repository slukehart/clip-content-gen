from clipscore.config import Settings
from clipscore.db.models import Campaign, ClipJob
from clipscore.web.actions import clip_this


def _bare_campaign(session, cid="c1"):
    # a ranked campaign with NO auto-discoverable source (the real-world norm)
    session.add(Campaign(id=cid, source="contentrewards", external_id=cid,
                         campaign_type="clipping", status="active", access_status="ingestable",
                         first_seen_at="2026-07-01T00:00:00Z", last_seen_at="2026-07-01T00:00:00Z"))
    session.commit()


def test_clip_this_with_pasted_url_routes_passthrough(session):
    _bare_campaign(session)
    res = clip_this(session, "c1", Settings(_env_file=None), source_ref="https://youtu.be/abc")
    assert res.ok and res.job_id is not None
    job = session.get(ClipJob, res.job_id)
    assert job.source_type == "passthrough"
    assert job.source_ref == "https://youtu.be/abc"


def test_clip_this_with_non_fetchable_url_routes_campaign_provided(session):
    _bare_campaign(session)
    res = clip_this(session, "c1", Settings(_env_file=None),
                    source_ref="https://example.com/page.html")
    assert res.ok
    job = session.get(ClipJob, res.job_id)
    assert job.source_type == "campaign_provided"
    assert job.source_ref == "https://example.com/page.html"


def test_approval_row_carries_campaign_url(session):
    from clipscore.db.models import CampaignScore
    from clipscore.web.queries import approval_rows
    session.add(Campaign(id="c1", source="contentrewards", external_id="c1",
                         campaign_type="clipping", status="active", access_status="ingestable",
                         title="Cool Campaign", url="https://whop.com/cool-campaign",
                         first_seen_at="2026-07-01T00:00:00Z", last_seen_at="2026-07-01T00:00:00Z"))
    session.add(CampaignScore(campaign_id="c1", scored_at="2026-07-01T00:00:00Z",
                              cvs_niche_percentile=0.5))
    session.commit()
    rows = approval_rows(session, Settings(_env_file=None))
    assert rows[0].url == "https://whop.com/cool-campaign"


def test_clip_this_without_source_still_errors_when_no_auto_source(session):
    # unchanged behavior: no pasted URL + no auto-source -> clean error, no job
    _bare_campaign(session)
    res = clip_this(session, "c1", Settings(_env_file=None))
    assert not res.ok
    assert "no acquirable source" in (res.error or "")
    assert session.query(ClipJob).count() == 0
