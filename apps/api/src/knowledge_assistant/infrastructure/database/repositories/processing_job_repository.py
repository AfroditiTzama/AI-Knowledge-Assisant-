from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge_assistant.domain.jobs.entities import (
    ProcessingJob,
    ProcessingJobStage,
    ProcessingJobStatus,
)
from knowledge_assistant.domain.jobs.repository import ProcessingJobRepository
from knowledge_assistant.infrastructure.database.mappers.processing_job_mapper import (
    ProcessingJobMapper,
)
from knowledge_assistant.infrastructure.database.models.processing_job import (
    ProcessingJobModel,
)


class SQLAlchemyProcessingJobRepository(ProcessingJobRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, job: ProcessingJob) -> ProcessingJob:
        try:
            async with self._session.begin_nested():
                model = ProcessingJobMapper.to_model(job)
                self._session.add(model)
                await self._session.flush()
                await self._session.refresh(model)
            return ProcessingJobMapper.to_domain(model)
        except IntegrityError:
            active_job = await self.get_active_for_document(
                owner_id=job.owner_id,
                document_id=job.document_id,
            )
            if active_job is not None:
                return active_job
            raise

    async def update(self, job: ProcessingJob) -> ProcessingJob:
        model = await self._session.get(ProcessingJobModel, job.id)
        if model is None:
            raise ValueError(f"Processing job not found: {job.id}")

        model.status = job.status
        model.stage = job.stage
        model.progress = job.progress
        model.attempts = job.attempts
        model.max_attempts = job.max_attempts
        model.error_message = job.error_message
        model.updated_at = job.updated_at
        model.started_at = job.started_at
        model.completed_at = job.completed_at

        await self._session.flush()
        await self._session.refresh(model)
        return ProcessingJobMapper.to_domain(model)

    async def get_by_id(self, job_id: UUID) -> ProcessingJob | None:
        model = await self._session.get(ProcessingJobModel, job_id)
        return (
            ProcessingJobMapper.to_domain(model)
            if model is not None
            else None
        )

    async def get_active_for_document(
        self,
        *,
        owner_id: UUID,
        document_id: UUID,
    ) -> ProcessingJob | None:
        statement = (
            select(ProcessingJobModel)
            .where(
                ProcessingJobModel.owner_id == owner_id,
                ProcessingJobModel.document_id == document_id,
                ProcessingJobModel.status.in_(
                    [
                        ProcessingJobStatus.QUEUED,
                        ProcessingJobStatus.RUNNING,
                    ]
                ),
            )
            .order_by(ProcessingJobModel.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return (
            ProcessingJobMapper.to_domain(model)
            if model is not None
            else None
        )

    async def get_latest_for_document(
        self,
        *,
        owner_id: UUID,
        document_id: UUID,
    ) -> ProcessingJob | None:
        statement = (
            select(ProcessingJobModel)
            .where(
                ProcessingJobModel.owner_id == owner_id,
                ProcessingJobModel.document_id == document_id,
            )
            .order_by(ProcessingJobModel.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return (
            ProcessingJobMapper.to_domain(model)
            if model is not None
            else None
        )

    async def list_by_owner_id(
        self,
        owner_id: UUID,
    ) -> list[ProcessingJob]:
        statement = (
            select(ProcessingJobModel)
            .where(ProcessingJobModel.owner_id == owner_id)
            .order_by(ProcessingJobModel.created_at.desc())
        )
        result = await self._session.execute(statement)
        return [
            ProcessingJobMapper.to_domain(model)
            for model in result.scalars().all()
        ]

    async def claim_next_queued(self) -> ProcessingJob | None:
        candidate = (
            select(ProcessingJobModel.id)
            .where(
                ProcessingJobModel.status == ProcessingJobStatus.QUEUED
            )
            .order_by(ProcessingJobModel.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        now = datetime.now(UTC)
        statement = (
            update(ProcessingJobModel)
            .where(
                ProcessingJobModel.id == candidate,
                ProcessingJobModel.status == ProcessingJobStatus.QUEUED,
            )
            .values(
                status=ProcessingJobStatus.RUNNING,
                stage=ProcessingJobStage.EXTRACTING,
                progress=5,
                attempts=ProcessingJobModel.attempts + 1,
                error_message=None,
                started_at=now,
                completed_at=None,
                updated_at=now,
            )
            .returning(ProcessingJobModel)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return ProcessingJobMapper.to_domain(model) if model is not None else None

    async def recover_interrupted(self) -> int:
        statement = select(ProcessingJobModel).where(
            ProcessingJobModel.status == ProcessingJobStatus.RUNNING
        )
        result = await self._session.execute(statement)
        models = list(result.scalars().all())

        for model in models:
            job = ProcessingJobMapper.to_domain(model)
            job.recover_after_restart()
            model.status = job.status
            model.stage = job.stage
            model.progress = job.progress
            model.attempts = job.attempts
            model.error_message = job.error_message
            model.updated_at = job.updated_at
            model.started_at = job.started_at
            model.completed_at = job.completed_at

        await self._session.flush()
        return len(models)
