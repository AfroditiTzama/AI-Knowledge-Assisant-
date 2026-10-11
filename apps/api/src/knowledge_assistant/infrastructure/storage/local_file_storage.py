import asyncio
from pathlib import Path
from uuid import uuid4

from knowledge_assistant.domain.documents.file_storage import (
    FileStorage,
    StoredFile,
)


class LocalFileStorage(FileStorage):
    def __init__(self, storage_directory: str | Path) -> None:
        self._storage_directory = Path(storage_directory).resolve()

    async def save(
        self,
        *,
        file_content: bytes,
        original_filename: str,
    ) -> StoredFile:
        if not original_filename.strip():
            raise ValueError("Original filename cannot be empty.")

        await asyncio.to_thread(
            self._storage_directory.mkdir,
            parents=True,
            exist_ok=True,
        )

        file_extension = Path(original_filename).suffix.lower()
        stored_filename = f"{uuid4().hex}{file_extension}"

        file_path = self._resolve_storage_path(stored_filename)

        temporary_path = self._resolve_storage_path(
            f".{stored_filename}.uploading"
        )
        try:
            await asyncio.to_thread(
                temporary_path.write_bytes,
                file_content,
            )
            await asyncio.to_thread(temporary_path.replace, file_path)
        except Exception:
            if await asyncio.to_thread(temporary_path.exists):
                await asyncio.to_thread(temporary_path.unlink)
            raise

        return StoredFile(
            stored_filename=stored_filename,
            storage_path=stored_filename,
            size_bytes=len(file_content),
        )

    async def read(self, storage_path: str) -> bytes:
        file_path = self._resolve_storage_path(storage_path)

        file_exists = await asyncio.to_thread(file_path.exists)

        if not file_exists:
            raise FileNotFoundError(
                f"Stored file was not found: {storage_path}"
            )

        is_file = await asyncio.to_thread(file_path.is_file)

        if not is_file:
            raise ValueError(
                "Storage path does not point to a file."
            )

        return await asyncio.to_thread(file_path.read_bytes)

    async def delete(self, storage_path: str) -> None:
        file_path = self._resolve_storage_path(storage_path)

        file_exists = await asyncio.to_thread(file_path.exists)

        if not file_exists:
            return

        is_file = await asyncio.to_thread(file_path.is_file)

        if not is_file:
            raise ValueError(
                "Storage path does not point to a file."
            )

        await asyncio.to_thread(file_path.unlink)

    def _resolve_storage_path(self, storage_path: str) -> Path:
        file_path = (
            self._storage_directory / storage_path
        ).resolve()

        if not file_path.is_relative_to(self._storage_directory):
            raise ValueError("Invalid storage path.")

        return file_path
