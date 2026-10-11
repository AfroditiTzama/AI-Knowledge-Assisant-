from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class VectorRecord:
    id: str
    owner_id: UUID
    document_id: UUID
    chunk_index: int
    text: str
    page_number: int | None
    embedding: list[float]


@dataclass(frozen=True)
class VectorSearchResult:
    id: str
    document_id: UUID
    chunk_index: int
    text: str
    page_number: int | None
    score: float


class VectorStore(ABC):
    @abstractmethod
    async def stage_document_records(
        self,
        *,
        owner_id: UUID,
        document_id: UUID,
        ingestion_generation: UUID,
        records: tuple[VectorRecord, ...],
    ) -> None:
        """Idempotently write and verify one inactive vector generation."""
        raise NotImplementedError

    @abstractmethod
    async def delete_document_generation(
        self,
        *,
        owner_id: UUID,
        document_id: UUID,
        ingestion_generation: UUID,
    ) -> None:
        """Delete one explicitly identified inactive generation."""
        raise NotImplementedError

    @abstractmethod
    async def cleanup_inactive_document_records(
        self,
        *,
        owner_id: UUID,
        document_id: UUID,
        active_ingestion_generation: UUID | None,
    ) -> None:
        """Delete records that do not belong to the active generation."""
        raise NotImplementedError

    @abstractmethod
    async def search(
        self,
        *,
        owner_id: UUID,
        active_ingestion_generations: dict[UUID, UUID],
        query_embedding: list[float],
        limit: int = 5,
    ) -> tuple[VectorSearchResult, ...]:
        """Search only active document generations owned by the user."""
        raise NotImplementedError

    @abstractmethod
    async def delete_document_records(
        self,
        *,
        owner_id: UUID,
        document_id: UUID,
    ) -> None:
        """Delete all vector records belonging to one document."""
        raise NotImplementedError
