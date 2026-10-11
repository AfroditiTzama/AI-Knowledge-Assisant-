from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from knowledge_assistant.domain.jobs.entities import (
    ProcessingJobStage,
    ProcessingJobStatus,
    ProcessingJobType,
)
from knowledge_assistant.infrastructure.database.base import Base


class ProcessingJobModel(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        Index(
            "uq_processing_jobs_active_document",
            "document_id",
            unique=True,
            sqlite_where=text("status IN ('QUEUED', 'RUNNING')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_type: Mapped[ProcessingJobType] = mapped_column(
        Enum(
            ProcessingJobType,
            name="processing_job_type",
            native_enum=False,
            validate_strings=True,
        ),
        nullable=False,
        index=True,
    )
    status: Mapped[ProcessingJobStatus] = mapped_column(
        Enum(
            ProcessingJobStatus,
            name="processing_job_status",
            native_enum=False,
            validate_strings=True,
        ),
        nullable=False,
        index=True,
    )
    stage: Mapped[ProcessingJobStage] = mapped_column(
        Enum(
            ProcessingJobStage,
            name="processing_job_stage",
            native_enum=False,
            validate_strings=True,
        ),
        nullable=False,
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    error_message: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
