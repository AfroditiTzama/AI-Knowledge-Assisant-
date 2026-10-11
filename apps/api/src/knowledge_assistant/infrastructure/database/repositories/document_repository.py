from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge_assistant.domain.documents.entities import Document
from knowledge_assistant.domain.documents.repository import DocumentRepository
from knowledge_assistant.infrastructure.database.mappers.document_mapper import (
    DocumentMapper,
)
from knowledge_assistant.infrastructure.database.models.document import (
    DocumentModel,
)
from knowledge_assistant.infrastructure.database.models.document_chunk import (
    DocumentChunkModel,
)
from knowledge_assistant.infrastructure.database.models.wiki import (
    WikiPageModel,
    WikiPageRevisionModel,
    WikiPageSourceModel,
)


class SQLAlchemyDocumentRepository(DocumentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, document: Document) -> Document:
        document_model = DocumentMapper.to_model(document)
        self._session.add(document_model)
        await self._session.flush()
        await self._session.refresh(document_model)
        return DocumentMapper.to_domain(document_model)

    async def update(self, document: Document) -> Document:
        document_model = await self._session.get(
            DocumentModel,
            document.id,
        )

        if document_model is None:
            raise ValueError(f"Document not found: {document.id}")

        document_model.owner_id = document.owner_id
        document_model.original_filename = document.original_filename
        document_model.stored_filename = document.stored_filename
        document_model.storage_path = document.storage_path
        document_model.content_type = document.content_type
        document_model.size_bytes = document.size_bytes
        document_model.status = document.status
        document_model.active_ingestion_generation = (
            document.active_ingestion_generation
        )
        document_model.created_at = document.created_at
        document_model.updated_at = document.updated_at

        await self._session.flush()
        await self._session.refresh(document_model)
        return DocumentMapper.to_domain(document_model)

    async def get_by_id(
        self,
        document_id: UUID,
    ) -> Document | None:
        statement = select(DocumentModel).where(
            DocumentModel.id == document_id
        )
        result = await self._session.execute(statement)
        document_model = result.scalar_one_or_none()

        if document_model is None:
            return None

        return DocumentMapper.to_domain(document_model)

    async def list_by_owner_id(
        self,
        owner_id: UUID,
    ) -> list[Document]:
        statement = (
            select(DocumentModel)
            .where(DocumentModel.owner_id == owner_id)
            .order_by(DocumentModel.created_at.desc())
        )
        result = await self._session.execute(statement)
        document_models = result.scalars().all()

        return [
            DocumentMapper.to_domain(document_model)
            for document_model in document_models
        ]

    async def list_all(self) -> list[Document]:
        statement = select(DocumentModel).order_by(
            DocumentModel.created_at.asc()
        )
        result = await self._session.execute(statement)
        return [
            DocumentMapper.to_domain(document_model)
            for document_model in result.scalars().all()
        ]

    async def delete(self, document_id: UUID) -> None:
        chunk_result = await self._session.execute(
            select(DocumentChunkModel.id).where(
                DocumentChunkModel.document_id == document_id
            )
        )
        chunk_ids = list(chunk_result.scalars().all())

        if chunk_ids:
            await self._session.execute(
                delete(WikiPageSourceModel).where(
                    WikiPageSourceModel.chunk_id.in_(chunk_ids)
                )
            )

        await self._session.execute(
            delete(DocumentChunkModel).where(
                DocumentChunkModel.document_id == document_id
            )
        )
        await self._session.execute(
            update(WikiPageModel)
            .where(WikiPageModel.document_id == document_id)
            .values(document_id=None)
        )
        await self._session.execute(
            update(WikiPageRevisionModel)
            .where(
                WikiPageRevisionModel.triggering_document_id
                == document_id
            )
            .values(triggering_document_id=None)
        )
        await self._session.execute(
            delete(DocumentModel).where(
                DocumentModel.id == document_id
            )
        )
        await self._session.flush()
