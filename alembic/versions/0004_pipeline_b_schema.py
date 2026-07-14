"""add pipeline b schema (clip_jobs, source_assets, clips, clip_matches) + campaigns columns

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.add_column(sa.Column("content_bank_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("target_creator", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("target_platforms", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("clip_min_len_s", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("clip_max_len_s", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("caption_rules", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("banned_content", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("extract_provenance", sa.String(), nullable=True))

    op.create_table(
        "clip_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("est_cost_usd", sa.Float(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_clip_jobs_campaign_id", "clip_jobs", ["campaign_id"])

    op.create_table(
        "source_assets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("clip_job_id", sa.Integer(), nullable=False),
        sa.Column("creator", sa.String(), nullable=True),
        sa.Column("platform", sa.String(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("authorizing_campaign_id", sa.String(), nullable=True),
        sa.Column("storage_uri", sa.String(), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=True),
        sa.Column("downloaded_at", sa.String(), nullable=True),
    )
    op.create_index("ix_source_assets_clip_job_id", "source_assets", ["clip_job_id"])
    op.create_index("ix_source_assets_authorizing_campaign_id", "source_assets", ["authorizing_campaign_id"])

    op.create_table(
        "clips",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_asset_id", sa.Integer(), nullable=False),
        sa.Column("platform_variant", sa.String(), nullable=True),
        sa.Column("storage_uri", sa.String(), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column("transcript", sa.String(), nullable=True),
        sa.Column("engine", sa.String(), nullable=True),
        sa.Column("engine_clip_id", sa.String(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_clips_source_asset_id", "clips", ["source_asset_id"])

    op.create_table(
        "clip_matches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("clip_id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.String(), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("meets_requirements", sa.Integer(), nullable=True),
        sa.Column("suggested_caption", sa.String(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
    )
    op.create_index("ix_clip_matches_clip_id", "clip_matches", ["clip_id"])
    op.create_index("ix_clip_matches_campaign_id", "clip_matches", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_clip_matches_campaign_id", table_name="clip_matches")
    op.drop_index("ix_clip_matches_clip_id", table_name="clip_matches")
    op.drop_table("clip_matches")

    op.drop_index("ix_clips_source_asset_id", table_name="clips")
    op.drop_table("clips")

    op.drop_index("ix_source_assets_authorizing_campaign_id", table_name="source_assets")
    op.drop_index("ix_source_assets_clip_job_id", table_name="source_assets")
    op.drop_table("source_assets")

    op.drop_index("ix_clip_jobs_campaign_id", table_name="clip_jobs")
    op.drop_table("clip_jobs")

    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.drop_column("extract_provenance")
        batch_op.drop_column("banned_content")
        batch_op.drop_column("caption_rules")
        batch_op.drop_column("clip_max_len_s")
        batch_op.drop_column("clip_min_len_s")
        batch_op.drop_column("target_platforms")
        batch_op.drop_column("target_creator")
        batch_op.drop_column("content_bank_url")
