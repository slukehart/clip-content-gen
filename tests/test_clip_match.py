from sqlalchemy import select
from clipscore.db.models import Clip, SourceAsset, ClipMatch, Campaign, CampaignScore, ClipJob
from clipscore.factory.clip.match import match_clip, run_matching
from clipscore.time import utcnow_iso

def _camp(session, cid, pct, **kw):
    now = utcnow_iso()
    c = Campaign(id=cid, source="cr", external_id=cid, status="active", access_status="ingestable",
                 campaign_type="clipping", first_seen_at=now, last_seen_at=now,
                 target_creator='["@diego"]', target_platforms='["tiktok"]', **kw)
    session.add(c)
    session.add(CampaignScore(campaign_id=cid, scored_at=now, cvs_niche_percentile=pct))
    session.commit()

def _clip(session, variant="tiktok", dur=90, creator="diego"):
    now = utcnow_iso()
    j = ClipJob(campaign_id="c1", source_type="url", source_ref="u", status="produced", created_at=now)
    session.add(j); session.commit()
    sa = SourceAsset(clip_job_id=j.id, creator=creator, platform="url", downloaded_at=now)
    session.add(sa); session.commit()
    clip = Clip(source_asset_id=sa.id, platform_variant=variant, duration_s=dur,
                storage_uri="x.mp4", engine="fake", status="produced", created_at=now)
    session.add(clip); session.commit()
    return j, clip

def test_match_ranks_by_cvs_percentile_times_specfit(session):
    _camp(session, "c1", 0.9, clip_min_len_s=60, clip_max_len_s=120)   # windowed -> spec_fit 1.0
    _camp(session, "c2", 0.95, clip_min_len_s=None, clip_max_len_s=None)  # no window -> spec_fit 0.9
    _, clip = _clip(session, dur=90)
    rows = match_clip(session, clip)
    ids = [r["campaign_id"] for r in rows]
    assert ids == ["c1", "c2"]  # 0.9*1.0=0.90 > 0.95*0.9=0.855
    assert rows[0]["rank"] == 1 and rows[0]["match_score"] == 0.9

def test_length_out_of_window_excludes(session):
    _camp(session, "c1", 0.9, clip_min_len_s=60, clip_max_len_s=80)
    _, clip = _clip(session, dur=200)  # too long
    assert match_clip(session, clip) == []

def test_platform_mismatch_excludes(session):
    _camp(session, "c1", 0.9)  # target_platforms tiktok
    _, clip = _clip(session, variant="shorts")  # -> youtube, not accepted
    assert match_clip(session, clip) == []

def test_run_matching_writes_rows_and_sets_status(session):
    _camp(session, "c1", 0.9, clip_min_len_s=60, clip_max_len_s=120)
    j, clip = _clip(session, dur=90)
    run_matching(session, j)
    assert j.status == "matched"
    m = session.execute(select(ClipMatch)).scalars().all()
    assert len(m) == 1 and m[0].campaign_id == "c1" and m[0].rank == 1 and m[0].meets_requirements == 1
