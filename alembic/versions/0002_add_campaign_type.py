"""add campaign_type to campaigns"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("campaigns", sa.Column("campaign_type", sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column("campaigns", "campaign_type")
