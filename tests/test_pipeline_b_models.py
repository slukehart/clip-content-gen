from sqlalchemy import select
from clipscore.db.models import Campaign, ClipJob, SourceAsset, Clip, ClipMatch

def test_campaign_new_columns_roundtrip(session):
    c = Campaign(id="x1", source="contentrewards", external_id="x1", url="https://whop.com/x1",
                 status="active", content_bank_url="https://drive.google.com/abc",
                 target_creator='["@diego"]', target_platforms='["tiktok"]',
                 clip_min_len_s=15, clip_max_len_s=60, caption_rules="use #ad",
                 banned_content="no politics",
                 extract_provenance='{"content_bank_url":"whop_page"}',
                 first_seen_at="2026-07-14T00:00:00Z", last_seen_at="2026-07-14T00:00:00Z")
    session.add(c); session.commit()
    got = session.execute(select(Campaign)).scalars().one()
    assert got.content_bank_url == "https://drive.google.com/abc"
    assert got.clip_min_len_s == 15 and got.clip_max_len_s == 60

def test_pipeline_b_tables_roundtrip(session):
    job = ClipJob(campaign_id="x1", source_type="campaign_provided",
                  source_ref="https://drive.google.com/abc", status="queued",
                  created_at="2026-07-14T00:00:00Z")
    session.add(job); session.commit()
    assert session.execute(select(ClipJob)).scalars().one().status == "queued"
