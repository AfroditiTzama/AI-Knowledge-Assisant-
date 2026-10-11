import asyncio
from io import BytesIO

from docx import Document as OpenXmlDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from knowledge_assistant.domain.documents.text_extractor import (
    DocumentTextExtractor,
    ExtractedDocument,
    ExtractedTextSegment,
)
from knowledge_assistant.domain.documents.validation import (
    DocumentValidationError,
    validate_docx_archive,
)


class DOCXTextExtractor(DocumentTextExtractor):
    def __init__(
        self,
        *,
        max_text_characters: int = 5_000_000,
        max_uncompressed_bytes: int = 100 * 1024 * 1024,
        max_archive_entries: int = 2_048,
        max_compression_ratio: int = 100,
    ) -> None:
        self._max_text_characters = max_text_characters
        self._max_uncompressed_bytes = max_uncompressed_bytes
        self._max_archive_entries = max_archive_entries
        self._max_compression_ratio = max_compression_ratio

    async def extract(
        self,
        *,
        file_content: bytes,
        original_filename: str,
        content_type: str | None,
    ) -> ExtractedDocument:
        if not file_content:
            raise ValueError("DOCX file cannot be empty.")

        return await asyncio.to_thread(
            self._extract_sync,
            file_content,
        )

    def _extract_sync(
        self,
        file_content: bytes,
    ) -> ExtractedDocument:
        validate_docx_archive(
            file_content,
            max_uncompressed_bytes=self._max_uncompressed_bytes,
            max_entries=self._max_archive_entries,
            max_compression_ratio=self._max_compression_ratio,
        )
        try:
            document = OpenXmlDocument(
                BytesIO(file_content)
            )
        except Exception as exc:
            raise ValueError(
                "The uploaded DOCX file is invalid or corrupted."
            ) from exc

        segments: list[ExtractedTextSegment] = []
        extracted_characters = 0

        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                paragraph_text = block.text.strip()

                if not paragraph_text:
                    continue

                extracted_characters += len(paragraph_text)
                if segments:
                    extracted_characters += 2
                self._ensure_text_limit(extracted_characters)

                segments.append(
                    ExtractedTextSegment(
                        text=paragraph_text,
                        page_number=None,
                    )
                )

            elif isinstance(block, Table):
                table_text = self._extract_table_text(
                    block,
                    remaining_characters=(
                        self._max_text_characters - extracted_characters
                        - (2 if segments else 0)
                    ),
                )

                if not table_text:
                    continue

                extracted_characters += len(table_text)
                if segments:
                    extracted_characters += 2
                self._ensure_text_limit(extracted_characters)

                segments.append(
                    ExtractedTextSegment(
                        text=table_text,
                        page_number=None,
                    )
                )

        if not segments:
            raise ValueError(
                "No extractable text was found in the DOCX file."
            )

        return ExtractedDocument(
            segments=tuple(segments),
        )

    def _extract_table_text(
        self,
        table: Table,
        *,
        remaining_characters: int,
    ) -> str:
        rows: list[str] = []
        character_count = 0

        for row in table.rows:
            cell_values = [
                cell.text.strip()
                for cell in row.cells
            ]

            if not any(cell_values):
                continue

            row_text = " | ".join(cell_values)
            character_count += len(row_text)
            if rows:
                character_count += 1
            if character_count > remaining_characters:
                raise DocumentValidationError(
                    "The document exceeds the extracted text limit."
                )
            rows.append(row_text)

        return "\n".join(rows)

    def _ensure_text_limit(self, character_count: int) -> None:
        if character_count > self._max_text_characters:
            raise DocumentValidationError(
                "The document exceeds the extracted text limit."
            )
