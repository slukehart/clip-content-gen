"""add outcomes.clip_id (nullable) for Pipeline B4 duplicate-deliverable warning

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("outcomes", sa.Column("clip_id", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("outcomes", "clip_id")
