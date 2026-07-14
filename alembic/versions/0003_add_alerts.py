"""add alerts table

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.String(), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("niche", sa.String(), nullable=True),
        sa.Column("cvs_niche_percentile", sa.Float(), nullable=True),
        sa.Column("alerted_at", sa.String(), nullable=False),
        sa.UniqueConstraint("campaign_id", "epoch", name="uq_alert_campaign_epoch"),
    )
    op.create_index("ix_alerts_campaign_id", "alerts", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_alerts_campaign_id", table_name="alerts")
    op.drop_table("alerts")
