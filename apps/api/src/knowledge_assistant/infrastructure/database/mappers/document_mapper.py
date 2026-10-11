from knowledge_assistant.domain.documents.entities import Document
from knowledge_assistant.infrastructure.database.models.document import (
    DocumentModel,
)


class DocumentMapper:
    @staticmethod
    def to_domain(model: DocumentModel) -> Document:
        return Document(
            id=model.id,
            owner_id=model.owner_id,
            original_filename=model.original_filename,
            stored_filename=model.stored_filename,
            storage_path=model.storage_path,
            content_type=model.content_type,
            size_bytes=model.size_bytes,
            status=model.status,
            created_at=model.created_at,
            updated_at=model.updated_at,
            active_ingestion_generation=(
                model.active_ingestion_generation
            ),
        )

    @staticmethod
    def to_model(entity: Document) -> DocumentModel:
        return DocumentModel(
            id=entity.id,
            owner_id=entity.owner_id,
            original_filename=entity.original_filename,
            stored_filename=entity.stored_filename,
            storage_path=entity.storage_path,
            content_type=entity.content_type,
            size_bytes=entity.size_bytes,
            status=entity.status,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            active_ingestion_generation=(
                entity.active_ingestion_generation
            ),
        )
