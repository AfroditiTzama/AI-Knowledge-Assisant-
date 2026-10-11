import asyncio
import logging
from contextlib import suppress
from uuid import UUID

from sqlalchemy.exc import OperationalError

from knowledge_assistant.application.documents.commands.process_document import (
    ProcessDocumentCommand,
)
from knowledge_assistant.bootstrap.dependencies.document import (
    get_document_text_chunker,
    get_document_text_extractor,
    get_embedding_service,
    get_file_storage,
    get_vector_store,
)
from knowledge_assistant.domain.jobs.entities import (
    ProcessingJob,
    ProcessingJobStage,
    ProcessingJobStatus,
)
from knowledge_assistant.infrastructure.database.repositories.document_chunk_repository import (
    SQLAlchemyDocumentChunkRepository,
)
from knowledge_assistant.infrastructure.database.repositories.document_repository import (
    SQLAlchemyDocumentRepository,
)
from knowledge_assistant.infrastructure.database.repositories.processing_job_repository import (
    SQLAlchemyProcessingJobRepository,
)
from knowledge_assistant.infrastructure.database.session import AsyncSessionFactory

logger = logging.getLogger(__name__)


class LocalProcessingWorker:
    def __init__(self, *, poll_interval_seconds: float = 1.0) -> None:
        self._poll_interval_seconds = poll_interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return

        self._stop_event = asyncio.Event()
        await self._recover_interrupted_jobs()
        self._task = asyncio.create_task(
            self._run(),
            name="local-processing-worker",
        )
        logger.info("Local processing worker started.")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is None:
            return

        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Local processing worker stopped.")

    async def _recover_interrupted_jobs(self) -> None:
        async with AsyncSessionFactory() as session:
            repository = SQLAlchemyProcessingJobRepository(session)
            recovered = await repository.recover_interrupted()
            await session.commit()
        if recovered:
            logger.warning(
                "Recovered %s interrupted processing job(s).",
                recovered,
            )
        await self._cleanup_inactive_vectors()

    async def _cleanup_inactive_vectors(self) -> None:
        async with AsyncSessionFactory() as session:
            documents = await SQLAlchemyDocumentRepository(session).list_all()

        vector_store = get_vector_store()
        for document in documents:
            try:
                await vector_store.cleanup_inactive_document_records(
                    owner_id=document.owner_id,
                    document_id=document.id,
                    active_ingestion_generation=(
                        document.active_ingestion_generation
                    ),
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Could not clean inactive vectors for document %s.",
                    document.id,
                )

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            job = await self._claim_next_job()
            if job is None:
                await asyncio.sleep(self._poll_interval_seconds)
                continue

            try:
                await self._process_document(job)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                logger.exception(
                    "Processing job %s failed.",
                    job.id,
                )
                await self._mark_failed(
                    job.id,
                    self._public_error_message(error),
                )

    async def _claim_next_job(self) -> ProcessingJob | None:
        async with AsyncSessionFactory() as session:
            repository = SQLAlchemyProcessingJobRepository(session)
            job = await repository.claim_next_queued()
            await session.commit()
            return job

    async def _process_document(self, job: ProcessingJob) -> None:
        async with AsyncSessionFactory() as session:
            document_repository = SQLAlchemyDocumentRepository(session)
            chunk_repository = SQLAlchemyDocumentChunkRepository(session)
            job_repository = SQLAlchemyProcessingJobRepository(session)

            command = ProcessDocumentCommand(
                document_repository=document_repository,
                document_chunk_repository=chunk_repository,
                file_storage=get_file_storage(),
                text_extractor=get_document_text_extractor(),
                text_chunker=get_document_text_chunker(),
                embedding_service=get_embedding_service(),
                vector_store=get_vector_store(),
            )

            document = await document_repository.get_by_id(job.document_id)
            if (
                document is not None
                and document.owner_id == job.owner_id
                and document.active_ingestion_generation == job.id
            ):
                await session.rollback()
                await self._mark_completed(job.id)
                return

            async def report(
                stage: ProcessingJobStage,
                progress: int,
            ) -> None:
                # Use the same SQLite session as document processing.
                # A second writer session would block while this transaction
                # holds SQLite's single write lock.
                current_job = await job_repository.get_by_id(job.id)
                if (
                    current_job is None
                    or current_job.status != ProcessingJobStatus.RUNNING
                ):
                    return

                current_job.report_progress(
                    stage=stage,
                    progress=progress,
                )
                await job_repository.update(current_job)

                # Keep each write transaction short and make progress visible
                # to polling requests immediately.
                await session.commit()

            try:
                result = await command.execute(
                    document_id=job.document_id,
                    owner_id=job.owner_id,
                    ingestion_generation=job.id,
                    progress_callback=report,
                )
                await session.commit()
            except Exception:
                await session.rollback()
                await self._mark_document_failed(
                    document_id=job.document_id,
                    owner_id=job.owner_id,
                )
                raise

        try:
            await get_vector_store().cleanup_inactive_document_records(
                owner_id=job.owner_id,
                document_id=job.document_id,
                active_ingestion_generation=result.ingestion_generation,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Could not clean inactive vectors for document %s.",
                job.document_id,
            )

        await self._mark_completed(job.id)

    async def _mark_document_failed(
        self,
        *,
        document_id: UUID,
        owner_id: UUID,
    ) -> None:
        active_generation = None
        async with AsyncSessionFactory() as session:
            repository = SQLAlchemyDocumentRepository(session)
            document = await repository.get_by_id(document_id)
            if document is None or document.owner_id != owner_id:
                return
            document.mark_as_failed()
            await repository.update(document)
            await session.commit()
            active_generation = document.active_ingestion_generation

        try:
            await get_vector_store().cleanup_inactive_document_records(
                owner_id=owner_id,
                document_id=document_id,
                active_ingestion_generation=active_generation,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Could not clean failed ingestion vectors for document %s.",
                document_id,
            )

    async def _mark_completed(self, job_id: UUID) -> None:
        async with AsyncSessionFactory() as session:
            repository = SQLAlchemyProcessingJobRepository(session)
            job = await repository.get_by_id(job_id)
            if job is None:
                return
            job.mark_completed()
            await repository.update(job)
            await session.commit()

    async def _mark_failed(self, job_id: UUID, message: str) -> None:
        async with AsyncSessionFactory() as session:
            repository = SQLAlchemyProcessingJobRepository(session)
            job = await repository.get_by_id(job_id)
            if job is None:
                return
            job.mark_failed(message)
            await repository.update(job)
            await session.commit()

    @staticmethod
    def _public_error_message(error: Exception) -> str:
        if isinstance(error, OperationalError):
            if "database is locked" in str(error).lower():
                return (
                    "The local database was temporarily busy. "
                    "Please retry processing."
                )
            return "The local database could not complete the operation."

        if isinstance(error, ValueError):
            return str(error)

        return (
            "Document processing failed. "
            "Check the backend logs for technical details."
        )
