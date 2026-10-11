import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from knowledge_assistant.application.documents.commands.process_document import (
    ProcessDocumentCommand,
)
from knowledge_assistant.domain.documents.chunk_entities import DocumentChunkEntity
from knowledge_assistant.domain.documents.entities import (
    LEGACY_INGESTION_GENERATION,
    Document,
    DocumentStatus,
)
from knowledge_assistant.domain.documents.text_chunker import DocumentChunk
from knowledge_assistant.domain.documents.text_extractor import (
    ExtractedDocument,
    ExtractedTextSegment,
)
from knowledge_assistant.domain.jobs.entities import ProcessingJob, ProcessingJobStatus
from knowledge_assistant.domain.vector_store.store import VectorRecord
from knowledge_assistant.infrastructure.database.base import Base
from knowledge_assistant.infrastructure.database.models.document import DocumentModel  # noqa: F401
from knowledge_assistant.infrastructure.database.models.document_chunk import (  # noqa: F401
    DocumentChunkModel,
)
from knowledge_assistant.infrastructure.database.models.processing_job import (  # noqa: F401
    ProcessingJobModel,
)
from knowledge_assistant.infrastructure.database.models.user import UserModel  # noqa: F401
from knowledge_assistant.infrastructure.database.repositories.document_chunk_repository import (
    SQLAlchemyDocumentChunkRepository,
)
from knowledge_assistant.infrastructure.database.repositories.document_repository import (
    SQLAlchemyDocumentRepository,
)
from knowledge_assistant.infrastructure.database.repositories.processing_job_repository import (
    SQLAlchemyProcessingJobRepository,
)
from knowledge_assistant.infrastructure.vector_store.chroma_store import ChromaVectorStore


class MemoryDocumentRepository:
    def __init__(self, document: Document) -> None:
        self.document = document
        self.statuses: list[DocumentStatus] = []

    async def get_by_id(self, document_id: UUID) -> Document | None:
        return self.document if self.document.id == document_id else None

    async def update(self, document: Document) -> Document:
        self.document = document
        self.statuses.append(document.status)
        return document


class MemoryChunkRepository:
    def __init__(self, chunks: tuple[DocumentChunkEntity, ...] = ()) -> None:
        self.chunks = chunks
        self.replace_calls = 0

    async def replace_for_document(
        self,
        *,
        document_id: UUID,
        chunks: tuple[DocumentChunkEntity, ...],
    ) -> None:
        assert all(chunk.document_id == document_id for chunk in chunks)
        self.replace_calls += 1
        self.chunks = chunks

    async def list_by_document_id(
        self,
        document_id: UUID,
    ) -> list[DocumentChunkEntity]:
        return [chunk for chunk in self.chunks if chunk.document_id == document_id]


class MemoryVectorStore:
    def __init__(self, *, fail_staging: bool = False) -> None:
        self.fail_staging = fail_staging
        self.generations: dict[
            tuple[UUID, UUID, UUID], tuple[VectorRecord, ...]
        ] = {}
        self.stage_calls = 0

    async def stage_document_records(
        self,
        *,
        owner_id: UUID,
        document_id: UUID,
        ingestion_generation: UUID,
        records: tuple[VectorRecord, ...],
    ) -> None:
        self.stage_calls += 1
        key = (owner_id, document_id, ingestion_generation)
        self.generations[key] = records[:1] if self.fail_staging else records
        if self.fail_staging:
            raise RuntimeError("injected vector failure")

    async def delete_document_generation(
        self,
        *,
        owner_id: UUID,
        document_id: UUID,
        ingestion_generation: UUID,
    ) -> None:
        self.generations.pop((owner_id, document_id, ingestion_generation), None)

    async def cleanup_inactive_document_records(
        self,
        *,
        owner_id: UUID,
        document_id: UUID,
        active_ingestion_generation: UUID | None,
    ) -> None:
        inactive = [
            key
            for key in self.generations
            if key[:2] == (owner_id, document_id)
            and key[2] != active_ingestion_generation
        ]
        for key in inactive:
            self.generations.pop(key)


class StaticFileStorage:
    async def read(self, storage_path: str) -> bytes:
        return b"document"


class StaticExtractor:
    async def extract(self, **kwargs) -> ExtractedDocument:
        return ExtractedDocument(
            segments=(ExtractedTextSegment(text="new content", page_number=1),)
        )


class StaticChunker:
    def chunk(self, extracted_document: ExtractedDocument) -> tuple[DocumentChunk, ...]:
        return (
            DocumentChunk(index=0, text="new content", page_number=1),
            DocumentChunk(index=1, text="more content", page_number=1),
        )


class StaticEmbeddingService:
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(index), 1.0] for index, _ in enumerate(texts)]


def make_document(
    *,
    owner_id: UUID | None = None,
    active_generation: UUID | None = None,
) -> Document:
    now = datetime.now(UTC)
    return Document(
        id=uuid4(),
        owner_id=owner_id or uuid4(),
        original_filename="document.txt",
        stored_filename="document.txt",
        storage_path="document.txt",
        content_type="text/plain",
        size_bytes=8,
        status=(
            DocumentStatus.PROCESSED
            if active_generation is not None
            else DocumentStatus.UPLOADED
        ),
        created_at=now,
        updated_at=now,
        active_ingestion_generation=active_generation,
    )


def make_command(
    document: Document,
    chunks: MemoryChunkRepository,
    vectors: MemoryVectorStore,
) -> ProcessDocumentCommand:
    return ProcessDocumentCommand(
        document_repository=MemoryDocumentRepository(document),
        document_chunk_repository=chunks,
        file_storage=StaticFileStorage(),
        text_extractor=StaticExtractor(),
        text_chunker=StaticChunker(),
        embedding_service=StaticEmbeddingService(),
        vector_store=vectors,
    )


@pytest.mark.asyncio
async def test_successful_ingestion_activates_verified_generation() -> None:
    document = make_document()
    generation = uuid4()
    chunks = MemoryChunkRepository()
    vectors = MemoryVectorStore()

    result = await make_command(document, chunks, vectors).execute(
        document_id=document.id,
        owner_id=document.owner_id,
        ingestion_generation=generation,
    )

    assert result.document.status is DocumentStatus.PROCESSED
    assert result.document.active_ingestion_generation == generation
    assert len(chunks.chunks) == 2
    assert len(vectors.generations[(document.owner_id, document.id, generation)]) == 2


@pytest.mark.asyncio
async def test_vector_failure_preserves_previous_active_generation() -> None:
    active_generation = uuid4()
    document = make_document(active_generation=active_generation)
    old_chunk = DocumentChunkEntity.create(
        document_id=document.id,
        chunk_index=0,
        text="old content",
        page_number=1,
    )
    chunks = MemoryChunkRepository((old_chunk,))
    vectors = MemoryVectorStore(fail_staging=True)
    vectors.generations[(document.owner_id, document.id, active_generation)] = (
        VectorRecord(
            id=str(old_chunk.id),
            owner_id=document.owner_id,
            document_id=document.id,
            chunk_index=0,
            text=old_chunk.text,
            page_number=1,
            embedding=[0.0, 1.0],
        ),
    )
    failed_generation = uuid4()

    with pytest.raises(RuntimeError, match="injected vector failure"):
        await make_command(document, chunks, vectors).execute(
            document_id=document.id,
            owner_id=document.owner_id,
            ingestion_generation=failed_generation,
        )

    assert chunks.chunks == (old_chunk,)
    assert document.status is DocumentStatus.FAILED
    assert document.active_ingestion_generation == active_generation
    assert (document.owner_id, document.id, failed_generation) not in vectors.generations
    assert (document.owner_id, document.id, active_generation) in vectors.generations


@pytest.mark.asyncio
async def test_repeating_active_job_is_idempotent() -> None:
    document = make_document()
    generation = uuid4()
    chunks = MemoryChunkRepository()
    vectors = MemoryVectorStore()
    command = make_command(document, chunks, vectors)

    first = await command.execute(
        document_id=document.id,
        owner_id=document.owner_id,
        ingestion_generation=generation,
    )
    first_ids = [chunk.id for chunk in chunks.chunks]
    second = await command.execute(
        document_id=document.id,
        owner_id=document.owner_id,
        ingestion_generation=generation,
    )

    assert vectors.stage_calls == 1
    assert chunks.replace_calls == 1
    assert [chunk.id for chunk in chunks.chunks] == first_ids
    assert second.ingestion_generation == first.ingestion_generation


async def create_session_factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ingestion.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_successful_ingestion_commits_chunks_and_activation_together(
    tmp_path: Path,
) -> None:
    engine, sessions = await create_session_factory(tmp_path)
    document = make_document()
    generation = uuid4()
    try:
        async with sessions() as session:
            await SQLAlchemyDocumentRepository(session).add(document)
            await session.commit()

        async with sessions() as session:
            result = await ProcessDocumentCommand(
                document_repository=SQLAlchemyDocumentRepository(session),
                document_chunk_repository=SQLAlchemyDocumentChunkRepository(session),
                file_storage=StaticFileStorage(),
                text_extractor=StaticExtractor(),
                text_chunker=StaticChunker(),
                embedding_service=StaticEmbeddingService(),
                vector_store=MemoryVectorStore(),
            ).execute(
                document_id=document.id,
                owner_id=document.owner_id,
                ingestion_generation=generation,
            )
            await session.commit()
        assert result.ingestion_generation == generation

        async with sessions() as session:
            stored_document = await SQLAlchemyDocumentRepository(session).get_by_id(
                document.id
            )
            stored_chunks = await SQLAlchemyDocumentChunkRepository(
                session
            ).list_by_document_id(document.id)
        assert stored_document is not None
        assert stored_document.active_ingestion_generation == generation
        assert stored_document.status is DocumentStatus.PROCESSED
        assert [chunk.text for chunk in stored_chunks] == [
            "new content",
            "more content",
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_chunk_failure_rolls_back_partial_sql_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, sessions = await create_session_factory(tmp_path)
    document = make_document(active_generation=uuid4())
    old_chunk = DocumentChunkEntity.create(
        document_id=document.id,
        chunk_index=0,
        text="old content",
        page_number=1,
    )
    try:
        async with sessions() as session:
            documents = SQLAlchemyDocumentRepository(session)
            chunks = SQLAlchemyDocumentChunkRepository(session)
            await documents.add(document)
            await chunks.replace_for_document(
                document_id=document.id,
                chunks=(old_chunk,),
            )
            await session.commit()

        class FailingChunkRepository(SQLAlchemyDocumentChunkRepository):
            async def replace_for_document(self, **kwargs) -> None:
                await super().replace_for_document(**kwargs)
                raise RuntimeError("injected chunk failure")

        vectors = MemoryVectorStore()
        failed_generation = uuid4()
        async with sessions() as session:
            command = ProcessDocumentCommand(
                document_repository=SQLAlchemyDocumentRepository(session),
                document_chunk_repository=FailingChunkRepository(session),
                file_storage=StaticFileStorage(),
                text_extractor=StaticExtractor(),
                text_chunker=StaticChunker(),
                embedding_service=StaticEmbeddingService(),
                vector_store=vectors,
            )
            with pytest.raises(RuntimeError, match="injected chunk failure"):
                await command.execute(
                    document_id=document.id,
                    owner_id=document.owner_id,
                    ingestion_generation=failed_generation,
                )
            await session.rollback()

        from knowledge_assistant.infrastructure.jobs import local_processing_worker

        monkeypatch.setattr(
            local_processing_worker,
            "AsyncSessionFactory",
            sessions,
        )
        monkeypatch.setattr(
            local_processing_worker,
            "get_vector_store",
            lambda: vectors,
        )
        await local_processing_worker.LocalProcessingWorker()._mark_document_failed(
            document_id=document.id,
            owner_id=document.owner_id,
        )

        async with sessions() as session:
            stored_document = await SQLAlchemyDocumentRepository(session).get_by_id(
                document.id
            )
            stored_chunks = await SQLAlchemyDocumentChunkRepository(
                session
            ).list_by_document_id(document.id)
        assert stored_document is not None
        assert stored_document.status is DocumentStatus.FAILED
        assert stored_document.active_ingestion_generation == (
            document.active_ingestion_generation
        )
        assert [chunk.text for chunk in stored_chunks] == ["old content"]
        assert (document.owner_id, document.id, failed_generation) not in (
            vectors.generations
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_interrupted_job_is_recovered_without_consuming_attempt(tmp_path: Path) -> None:
    engine, sessions = await create_session_factory(tmp_path)
    document = make_document()
    job = ProcessingJob.create_document_processing(
        owner_id=document.owner_id,
        document_id=document.id,
    )
    job.mark_running()
    try:
        async with sessions() as session:
            await SQLAlchemyDocumentRepository(session).add(document)
            await SQLAlchemyProcessingJobRepository(session).add(job)
            await session.commit()

        async with sessions() as session:
            repository = SQLAlchemyProcessingJobRepository(session)
            assert await repository.recover_interrupted() == 1
            await session.commit()

        async with sessions() as session:
            claimed = await SQLAlchemyProcessingJobRepository(session).claim_next_queued()
            await session.commit()
        assert claimed is not None
        assert claimed.status is ProcessingJobStatus.RUNNING
        assert claimed.attempts == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_claims_select_a_job_only_once(tmp_path: Path) -> None:
    engine, sessions = await create_session_factory(tmp_path)
    document = make_document()
    job = ProcessingJob.create_document_processing(
        owner_id=document.owner_id,
        document_id=document.id,
    )
    try:
        async with sessions() as session:
            await SQLAlchemyDocumentRepository(session).add(document)
            await SQLAlchemyProcessingJobRepository(session).add(job)
            await session.commit()

        async def claim():
            async with sessions() as session:
                result = await SQLAlchemyProcessingJobRepository(
                    session
                ).claim_next_queued()
                await session.commit()
                return result

        claimed = await asyncio.gather(claim(), claim())
        assert sum(result is not None for result in claimed) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_active_job_insert_returns_existing_job(tmp_path: Path) -> None:
    engine, sessions = await create_session_factory(tmp_path)
    document = make_document()
    first_job = ProcessingJob.create_document_processing(
        owner_id=document.owner_id,
        document_id=document.id,
    )
    duplicate_job = ProcessingJob.create_document_processing(
        owner_id=document.owner_id,
        document_id=document.id,
    )
    try:
        async with sessions() as session:
            await SQLAlchemyDocumentRepository(session).add(document)
            repository = SQLAlchemyProcessingJobRepository(session)
            saved_first = await repository.add(first_job)
            await session.commit()

        async with sessions() as session:
            saved_duplicate = await SQLAlchemyProcessingJobRepository(session).add(
                duplicate_job
            )
            await session.commit()

        assert saved_duplicate.id == saved_first.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_chroma_search_returns_only_active_owned_generation(tmp_path: Path) -> None:
    store = ChromaVectorStore(storage_directory=tmp_path / "chroma")
    owner_id = uuid4()
    other_owner_id = uuid4()
    document_id = uuid4()
    active_generation = uuid4()
    failed_generation = uuid4()

    def record(record_id: str, owner: UUID, text: str) -> VectorRecord:
        return VectorRecord(
            id=record_id,
            owner_id=owner,
            document_id=document_id,
            chunk_index=0,
            text=text,
            page_number=1,
            embedding=[1.0, 0.0],
        )

    await store.stage_document_records(
        owner_id=owner_id,
        document_id=document_id,
        ingestion_generation=active_generation,
        records=(record("active", owner_id, "active content"),),
    )
    await store.stage_document_records(
        owner_id=owner_id,
        document_id=document_id,
        ingestion_generation=failed_generation,
        records=(record("failed", owner_id, "failed content"),),
    )
    await store.stage_document_records(
        owner_id=other_owner_id,
        document_id=document_id,
        ingestion_generation=active_generation,
        records=(record("other-owner", other_owner_id, "private content"),),
    )

    results = await store.search(
        owner_id=owner_id,
        active_ingestion_generations={document_id: active_generation},
        query_embedding=[1.0, 0.0],
        limit=10,
    )

    assert [result.id for result in results] == ["active"]
    await store.cleanup_inactive_document_records(
        owner_id=owner_id,
        document_id=document_id,
        active_ingestion_generation=active_generation,
    )
    results_after_cleanup = await store.search(
        owner_id=owner_id,
        active_ingestion_generations={document_id: active_generation},
        query_embedding=[1.0, 0.0],
        limit=10,
    )
    assert [result.id for result in results_after_cleanup] == ["active"]


@pytest.mark.asyncio
async def test_legacy_vectors_remain_searchable_until_reprocessed(tmp_path: Path) -> None:
    store = ChromaVectorStore(storage_directory=tmp_path / "legacy-chroma")
    owner_id = uuid4()
    document_id = uuid4()
    store._collection.upsert(  # noqa: SLF001
        ids=["legacy"],
        embeddings=[[1.0, 0.0]],
        documents=["legacy content"],
        metadatas=[
            {
                "owner_id": str(owner_id),
                "document_id": str(document_id),
                "chunk_index": 0,
            }
        ],
    )

    results = await store.search(
        owner_id=owner_id,
        active_ingestion_generations={
            document_id: LEGACY_INGESTION_GENERATION
        },
        query_embedding=[1.0, 0.0],
        limit=5,
    )

    assert [result.id for result in results] == ["legacy"]
