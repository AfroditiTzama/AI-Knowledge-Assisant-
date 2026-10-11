import asyncio

from knowledge_assistant.domain.documents.text_extractor import (
    DocumentTextExtractor,
    ExtractedDocument,
    ExtractedTextSegment,
)


class TXTTextExtractor(DocumentTextExtractor):
    def __init__(self, *, max_text_characters: int = 5_000_000) -> None:
        self._max_text_characters = max_text_characters

    async def extract(
        self,
        *,
        file_content: bytes,
        original_filename: str,
        content_type: str | None,
    ) -> ExtractedDocument:
        if not file_content:
            raise ValueError("TXT file cannot be empty.")

        return await asyncio.to_thread(
            self._extract_sync,
            file_content,
        )

    def _extract_sync(
        self,
        file_content: bytes,
    ) -> ExtractedDocument:
        text = TXTTextExtractor._decode_text(file_content)
        text = text.strip()

        if len(text) > self._max_text_characters:
            raise ValueError(
                "The document exceeds the extracted text limit."
            )

        if not text:
            raise ValueError(
                "No extractable text was found in the TXT file."
            )

        return ExtractedDocument(
            segments=(
                ExtractedTextSegment(
                    text=text,
                    page_number=None,
                ),
            ),
        )

    @staticmethod
    def _decode_text(file_content: bytes) -> str:
        encodings = (
            "utf-8-sig",
            "utf-8",
            "utf-16",
            "cp1253",
            "latin-1",
        )

        for encoding in encodings:
            try:
                return file_content.decode(encoding)
            except UnicodeDecodeError:
                continue

        raise ValueError(
            "The TXT file encoding is not supported."
        )
