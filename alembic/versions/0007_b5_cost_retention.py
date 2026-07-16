"""B5: clip_jobs.est_minutes + credits_used; clip_matches unique(clip_id, campaign_id)

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clip_jobs", sa.Column("est_minutes", sa.Integer(), nullable=True))
    op.add_column("clip_jobs", sa.Column("credits_used", sa.Integer(), nullable=True))
    # SQLite cannot ALTER ADD CONSTRAINT -> batch mode rebuilds the table.
    with op.batch_alter_table("clip_matches") as b:
        b.create_unique_constraint("uq_clipmatch_clip_campaign", ["clip_id", "campaign_id"])


def downgrade():
    with op.batch_alter_table("clip_matches") as b:
        b.drop_constraint("uq_clipmatch_clip_campaign", type_="unique")
    op.drop_column("clip_jobs", "credits_used")
    op.drop_column("clip_jobs", "est_minutes")
