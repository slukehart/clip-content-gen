"""add campaigns.extract_input_hash (re-extraction staleness marker)

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.add_column(sa.Column("extract_input_hash", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.drop_column("extract_input_hash")
