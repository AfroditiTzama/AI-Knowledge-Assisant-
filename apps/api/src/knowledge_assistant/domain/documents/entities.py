from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4


class DocumentStatus(str, Enum):  # noqa: UP042
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


LEGACY_INGESTION_GENERATION = UUID(int=0)


@dataclass
class Document:
    id: UUID
    owner_id: UUID
    original_filename: str
    stored_filename: str
    storage_path: str
    content_type: str | None
    size_bytes: int
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime
    active_ingestion_generation: UUID | None = None

    def __post_init__(self) -> None:
        if not self.original_filename.strip():
            raise ValueError("Original filename cannot be empty.")

        if not self.stored_filename.strip():
            raise ValueError("Stored filename cannot be empty.")

        if not self.storage_path.strip():
            raise ValueError("Storage path cannot be empty.")

        if self.size_bytes < 0:
            raise ValueError("Document size cannot be negative.")

    @classmethod
    def create(
        cls,
        *,
        owner_id: UUID,
        original_filename: str,
        stored_filename: str,
        storage_path: str,
        content_type: str | None,
        size_bytes: int,
    ) -> "Document":
        now = datetime.now(UTC)

        return cls(
            id=uuid4(),
            owner_id=owner_id,
            original_filename=original_filename.strip(),
            stored_filename=stored_filename.strip(),
            storage_path=storage_path.strip(),
            content_type=content_type,
            size_bytes=size_bytes,
            status=DocumentStatus.UPLOADED,
            created_at=now,
            updated_at=now,
        )

    def mark_as_queued(self) -> None:
        self.status = DocumentStatus.QUEUED
        self._touch()

    def mark_as_processing(self) -> None:
        self.status = DocumentStatus.PROCESSING
        self._touch()

    def mark_as_processed(
        self,
        ingestion_generation: UUID | None = None,
    ) -> None:
        if ingestion_generation is not None:
            self.active_ingestion_generation = ingestion_generation
        self.status = DocumentStatus.PROCESSED
        self._touch()

    def mark_as_failed(self) -> None:
        self.status = DocumentStatus.FAILED
        self._touch()

    def _touch(self) -> None:
        self.updated_at = datetime.now(UTC)
