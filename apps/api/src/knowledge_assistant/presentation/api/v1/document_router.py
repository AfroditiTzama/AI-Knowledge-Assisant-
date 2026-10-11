from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from knowledge_assistant.bootstrap.dependencies.document import (
    DeleteDocumentCommandDependency,
    GetDocumentChunkPreviewQueryDependency,
    ListDocumentsQueryDependency,
    UploadDocumentCommandDependency,
)
from knowledge_assistant.bootstrap.dependencies.jobs import (
    EnqueueDocumentProcessingCommandDependency,
    ProcessingJobRepositoryDependency,
)
from knowledge_assistant.bootstrap.dependencies.user import get_current_user
from knowledge_assistant.core.config import get_settings
from knowledge_assistant.domain.users.entities import User
from knowledge_assistant.presentation.api.v1.schemas.document import (
    DocumentChunkPreviewResponse,
    DocumentResponse,
)
from knowledge_assistant.presentation.api.v1.schemas.job import (
    EnqueueProcessingJobResponse,
    ProcessingJobResponse,
)

router = APIRouter(
    prefix="/documents",
    tags=["Documents"],
)


CurrentUserDependency = Annotated[
    User,
    Depends(get_current_user),
]


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    file: Annotated[
        UploadFile,
        File(description="Document file to upload"),
    ],
    current_user: CurrentUserDependency,
    command: UploadDocumentCommandDependency,
) -> DocumentResponse:
    try:
        settings = get_settings()
        file_content = await _read_upload_bounded(
            file,
            max_bytes=settings.document_max_upload_bytes,
            chunk_bytes=settings.document_upload_chunk_bytes,
        )

        document = await command.execute(
            owner_id=current_user.id,
            original_filename=file.filename or "",
            content_type=file.content_type,
            file_content=file_content,
        )

        return DocumentResponse.model_validate(document)

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    finally:
        await file.close()


async def _read_upload_bounded(
    file: UploadFile,
    *,
    max_bytes: int,
    chunk_bytes: int,
) -> bytes:
    content = bytearray()
    while True:
        remaining = max_bytes - len(content)
        chunk = await file.read(min(chunk_bytes, remaining + 1))
        if not chunk:
            return bytes(content)
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Uploaded file exceeds the configured size limit.",
            )


@router.get(
    "",
    response_model=list[DocumentResponse],
    status_code=status.HTTP_200_OK,
)
async def list_documents(
    current_user: CurrentUserDependency,
    query: ListDocumentsQueryDependency,
) -> list[DocumentResponse]:
    documents = await query.execute(
        owner_id=current_user.id,
    )

    return [
        DocumentResponse.model_validate(document)
        for document in documents
    ]


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    document_id: UUID,
    current_user: CurrentUserDependency,
    command: DeleteDocumentCommandDependency,
    job_repository: ProcessingJobRepositoryDependency,
) -> None:
    active_job = await job_repository.get_active_for_document(
        owner_id=current_user.id,
        document_id=document_id,
    )
    if active_job is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wait for document processing to finish before deleting it."
            ),
        )

    try:
        await command.execute(
            document_id=document_id,
            owner_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/chunks/{chunk_id}",
    response_model=DocumentChunkPreviewResponse,
    status_code=status.HTTP_200_OK,
)
async def get_document_chunk_preview(
    chunk_id: UUID,
    current_user: CurrentUserDependency,
    query: GetDocumentChunkPreviewQueryDependency,
) -> DocumentChunkPreviewResponse:
    try:
        preview = await query.execute(
            chunk_id=chunk_id,
            owner_id=current_user.id,
        )

        return DocumentChunkPreviewResponse(
            chunk_id=preview.chunk_id,
            document_id=preview.document_id,
            document_filename=(
                preview.document_filename
            ),
            chunk_index=preview.chunk_index,
            page_number=preview.page_number,
            text=preview.text,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/{document_id}/chunks/{chunk_index}",
    response_model=DocumentChunkPreviewResponse,
    status_code=status.HTTP_200_OK,
)
async def get_document_chunk_preview_by_location(
    document_id: UUID,
    chunk_index: int,
    current_user: CurrentUserDependency,
    query: GetDocumentChunkPreviewQueryDependency,
) -> DocumentChunkPreviewResponse:
    try:
        preview = await query.execute_by_location(
            document_id=document_id,
            chunk_index=chunk_index,
            owner_id=current_user.id,
        )

        return DocumentChunkPreviewResponse(
            chunk_id=preview.chunk_id,
            document_id=preview.document_id,
            document_filename=(
                preview.document_filename
            ),
            chunk_index=preview.chunk_index,
            page_number=preview.page_number,
            text=preview.text,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/{document_id}/process",
    response_model=EnqueueProcessingJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def process_document(
    document_id: UUID,
    current_user: CurrentUserDependency,
    command: EnqueueDocumentProcessingCommandDependency,
) -> EnqueueProcessingJobResponse:
    try:
        result = await command.execute(
            document_id=document_id,
            owner_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return EnqueueProcessingJobResponse(
        job=ProcessingJobResponse.model_validate(result.job),
        created=result.created,
    )
