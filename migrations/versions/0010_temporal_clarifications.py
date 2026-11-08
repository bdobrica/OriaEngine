"""short-lived encrypted temporal clarification

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "temporal_clarifications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_key_version", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "octet_length(encrypted_payload) >= 29",
            name=op.f("ck_temporal_clarifications_encrypted_envelope"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name=op.f("fk_temporal_clarifications_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_temporal_clarifications")),
    )
    op.create_index(
        "ix_temporal_clarifications_expires_at", "temporal_clarifications", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_table("temporal_clarifications")
