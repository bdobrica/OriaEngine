"""encrypted canonical entities/events and conversational memory progress

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "birth_profiles", sa.Column("revision", sa.Integer(), server_default="1", nullable=False)
    )
    op.create_check_constraint(
        op.f("ck_birth_profiles_positive_revision"), "birth_profiles", "revision > 0"
    )
    op.create_table(
        "knowledge_records",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=True),
        sa.Column("encryption_key_version", sa.String(64), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('entity', 'event')", name=op.f("ck_knowledge_records_kind")),
        sa.CheckConstraint("revision > 0", name=op.f("ck_knowledge_records_positive_revision")),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND encrypted_payload IS NOT NULL AND octet_length(encrypted_payload) >= 29 "
            "AND encryption_key_version IS NOT NULL) OR "
            "(deleted_at IS NOT NULL AND encrypted_payload IS NULL "
            "AND encryption_key_version IS NULL)",
            name=op.f("ck_knowledge_records_lifecycle"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "id"),
    )
    op.create_table(
        "knowledge_links",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("dependency_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id", "record_id"],
            ["knowledge_records.user_id", "knowledge_records.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "dependency_id"],
            ["knowledge_records.user_id", "knowledge_records.id"],
            ondelete="CASCADE",
            name="fk_knowledge_links_dependency",
        ),
        sa.CheckConstraint("record_id <> dependency_id", name=op.f("ck_knowledge_links_not_self")),
        sa.PrimaryKeyConstraint("user_id", "record_id", "dependency_id"),
    )
    op.create_table(
        "knowledge_changes",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "record_id"],
            ["knowledge_records.user_id", "knowledge_records.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "record_id", "revision"),
    )
    op.create_table(
        "knowledge_operations",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "source_message_id"),
    )
    op.create_table(
        "knowledge_dialogues",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_key_version", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "octet_length(encrypted_payload) >= 29",
            name=op.f("ck_knowledge_dialogues_encrypted_envelope"),
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index("ix_knowledge_dialogues_expires_at", "knowledge_dialogues", ["expires_at"])


def downgrade() -> None:
    for name in (
        "knowledge_dialogues",
        "knowledge_operations",
        "knowledge_changes",
        "knowledge_links",
        "knowledge_records",
    ):
        op.drop_table(name)
    op.drop_constraint(op.f("ck_birth_profiles_positive_revision"), "birth_profiles", type_="check")
    op.drop_column("birth_profiles", "revision")
