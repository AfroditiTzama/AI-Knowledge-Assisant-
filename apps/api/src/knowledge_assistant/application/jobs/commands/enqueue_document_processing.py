from dataclasses import dataclass
from uuid import UUID

from knowledge_assistant.domain.documents.repository import DocumentRepository
from knowledge_assistant.domain.jobs.entities import ProcessingJob
from knowledge_assistant.domain.jobs.repository import ProcessingJobRepository


@dataclass(frozen=True)
class EnqueueDocumentProcessingResult:
    job: ProcessingJob
    created: bool


class EnqueueDocumentProcessingCommand:
    def __init__(
        self,
        *,
        document_repository: DocumentRepository,
        job_repository: ProcessingJobRepository,
    ) -> None:
        self._document_repository = document_repository
        self._job_repository = job_repository

    async def execute(
        self,
        *,
        document_id: UUID,
        owner_id: UUID,
    ) -> EnqueueDocumentProcessingResult:
        document = await self._document_repository.get_by_id(document_id)
        if document is None or document.owner_id != owner_id:
            raise ValueError("Document was not found.")

        active_job = await self._job_repository.get_active_for_document(
            owner_id=owner_id,
            document_id=document_id,
        )
        if active_job is not None:
            return EnqueueDocumentProcessingResult(
                job=active_job,
                created=False,
            )

        job = ProcessingJob.create_document_processing(
            owner_id=owner_id,
            document_id=document_id,
        )
        saved_job = await self._job_repository.add(job)
        created = saved_job.id == job.id
        if created:
            document.mark_as_queued()
            await self._document_repository.update(document)
        return EnqueueDocumentProcessingResult(
            job=saved_job,
            created=created,
        )
