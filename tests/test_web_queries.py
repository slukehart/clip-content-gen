from datetime import datetime, timezone

from clipscore.config import Settings
from clipscore.db.models import Campaign, CampaignScore, ClipJob, Clip, SourceAsset, ClipMatch
from clipscore.time import et_month_bounds_utc
from clipscore.web import queries


def _camp(session, cid, ctype="clipping", pct=0.5, bank="https://drive.google.com/x"):
    session.add(Campaign(
        id=cid, source="s", external_id=cid, campaign_type=ctype, niche="gaming",
        title=f"T {cid}", status="active", access_status="ingestable",
        first_seen_at="2026-01-01T00:00:00Z", last_seen_at="2026-01-01T00:00:00Z",
        content_bank_url=bank,
    ))
    session.add(CampaignScore(campaign_id=cid, scored_at="2026-01-01T00:00:00Z",
                              cvs_niche_percentile=pct))
    session.commit()


def test_approval_rows_filters_and_sorts(session):
    _camp(session, "a", "clipping", pct=0.4)
    _camp(session, "b", "both", pct=0.9)
    _camp(session, "u", "ugc", pct=0.99)          # excluded by eligible_latest_scores
    rows = queries.approval_rows(session, Settings(clip_est_cost_usd=1.25))
    ids = [r.campaign_id for r in rows]
    assert ids == ["b", "a"]                        # ugc dropped, sorted desc by pct
    assert rows[0].est_cost_usd == 1.25
    assert rows[0].clippable is True


def test_approval_row_job_status(session):
    _camp(session, "a")
    session.add(ClipJob(campaign_id="a", source_type="campaign_provided", source_ref="x",
                        status="queued", created_at="2026-01-02T00:00:00Z"))
    session.commit()
    rows = queries.approval_rows(session, Settings())
    assert rows[0].job_status == "queued"


def test_review_detail_and_ready_clips(session):
    _camp(session, "a", pct=0.7)
    sa = SourceAsset(clip_job_id=1, storage_uri="media/x.mp4")
    session.add(sa); session.commit()
    clip = Clip(source_asset_id=sa.id, platform_variant="tiktok", duration_s=60,
                status="ready", cost_usd=0.5, created_at="2026-07-10T00:00:00Z")
    session.add(clip); session.commit()
    session.add(ClipMatch(clip_id=clip.id, campaign_id="a", match_score=0.7,
                          meets_requirements=1, suggested_caption="hi #ad", rank=1))
    session.commit()

    assert [c.clip_id for c in queries.ready_clips(session)] == [clip.id]
    detail = queries.review_detail(session, clip.id)
    assert detail.matches[0].campaign_id == "a"
    assert detail.download_url == f"/media/{clip.id}"
    assert "target_platforms" in detail.requirements
    assert queries.review_detail(session, 9999) is None


def test_monthly_cost_uses_et_month(session):
    sa = SourceAsset(clip_job_id=1, storage_uri="media/x.mp4"); session.add(sa); session.commit()
    now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    start, nxt = et_month_bounds_utc(now)
    # in-month clip counts; a clip stamped before the month start does not
    session.add(Clip(source_asset_id=sa.id, status="ready", cost_usd=2.0,
                     created_at="2026-07-10T00:00:00Z"))
    session.add(Clip(source_asset_id=sa.id, status="ready", cost_usd=5.0,
                     created_at="2026-06-01T00:00:00Z"))
    session.add(Clip(source_asset_id=sa.id, status="ready", cost_usd=None,
                     created_at="2026-07-11T00:00:00Z"))     # NULL cost -> 0
    session.commit()
    assert queries.monthly_cost_usd(session, now=now) == 2.0
