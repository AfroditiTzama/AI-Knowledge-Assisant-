import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from knowledge_assistant.domain.documents.chunk_entities import (
    DocumentChunkEntity,
)
from knowledge_assistant.domain.documents.chunk_repository import (
    DocumentChunkRepository,
)
from knowledge_assistant.domain.documents.entities import Document
from knowledge_assistant.domain.documents.file_storage import FileStorage
from knowledge_assistant.domain.documents.repository import DocumentRepository
from knowledge_assistant.domain.documents.text_chunker import (
    DocumentChunk,
    DocumentTextChunker,
)
from knowledge_assistant.domain.documents.text_extractor import (
    DocumentTextExtractor,
    ExtractedDocument,
    ExtractedTextSegment,
)
from knowledge_assistant.domain.embeddings.service import EmbeddingService
from knowledge_assistant.domain.jobs.entities import ProcessingJobStage
from knowledge_assistant.domain.vector_store.store import (
    VectorRecord,
    VectorStore,
)

ProgressCallback = Callable[
    [ProcessingJobStage, int],
    Awaitable[None],
]


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessDocumentResult:
    document: Document
    extracted_document: ExtractedDocument
    chunks: tuple[DocumentChunk, ...]
    ingestion_generation: UUID
    previous_ingestion_generation: UUID | None


class ProcessDocumentCommand:
    def __init__(
        self,
        document_repository: DocumentRepository,
        document_chunk_repository: DocumentChunkRepository,
        file_storage: FileStorage,
        text_extractor: DocumentTextExtractor,
        text_chunker: DocumentTextChunker,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
    ) -> None:
        self._document_repository = document_repository
        self._document_chunk_repository = document_chunk_repository
        self._file_storage = file_storage
        self._text_extractor = text_extractor
        self._text_chunker = text_chunker
        self._embedding_service = embedding_service
        self._vector_store = vector_store

    async def execute(
        self,
        *,
        document_id: UUID,
        owner_id: UUID,
        ingestion_generation: UUID | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> ProcessDocumentResult:
        document = await self._document_repository.get_by_id(document_id)

        if document is None or document.owner_id != owner_id:
            raise ValueError("Document was not found.")

        generation = ingestion_generation or uuid4()
        if document.active_ingestion_generation == generation:
            active_entities = (
                await self._document_chunk_repository.list_by_document_id(
                    document.id
                )
            )
            active_chunks = tuple(
                DocumentChunk(
                    index=chunk.chunk_index,
                    text=chunk.text,
                    page_number=chunk.page_number,
                )
                for chunk in active_entities
            )
            return ProcessDocumentResult(
                document=document,
                extracted_document=ExtractedDocument(
                    segments=tuple(
                        ExtractedTextSegment(
                            text=chunk.text,
                            page_number=chunk.page_number,
                        )
                        for chunk in active_entities
                    )
                ),
                chunks=active_chunks,
                ingestion_generation=generation,
                previous_ingestion_generation=generation,
            )

        previous_generation = document.active_ingestion_generation

        document.mark_as_processing()
        document = await self._document_repository.update(document)

        try:
            await self._report(
                progress_callback,
                ProcessingJobStage.EXTRACTING,
                10,
            )
            file_content = await self._file_storage.read(
                document.storage_path
            )

            extracted_document = await self._text_extractor.extract(
                file_content=file_content,
                original_filename=document.original_filename,
                content_type=document.content_type,
            )

            await self._report(
                progress_callback,
                ProcessingJobStage.CHUNKING,
                40,
            )
            chunks = self._text_chunker.chunk(extracted_document)

            if not chunks:
                raise ValueError(
                    "No text chunks were created from the document."
                )

            chunk_entities = tuple(
                DocumentChunkEntity(
                    id=uuid5(
                        NAMESPACE_URL,
                        f"{document.id}:{generation}:{chunk.index}",
                    ),
                    document_id=document.id,
                    chunk_index=chunk.index,
                    text=chunk.text.strip(),
                    page_number=chunk.page_number,
                )
                for chunk in chunks
            )

            await self._report(
                progress_callback,
                ProcessingJobStage.EMBEDDING,
                60,
            )
            embeddings = await self._embedding_service.embed_documents(
                [chunk.text for chunk in chunk_entities]
            )

            if len(embeddings) != len(chunk_entities):
                raise ValueError(
                    "Embedding count does not match chunk count."
                )

            await self._report(
                progress_callback,
                ProcessingJobStage.PERSISTING,
                85,
            )
            vector_records = tuple(
                VectorRecord(
                    id=str(chunk_entity.id),
                    owner_id=document.owner_id,
                    document_id=document.id,
                    chunk_index=chunk_entity.chunk_index,
                    text=chunk_entity.text,
                    page_number=chunk_entity.page_number,
                    embedding=embedding,
                )
                for chunk_entity, embedding in zip(
                    chunk_entities,
                    embeddings,
                    strict=True,
                )
            )

            await self._vector_store.stage_document_records(
                owner_id=document.owner_id,
                document_id=document.id,
                ingestion_generation=generation,
                records=vector_records,
            )

            await self._document_chunk_repository.replace_for_document(
                document_id=document.id,
                chunks=chunk_entities,
            )

            document.mark_as_processed(generation)
            document = await self._document_repository.update(document)

            return ProcessDocumentResult(
                document=document,
                extracted_document=extracted_document,
                chunks=chunks,
                ingestion_generation=generation,
                previous_ingestion_generation=previous_generation,
            )

        except Exception:
            if document.active_ingestion_generation != generation:
                try:
                    await self._vector_store.delete_document_generation(
                        owner_id=document.owner_id,
                        document_id=document.id,
                        ingestion_generation=generation,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Could not clean staged vector generation %s for document %s.",
                        generation,
                        document.id,
                    )
            document.mark_as_failed()
            await self._document_repository.update(document)
            raise

    @staticmethod
    async def _report(
        callback: ProgressCallback | None,
        stage: ProcessingJobStage,
        progress: int,
    ) -> None:
        if callback is not None:
            await callback(stage, progress)
