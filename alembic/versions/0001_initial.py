"""initial schema"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("campaigns",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("source", sa.String, index=True),
        sa.Column("external_id", sa.String, index=True),
        sa.Column("whop_experience_id", sa.String, nullable=True),
        sa.Column("whop_product_route", sa.String, nullable=True),
        sa.Column("url", sa.String, nullable=True),
        sa.Column("brand", sa.String, nullable=True),
        sa.Column("title", sa.String, nullable=True),
        sa.Column("niche", sa.String, nullable=True),
        sa.Column("cpm_usd", sa.Float, nullable=True),
        sa.Column("platform_fee_pct", sa.Float, nullable=True),
        sa.Column("cap_per_post_usd", sa.Float, nullable=True),
        sa.Column("cap_provenance", sa.String, server_default="absent"),
        sa.Column("min_payout_threshold_usd", sa.Float, nullable=True),
        sa.Column("min_views_threshold", sa.Integer, nullable=True),
        sa.Column("budget_total_usd", sa.Float, nullable=True),
        sa.Column("allowed_socials", sa.JSON, nullable=True),
        sa.Column("requirements_raw", sa.String, nullable=True),
        sa.Column("status", sa.String, server_default="active"),
        sa.Column("ingest_method", sa.String, server_default="auto"),
        sa.Column("access_status", sa.String, server_default="ingestable"),
        sa.Column("is_verified", sa.Boolean, nullable=True),
        sa.Column("first_seen_at", sa.String),
        sa.Column("last_seen_at", sa.String),
        sa.UniqueConstraint("source", "external_id", name="uq_source_external"),
    )
    op.create_table("campaign_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.String, index=True),
        sa.Column("epoch", sa.Integer, server_default="0"),
        sa.Column("budget_total_usd", sa.Float, nullable=True),
        sa.Column("budget_spent_usd", sa.Float, nullable=True),
        sa.Column("budget_remaining_usd", sa.Float, nullable=True),
        sa.Column("active_clippers", sa.Integer, nullable=True),
        sa.Column("total_views", sa.BigInteger, nullable=True),
        sa.Column("success_rate", sa.Float, nullable=True),
        sa.Column("engagement", sa.Float, nullable=True),
        sa.Column("captured_at", sa.String, index=True),
    )
    op.create_table("fetch_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String, index=True),
        sa.Column("url", sa.String),
        sa.Column("event_type", sa.String),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("detail", sa.String, nullable=True),
        sa.Column("detected_at", sa.String, index=True),
    )
    op.create_table("platform_trust",
        sa.Column("source", sa.String, primary_key=True),
        sa.Column("trust_score", sa.Float),
        sa.Column("default_fee_pct", sa.Float),
        sa.Column("notes", sa.String, nullable=True),
    )
    op.create_table("niche_baselines",
        sa.Column("niche", sa.String, primary_key=True),
        sa.Column("e_views_median", sa.Integer),
        sa.Column("p_threshold", sa.Float),
    )
    op.create_table("campaign_scores",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.String, index=True),
        sa.Column("scored_at", sa.String),
        sa.Column("net_cpm", sa.Float, nullable=True),
        sa.Column("capped_earnings", sa.Float, nullable=True),
        sa.Column("p_threshold", sa.Float, nullable=True),
        sa.Column("p_approval", sa.Float, nullable=True),
        sa.Column("p_payout", sa.Float, nullable=True),
        sa.Column("budget_health", sa.Float, nullable=True),
        sa.Column("sat_factor", sa.Float, nullable=True),
        sa.Column("ev_per_clip", sa.Float, nullable=True),
        sa.Column("cvs_raw", sa.Float, nullable=True),
        sa.Column("cvs_niche_percentile", sa.Float, nullable=True),
    )
    op.create_table("outcomes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.String, index=True),
        sa.Column("clips_posted", sa.Integer, nullable=True),
        sa.Column("clips_approved", sa.Integer, nullable=True),
        sa.Column("actual_views", sa.BigInteger, nullable=True),
        sa.Column("actual_payout_usd", sa.Float, nullable=True),
        sa.Column("payout_days", sa.Integer, nullable=True),
        sa.Column("logged_at", sa.String),
    )

def downgrade():
    for t in ["outcomes", "campaign_scores", "niche_baselines", "platform_trust",
              "fetch_events", "campaign_snapshots", "campaigns"]:
        op.drop_table(t)
