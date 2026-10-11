import asyncio
from io import BytesIO

from pypdf import PdfReader

from knowledge_assistant.domain.documents.text_extractor import (
    DocumentTextExtractor,
    ExtractedDocument,
    ExtractedTextSegment,
)


class PDFTextExtractor(DocumentTextExtractor):
    def __init__(
        self,
        *,
        max_pages: int = 500,
        max_text_characters: int = 5_000_000,
    ) -> None:
        self._max_pages = max_pages
        self._max_text_characters = max_text_characters

    async def extract(
        self,
        *,
        file_content: bytes,
        original_filename: str,
        content_type: str | None,
    ) -> ExtractedDocument:
        if not file_content:
            raise ValueError("PDF file cannot be empty.")

        return await asyncio.to_thread(
            self._extract_sync,
            file_content,
        )

    def _extract_sync(
        self,
        file_content: bytes,
    ) -> ExtractedDocument:
        try:
            reader = PdfReader(
                BytesIO(file_content),
                strict=False,
            )
            if reader.is_encrypted:
                raise ValueError(
                    "Password-protected PDF files are not supported."
                )

            if len(reader.pages) > self._max_pages:
                raise ValueError(
                    "The PDF exceeds the configured page limit."
                )
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(
                "The uploaded PDF is invalid or corrupted."
            ) from exc

        segments: list[ExtractedTextSegment] = []
        extracted_characters = 0

        try:
            for page_number, page in enumerate(
                reader.pages,
                start=1,
            ):
                page_text = page.extract_text() or ""
                page_text = page_text.strip()

                if not page_text:
                    continue

                extracted_characters += len(page_text)
                if segments:
                    extracted_characters += 2
                if extracted_characters > self._max_text_characters:
                    raise ValueError(
                        "The document exceeds the extracted text limit."
                    )

                segments.append(
                    ExtractedTextSegment(
                        text=page_text,
                        page_number=page_number,
                    )
                )
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(
                "The uploaded PDF is invalid or corrupted."
            ) from exc

        if not segments:
            raise ValueError(
                "No extractable text was found in the PDF."
            )

        return ExtractedDocument(
            segments=tuple(segments),
        )
