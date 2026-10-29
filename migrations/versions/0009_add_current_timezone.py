"""add optional user-selected current timezone

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("current_timezone", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "current_timezone")
