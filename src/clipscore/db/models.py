from sqlalchemy import String, Integer, Float, Boolean, JSON, BigInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from clipscore.db.base import Base

class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_source_external"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, index=True)
    external_id: Mapped[str] = mapped_column(String, index=True)
    whop_experience_id: Mapped[str | None] = mapped_column(String, nullable=True)
    whop_product_route: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    brand: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    campaign_type: Mapped[str | None] = mapped_column(String, nullable=True)
    niche: Mapped[str | None] = mapped_column(String, nullable=True)
    cpm_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    platform_fee_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    cap_per_post_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cap_provenance: Mapped[str] = mapped_column(String, default="absent")
    min_payout_threshold_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_views_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_total_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    allowed_socials: Mapped[list | None] = mapped_column(JSON, nullable=True)
    requirements_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
    ingest_method: Mapped[str] = mapped_column(String, default="auto")
    access_status: Mapped[str] = mapped_column(String, default="ingestable")
    is_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    first_seen_at: Mapped[str] = mapped_column(String)
    last_seen_at: Mapped[str] = mapped_column(String)
    content_bank_url: Mapped[str | None] = mapped_column(String, nullable=True)
    target_creator: Mapped[str | None] = mapped_column(String, nullable=True)
    target_platforms: Mapped[str | None] = mapped_column(String, nullable=True)
    clip_min_len_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clip_max_len_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    caption_rules: Mapped[str | None] = mapped_column(String, nullable=True)
    banned_content: Mapped[str | None] = mapped_column(String, nullable=True)
    extract_provenance: Mapped[str | None] = mapped_column(String, nullable=True)

class CampaignSnapshot(Base):
    __tablename__ = "campaign_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(String, index=True)
    epoch: Mapped[int] = mapped_column(Integer, default=0)
    budget_total_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_spent_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_remaining_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_clippers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    engagement: Mapped[float | None] = mapped_column(Float, nullable=True)
    captured_at: Mapped[str] = mapped_column(String, index=True)

class FetchEvent(Base):
    __tablename__ = "fetch_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, index=True)
    url: Mapped[str] = mapped_column(String)
    event_type: Mapped[str] = mapped_column(String)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(String, nullable=True)
    detected_at: Mapped[str] = mapped_column(String, index=True)

class PlatformTrust(Base):
    __tablename__ = "platform_trust"
    source: Mapped[str] = mapped_column(String, primary_key=True)
    trust_score: Mapped[float] = mapped_column(Float)
    default_fee_pct: Mapped[float] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

class NicheBaseline(Base):
    __tablename__ = "niche_baselines"
    niche: Mapped[str] = mapped_column(String, primary_key=True)
    e_views_median: Mapped[int] = mapped_column(Integer)
    p_threshold: Mapped[float] = mapped_column(Float)

class CampaignScore(Base):
    __tablename__ = "campaign_scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(String, index=True)
    scored_at: Mapped[str] = mapped_column(String)
    net_cpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    capped_earnings: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_approval: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_payout: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_health: Mapped[float | None] = mapped_column(Float, nullable=True)
    sat_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    ev_per_clip: Mapped[float | None] = mapped_column(Float, nullable=True)
    cvs_raw: Mapped[float | None] = mapped_column(Float, nullable=True)
    cvs_niche_percentile: Mapped[float | None] = mapped_column(Float, nullable=True)

class Outcome(Base):
    __tablename__ = "outcomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(String, index=True)
    clips_posted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clips_approved: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actual_payout_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    payout_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    logged_at: Mapped[str] = mapped_column(String)

class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("campaign_id", "epoch", name="uq_alert_campaign_epoch"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(String, index=True)
    epoch: Mapped[int] = mapped_column(Integer)
    niche: Mapped[str | None] = mapped_column(String, nullable=True)
    cvs_niche_percentile: Mapped[float | None] = mapped_column(Float, nullable=True)
    alerted_at: Mapped[str] = mapped_column(String)

class ClipJob(Base):
    __tablename__ = "clip_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(String, index=True)
    source_type: Mapped[str] = mapped_column(String)
    source_ref: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    est_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String)

class SourceAsset(Base):
    __tablename__ = "source_assets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_job_id: Mapped[int] = mapped_column(Integer, index=True)
    creator: Mapped[str | None] = mapped_column(String, nullable=True)
    platform: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    authorizing_campaign_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    downloaded_at: Mapped[str | None] = mapped_column(String, nullable=True)

class Clip(Base):
    __tablename__ = "clips"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_asset_id: Mapped[int] = mapped_column(Integer, index=True)
    platform_variant: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcript: Mapped[str | None] = mapped_column(String, nullable=True)
    engine: Mapped[str | None] = mapped_column(String, nullable=True)
    engine_clip_id: Mapped[str | None] = mapped_column(String, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)

class ClipMatch(Base):
    __tablename__ = "clip_matches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_id: Mapped[int] = mapped_column(Integer, index=True)
    campaign_id: Mapped[str] = mapped_column(String, index=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    meets_requirements: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggested_caption: Mapped[str | None] = mapped_column(String, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
