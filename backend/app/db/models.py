from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AnalysisTarget(Base):
    __tablename__ = "analysis_target"
    __table_args__ = (
        CheckConstraint("cid > 0", name="ck_analysis_target_cid_positive"),
        CheckConstraint(
            "write_generation > 0", name="ck_analysis_target_write_generation_positive"
        ),
    )

    bvid: Mapped[str] = mapped_column(Text, primary_key=True)
    cid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    desired_analysis_version: Mapped[str] = mapped_column(Text, nullable=False)
    write_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner_attempt_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "analysis_attempt.attempt_id",
            name="fk_analysis_target_owner_attempt",
            use_alter=True,
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AnalysisResult(Base):
    __tablename__ = "analysis_result"
    __table_args__ = (
        ForeignKeyConstraint(
            ["bvid", "cid"],
            ["analysis_target.bvid", "analysis_target.cid"],
            name="fk_analysis_result_target",
            ondelete="CASCADE",
        ),
        CheckConstraint("cid > 0", name="ck_analysis_result_cid_positive"),
        CheckConstraint("score BETWEEN 0 AND 100", name="ck_analysis_result_score_range"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_analysis_result_confidence_range"),
        CheckConstraint(
            "label IN ('none', 'light', 'medium', 'high')",
            name="ck_analysis_result_label_known",
        ),
        CheckConstraint(
            "analysis_expires_at >= analyzed_at", name="ck_analysis_result_expiry_order"
        ),
    )

    bvid: Mapped[str] = mapped_column(Text, primary_key=True)
    cid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(nullable=False)
    evidence_json: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    analysis_version: Mapped[str] = mapped_column(Text, nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    analysis_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VideoDeclaration(Base):
    __tablename__ = "video_declaration"
    __table_args__ = (
        ForeignKeyConstraint(
            ["bvid", "cid"],
            ["analysis_target.bvid", "analysis_target.cid"],
            name="fk_video_declaration_target",
            ondelete="CASCADE",
        ),
        CheckConstraint("cid > 0", name="ck_video_declaration_cid_positive"),
        CheckConstraint(
            "state IN ('declared_ai', 'not_declared', 'unknown')",
            name="ck_video_declaration_state_known",
        ),
        CheckConstraint("expires_at >= checked_at", name="ck_video_declaration_expiry_order"),
    )

    bvid: Mapped[str] = mapped_column(Text, primary_key=True)
    cid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnalysisAttempt(Base):
    __tablename__ = "analysis_attempt"
    __table_args__ = (
        ForeignKeyConstraint(
            ["bvid", "cid"],
            ["analysis_target.bvid", "analysis_target.cid"],
            name="fk_analysis_attempt_target",
            ondelete="CASCADE",
        ),
        CheckConstraint("cid > 0", name="ck_analysis_attempt_cid_positive"),
        CheckConstraint("generation > 0", name="ck_analysis_attempt_generation_positive"),
        CheckConstraint(
            "dispatch_epoch >= 0",
            name="ck_analysis_attempt_dispatch_epoch_nonnegative",
        ),
        CheckConstraint(
            "status IN ('queued', 'fetching', 'analyzing', 'completed', 'failed')",
            name="ck_analysis_attempt_status_known",
        ),
        Index(
            "uq_analysis_attempt_active_version",
            "bvid",
            "cid",
            "analysis_version",
            unique=True,
            postgresql_where=text("status IN ('queued', 'fetching', 'analyzing')"),
        ),
        Index("ix_analysis_attempt_recovery_lease", "status", "lease_expires_at"),
        Index("ix_analysis_attempt_retry_after", "status", "retry_after"),
    )

    attempt_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    bvid: Mapped[str] = mapped_column(Text, nullable=False)
    cid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    analysis_version: Mapped[str] = mapped_column(Text, nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    dispatch_epoch: Mapped[int] = mapped_column(
        BigInteger, server_default=text("0"), nullable=False
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AnalysisOutbox(Base):
    __tablename__ = "analysis_outbox"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id",
            "generation",
            "dispatch_epoch",
            name="uq_analysis_outbox_delivery_key",
        ),
        CheckConstraint("generation > 0", name="ck_analysis_outbox_generation_positive"),
        CheckConstraint(
            "dispatch_epoch >= 0",
            name="ck_analysis_outbox_dispatch_epoch_nonnegative",
        ),
        Index(
            "ix_analysis_outbox_pending",
            "created_at",
            postgresql_where=text("delivered_at IS NULL"),
        ),
    )

    event_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    attempt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "analysis_attempt.attempt_id", name="fk_analysis_outbox_attempt", ondelete="CASCADE"
        ),
        nullable=False,
    )
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dispatch_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VideoMetadata(Base):
    __tablename__ = "video_metadata"
    __table_args__ = (
        CheckConstraint("default_cid > 0", name="ck_video_metadata_default_cid_positive"),
    )

    bvid: Mapped[str] = mapped_column(Text, primary_key=True)
    default_cid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InstallationToken(Base):
    __tablename__ = "installation_token"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_installation_token_hash"),)

    token_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
