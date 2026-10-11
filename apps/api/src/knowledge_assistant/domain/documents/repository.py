from abc import ABC, abstractmethod
from uuid import UUID

from knowledge_assistant.domain.documents.entities import Document


class DocumentRepository(ABC):
    @abstractmethod
    async def add(self, document: Document) -> Document:
        """Persist a new document."""
        raise NotImplementedError

    @abstractmethod
    async def update(self, document: Document) -> Document:
        """Persist changes to an existing document."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, document_id: UUID) -> Document | None:
        """Return a document by its ID."""
        raise NotImplementedError

    @abstractmethod
    async def list_by_owner_id(self, owner_id: UUID) -> list[Document]:
        """Return all documents owned by a specific user."""
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[Document]:
        """Return all documents for internal maintenance."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, document_id: UUID) -> None:
        """Delete a document and its owned persistence records."""
        raise NotImplementedError
