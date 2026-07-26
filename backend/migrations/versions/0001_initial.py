"""Create the initial persistent analysis schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-21
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[datetime], sa.Column[datetime]]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "analysis_target",
        sa.Column("bvid", sa.Text(), nullable=False),
        sa.Column("cid", sa.BigInteger(), nullable=False),
        sa.Column("desired_analysis_version", sa.Text(), nullable=False),
        sa.Column("write_generation", sa.BigInteger(), nullable=False),
        sa.Column("owner_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("cid > 0", name="ck_analysis_target_cid_positive"),
        sa.CheckConstraint(
            "write_generation > 0",
            name="ck_analysis_target_write_generation_positive",
        ),
        sa.PrimaryKeyConstraint("bvid", "cid", name="pk_analysis_target"),
    )

    op.create_table(
        "analysis_result",
        sa.Column("bvid", sa.Text(), nullable=False),
        sa.Column("cid", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Double(), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("analysis_version", sa.Text(), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analysis_expires_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("cid > 0", name="ck_analysis_result_cid_positive"),
        sa.CheckConstraint("score BETWEEN 0 AND 100", name="ck_analysis_result_score_range"),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1",
            name="ck_analysis_result_confidence_range",
        ),
        sa.CheckConstraint(
            "label IN ('none', 'light', 'medium', 'high')",
            name="ck_analysis_result_label_known",
        ),
        sa.CheckConstraint(
            "analysis_expires_at >= analyzed_at",
            name="ck_analysis_result_expiry_order",
        ),
        sa.ForeignKeyConstraint(
            ["bvid", "cid"],
            ["analysis_target.bvid", "analysis_target.cid"],
            name="fk_analysis_result_target",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("bvid", "cid", name="pk_analysis_result"),
    )

    op.create_table(
        "video_declaration",
        sa.Column("bvid", sa.Text(), nullable=False),
        sa.Column("cid", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("cid > 0", name="ck_video_declaration_cid_positive"),
        sa.CheckConstraint(
            "state IN ('declared_ai', 'not_declared', 'unknown')",
            name="ck_video_declaration_state_known",
        ),
        sa.CheckConstraint(
            "expires_at >= checked_at",
            name="ck_video_declaration_expiry_order",
        ),
        sa.ForeignKeyConstraint(
            ["bvid", "cid"],
            ["analysis_target.bvid", "analysis_target.cid"],
            name="fk_video_declaration_target",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("bvid", "cid", name="pk_video_declaration"),
    )

    op.create_table(
        "analysis_attempt",
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bvid", sa.Text(), nullable=False),
        sa.Column("cid", sa.BigInteger(), nullable=False),
        sa.Column("analysis_version", sa.Text(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("dispatch_epoch", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("cid > 0", name="ck_analysis_attempt_cid_positive"),
        sa.CheckConstraint("generation > 0", name="ck_analysis_attempt_generation_positive"),
        sa.CheckConstraint(
            "dispatch_epoch >= 0",
            name="ck_analysis_attempt_dispatch_epoch_nonnegative",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'fetching', 'analyzing', 'completed', 'failed')",
            name="ck_analysis_attempt_status_known",
        ),
        sa.ForeignKeyConstraint(
            ["bvid", "cid"],
            ["analysis_target.bvid", "analysis_target.cid"],
            name="fk_analysis_attempt_target",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("attempt_id", name="pk_analysis_attempt"),
    )
    op.create_index(
        "uq_analysis_attempt_active_version",
        "analysis_attempt",
        ["bvid", "cid", "analysis_version"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'fetching', 'analyzing')"),
    )
    op.create_index(
        "ix_analysis_attempt_recovery_lease",
        "analysis_attempt",
        ["status", "lease_expires_at"],
    )
    op.create_index(
        "ix_analysis_attempt_retry_after",
        "analysis_attempt",
        ["status", "retry_after"],
    )
    op.create_foreign_key(
        "fk_analysis_target_owner_attempt",
        "analysis_target",
        "analysis_attempt",
        ["owner_attempt_id"],
        ["attempt_id"],
    )

    op.create_table(
        "analysis_outbox",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("dispatch_epoch", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("generation > 0", name="ck_analysis_outbox_generation_positive"),
        sa.CheckConstraint(
            "dispatch_epoch >= 0",
            name="ck_analysis_outbox_dispatch_epoch_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["analysis_attempt.attempt_id"],
            name="fk_analysis_outbox_attempt",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", name="pk_analysis_outbox"),
        sa.UniqueConstraint(
            "attempt_id",
            "generation",
            "dispatch_epoch",
            name="uq_analysis_outbox_delivery_key",
        ),
    )
    op.create_index(
        "ix_analysis_outbox_pending",
        "analysis_outbox",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("delivered_at IS NULL"),
    )

    op.create_table(
        "video_metadata",
        sa.Column("bvid", sa.Text(), nullable=False),
        sa.Column("default_cid", sa.BigInteger(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("default_cid > 0", name="ck_video_metadata_default_cid_positive"),
        sa.PrimaryKeyConstraint("bvid", name="pk_video_metadata"),
    )

    op.create_table(
        "installation_token",
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("token_id", name="pk_installation_token"),
        sa.UniqueConstraint("token_hash", name="uq_installation_token_hash"),
    )


def downgrade() -> None:
    op.drop_table("installation_token")
    op.drop_table("video_metadata")
    op.drop_table("analysis_outbox")
    op.drop_constraint(
        "fk_analysis_target_owner_attempt",
        "analysis_target",
        type_="foreignkey",
    )
    op.drop_table("analysis_attempt")
    op.drop_table("video_declaration")
    op.drop_table("analysis_result")
    op.drop_table("analysis_target")
