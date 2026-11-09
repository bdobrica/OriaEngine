"""Durable accepted turns, delivery and privacy bypass.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "inbound_events",
        sa.Column("is_control", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("inbound_events", sa.Column("admitted_consent_id", sa.Uuid(), nullable=True))
    for name in ("history_invalidated", "delivery_unconfirmed"):
        op.add_column(
            "conversation_sessions",
            sa.Column(name, sa.Boolean(), server_default="false", nullable=False),
        )
    op.create_table(
        "conversation_history_work",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("consent_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=True),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("delivery", sa.String(16), nullable=False),
        sa.Column("encrypted_prepared", sa.LargeBinary(), nullable=True),
        sa.Column("encrypted_finalize", sa.LargeBinary(), nullable=True),
        sa.Column("encryption_key_version", sa.String(64), nullable=False),
        sa.Column("receipt", sa.Text(), nullable=True),
        sa.Column("accept_attempted", sa.Boolean(), nullable=False),
        sa.Column("cleanup_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_cleanup_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["inbound_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "phase IN ('prepared','finalize','accepted','abandon','terminal')",
            name=op.f("ck_conversation_history_work_phase"),
        ),
        sa.CheckConstraint(
            "delivery IN ('not_attempted','unknown','failed','sent','cancelled')",
            name=op.f("ck_conversation_history_work_delivery"),
        ),
        sa.CheckConstraint(
            "phase NOT IN ('abandon','terminal') OR (encrypted_prepared IS NULL AND encrypted_finalize IS NULL)",
            name=op.f("ck_conversation_history_work_terminal_payload"),
        ),
    )
    op.create_index(
        "ix_conversation_history_work_user_id", "conversation_history_work", ["user_id"]
    )


def downgrade() -> None:
    # Never remove the recovery/erasure fence while it still owns work.
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM conversation_history_work WHERE phase != 'terminal')")
    ):
        raise RuntimeError("Resolve conversation history work before downgrade")
    op.drop_table("conversation_history_work")
    op.drop_column("conversation_sessions", "delivery_unconfirmed")
    op.drop_column("conversation_sessions", "history_invalidated")
    op.drop_column("inbound_events", "admitted_consent_id")
    op.drop_column("inbound_events", "is_control")
