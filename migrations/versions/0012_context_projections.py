"""encrypted durable SecondContext projection work

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "context_projection_work",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=True),
        sa.Column("encryption_key_version", sa.String(64), nullable=True),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column("pending", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('entity','event','reading')", name=op.f("ck_context_projection_work_kind")
        ),
        sa.CheckConstraint(
            "revision > 0 AND attempts >= 0",
            name=op.f("ck_context_projection_work_positive_revision"),
        ),
        sa.CheckConstraint(
            "(deleted AND encrypted_payload IS NULL AND encryption_key_version IS NULL) OR "
            "(NOT deleted AND encrypted_payload IS NOT NULL AND octet_length(encrypted_payload) >= 29 "
            "AND encryption_key_version IS NOT NULL)",
            name=op.f("ck_context_projection_work_lifecycle"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "id"),
    )
    op.create_index(
        "ix_context_projection_work_next_attempt_at", "context_projection_work", ["next_attempt_at"]
    )


def downgrade() -> None:
    op.drop_table("context_projection_work")
