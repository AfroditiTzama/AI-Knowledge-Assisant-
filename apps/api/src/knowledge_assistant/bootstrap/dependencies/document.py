from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge_assistant.application.documents.commands.delete_document import (
    DeleteDocumentCommand,
)
from knowledge_assistant.application.documents.commands.process_document import (
    ProcessDocumentCommand,
)
from knowledge_assistant.application.documents.commands.upload_document import (
    UploadDocumentCommand,
)
from knowledge_assistant.application.documents.queries.get_document_chunk_preview import (
    GetDocumentChunkPreviewQuery,
)
from knowledge_assistant.application.documents.queries.list_documents import (
    ListDocumentsQuery,
)
from knowledge_assistant.core.config import get_settings
from knowledge_assistant.domain.documents.chunk_repository import (
    DocumentChunkRepository,
)
from knowledge_assistant.domain.documents.file_storage import FileStorage
from knowledge_assistant.domain.documents.repository import DocumentRepository
from knowledge_assistant.domain.documents.text_chunker import (
    DocumentTextChunker,
)
from knowledge_assistant.domain.documents.text_extractor import (
    DocumentTextExtractor,
)
from knowledge_assistant.domain.embeddings.service import EmbeddingService
from knowledge_assistant.domain.vector_store.store import VectorStore
from knowledge_assistant.infrastructure.database.repositories.document_chunk_repository import (
    SQLAlchemyDocumentChunkRepository,
)
from knowledge_assistant.infrastructure.database.repositories.document_repository import (
    SQLAlchemyDocumentRepository,
)
from knowledge_assistant.infrastructure.database.session import get_db_session
from knowledge_assistant.infrastructure.documents.chunkers.recursive_text_chunker import (
    RecursiveTextChunker,
)
from knowledge_assistant.infrastructure.documents.text_extractors.composite_text_extractor import (
    CompositeDocumentTextExtractor,
)
from knowledge_assistant.infrastructure.embeddings.sentence_transformer_service import (
    SentenceTransformerEmbeddingService,
)
from knowledge_assistant.infrastructure.storage.local_file_storage import (
    LocalFileStorage,
)
from knowledge_assistant.infrastructure.vector_store.chroma_store import (
    ChromaVectorStore,
)


def get_document_repository(
    session: Annotated[
        AsyncSession,
        Depends(get_db_session),
    ],
) -> DocumentRepository:
    return SQLAlchemyDocumentRepository(session)


def get_document_chunk_repository(
    session: Annotated[
        AsyncSession,
        Depends(get_db_session),
    ],
) -> DocumentChunkRepository:
    return SQLAlchemyDocumentChunkRepository(session)


@lru_cache
def get_file_storage() -> FileStorage:
    settings = get_settings()
    return LocalFileStorage(
        storage_directory=settings.documents_storage_directory,
    )


@lru_cache
def get_document_text_extractor() -> DocumentTextExtractor:
    settings = get_settings()
    return CompositeDocumentTextExtractor(
        max_pdf_pages=settings.document_max_pdf_pages,
        max_extracted_text_characters=(
            settings.document_max_extracted_text_characters
        ),
        max_docx_uncompressed_bytes=(
            settings.document_max_docx_uncompressed_bytes
        ),
        max_docx_archive_entries=(
            settings.document_max_docx_archive_entries
        ),
        max_docx_compression_ratio=(
            settings.document_max_docx_compression_ratio
        ),
    )


@lru_cache
def get_document_text_chunker() -> DocumentTextChunker:
    return RecursiveTextChunker(
        chunk_size=1000,
        chunk_overlap=150,
    )


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return SentenceTransformerEmbeddingService()


@lru_cache
def get_vector_store() -> VectorStore:
    settings = get_settings()
    return ChromaVectorStore(
        storage_directory=settings.chroma_storage_directory,
        collection_name="document_chunks",
    )


def get_document_chunk_preview_query(
    document_repository: Annotated[
        DocumentRepository,
        Depends(get_document_repository),
    ],
    document_chunk_repository: Annotated[
        DocumentChunkRepository,
        Depends(get_document_chunk_repository),
    ],
) -> GetDocumentChunkPreviewQuery:
    return GetDocumentChunkPreviewQuery(
        document_repository=document_repository,
        document_chunk_repository=document_chunk_repository,
    )


def get_upload_document_command(
    document_repository: Annotated[
        DocumentRepository,
        Depends(get_document_repository),
    ],
    file_storage: Annotated[
        FileStorage,
        Depends(get_file_storage),
    ],
) -> UploadDocumentCommand:
    settings = get_settings()
    return UploadDocumentCommand(
        document_repository=document_repository,
        file_storage=file_storage,
        max_docx_uncompressed_bytes=(
            settings.document_max_docx_uncompressed_bytes
        ),
        max_docx_archive_entries=(
            settings.document_max_docx_archive_entries
        ),
        max_docx_compression_ratio=(
            settings.document_max_docx_compression_ratio
        ),
    )


def get_process_document_command(
    document_repository: Annotated[
        DocumentRepository,
        Depends(get_document_repository),
    ],
    document_chunk_repository: Annotated[
        DocumentChunkRepository,
        Depends(get_document_chunk_repository),
    ],
    file_storage: Annotated[
        FileStorage,
        Depends(get_file_storage),
    ],
    text_extractor: Annotated[
        DocumentTextExtractor,
        Depends(get_document_text_extractor),
    ],
    text_chunker: Annotated[
        DocumentTextChunker,
        Depends(get_document_text_chunker),
    ],
    embedding_service: Annotated[
        EmbeddingService,
        Depends(get_embedding_service),
    ],
    vector_store: Annotated[
        VectorStore,
        Depends(get_vector_store),
    ],
) -> ProcessDocumentCommand:
    return ProcessDocumentCommand(
        document_repository=document_repository,
        document_chunk_repository=document_chunk_repository,
        file_storage=file_storage,
        text_extractor=text_extractor,
        text_chunker=text_chunker,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )


def get_delete_document_command(
    document_repository: Annotated[
        DocumentRepository,
        Depends(get_document_repository),
    ],
    file_storage: Annotated[
        FileStorage,
        Depends(get_file_storage),
    ],
    vector_store: Annotated[
        VectorStore,
        Depends(get_vector_store),
    ],
) -> DeleteDocumentCommand:
    return DeleteDocumentCommand(
        document_repository=document_repository,
        file_storage=file_storage,
        vector_store=vector_store,
    )


def get_list_documents_query(
    document_repository: Annotated[
        DocumentRepository,
        Depends(get_document_repository),
    ],
) -> ListDocumentsQuery:
    return ListDocumentsQuery(
        document_repository=document_repository,
    )


UploadDocumentCommandDependency = Annotated[
    UploadDocumentCommand,
    Depends(get_upload_document_command),
]

ProcessDocumentCommandDependency = Annotated[
    ProcessDocumentCommand,
    Depends(get_process_document_command),
]

DeleteDocumentCommandDependency = Annotated[
    DeleteDocumentCommand,
    Depends(get_delete_document_command),
]

ListDocumentsQueryDependency = Annotated[
    ListDocumentsQuery,
    Depends(get_list_documents_query),
]

GetDocumentChunkPreviewQueryDependency = Annotated[
    GetDocumentChunkPreviewQuery,
    Depends(get_document_chunk_preview_query),
]
