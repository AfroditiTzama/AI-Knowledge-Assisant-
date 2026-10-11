from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4


class ProcessingJobType(str, Enum):  # noqa: UP042
    DOCUMENT_PROCESSING = "document_processing"


class ProcessingJobStatus(str, Enum):  # noqa: UP042
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProcessingJobStage(str, Enum):  # noqa: UP042
    QUEUED = "queued"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    PERSISTING = "persisting"
    COMPLETED = "completed"


@dataclass
class ProcessingJob:
    id: UUID
    owner_id: UUID
    document_id: UUID
    job_type: ProcessingJobType
    status: ProcessingJobStatus
    stage: ProcessingJobStage
    progress: int
    attempts: int
    max_attempts: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    def __post_init__(self) -> None:
        if not 0 <= self.progress <= 100:
            raise ValueError("Job progress must be between 0 and 100.")
        if self.attempts < 0:
            raise ValueError("Job attempts cannot be negative.")
        if self.max_attempts < 1:
            raise ValueError("Job max_attempts must be at least one.")

    @classmethod
    def create_document_processing(
        cls,
        *,
        owner_id: UUID,
        document_id: UUID,
        max_attempts: int = 3,
    ) -> "ProcessingJob":
        now = datetime.now(UTC)
        return cls(
            id=uuid4(),
            owner_id=owner_id,
            document_id=document_id,
            job_type=ProcessingJobType.DOCUMENT_PROCESSING,
            status=ProcessingJobStatus.QUEUED,
            stage=ProcessingJobStage.QUEUED,
            progress=0,
            attempts=0,
            max_attempts=max_attempts,
            error_message=None,
            created_at=now,
            updated_at=now,
            started_at=None,
            completed_at=None,
        )

    @property
    def is_active(self) -> bool:
        return self.status in {
            ProcessingJobStatus.QUEUED,
            ProcessingJobStatus.RUNNING,
        }

    @property
    def can_retry(self) -> bool:
        return (
            self.status == ProcessingJobStatus.FAILED
            and self.attempts < self.max_attempts
        )

    def mark_running(self) -> None:
        if self.status != ProcessingJobStatus.QUEUED:
            raise ValueError("Only queued jobs can start running.")
        now = datetime.now(UTC)
        self.status = ProcessingJobStatus.RUNNING
        self.stage = ProcessingJobStage.EXTRACTING
        self.progress = max(self.progress, 5)
        self.attempts += 1
        self.error_message = None
        self.started_at = now
        self.completed_at = None
        self.updated_at = now

    def report_progress(
        self,
        *,
        stage: ProcessingJobStage,
        progress: int,
    ) -> None:
        if self.status != ProcessingJobStatus.RUNNING:
            raise ValueError("Only running jobs can report progress.")
        if not 0 <= progress <= 99:
            raise ValueError(
                "Running job progress must be between 0 and 99."
            )
        if progress < self.progress:
            return
        self.stage = stage
        self.progress = progress
        self.updated_at = datetime.now(UTC)

    def mark_completed(self) -> None:
        now = datetime.now(UTC)
        self.status = ProcessingJobStatus.COMPLETED
        self.stage = ProcessingJobStage.COMPLETED
        self.progress = 100
        self.error_message = None
        self.completed_at = now
        self.updated_at = now

    def mark_failed(self, error_message: str) -> None:
        now = datetime.now(UTC)
        self.status = ProcessingJobStatus.FAILED
        self.error_message = error_message.strip()[:2000] or "Unknown error"
        self.completed_at = now
        self.updated_at = now

    def requeue(self) -> None:
        if not self.can_retry:
            raise ValueError("This job cannot be retried.")
        now = datetime.now(UTC)
        self.status = ProcessingJobStatus.QUEUED
        self.stage = ProcessingJobStage.QUEUED
        self.progress = 0
        self.error_message = None
        self.started_at = None
        self.completed_at = None
        self.updated_at = now

    def recover_after_restart(self) -> None:
        if self.status != ProcessingJobStatus.RUNNING:
            return
        now = datetime.now(UTC)
        self.status = ProcessingJobStatus.QUEUED
        self.stage = ProcessingJobStage.QUEUED
        self.progress = 0
        self.error_message = None
        self.attempts = max(0, self.attempts - 1)
        self.started_at = None
        self.completed_at = None
        self.updated_at = now
