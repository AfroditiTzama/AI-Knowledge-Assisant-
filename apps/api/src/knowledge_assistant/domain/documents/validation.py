from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

PDF_CONTENT_TYPES = frozenset({"application/pdf"})
DOCX_CONTENT_TYPES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    }
)
TXT_CONTENT_TYPES = frozenset({"text/plain"})
GENERIC_CONTENT_TYPES = frozenset({"", "application/octet-stream"})
SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".txt"})


class DocumentValidationError(ValueError):
    """Raised when an uploaded document fails a public validation rule."""


def validate_document_upload(
    *,
    file_content: bytes,
    original_filename: str,
    content_type: str | None,
    max_docx_uncompressed_bytes: int,
    max_docx_archive_entries: int,
    max_docx_compression_ratio: int,
) -> None:
    extension = Path(original_filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentValidationError(
            "Unsupported document type. Supported file types are PDF, DOCX and TXT."
        )

    normalized_content_type = _normalize_content_type(content_type)
    allowed_content_types = {
        ".pdf": PDF_CONTENT_TYPES,
        ".docx": DOCX_CONTENT_TYPES,
        ".txt": TXT_CONTENT_TYPES,
    }[extension]
    if normalized_content_type not in allowed_content_types | GENERIC_CONTENT_TYPES:
        raise DocumentValidationError(
            "The uploaded file's media type does not match its extension."
        )

    if extension == ".pdf" and not file_content.startswith(b"%PDF-"):
        raise DocumentValidationError(
            "The uploaded file does not have a valid PDF signature."
        )

    if extension == ".docx":
        if not file_content.startswith(b"PK\x03\x04"):
            raise DocumentValidationError(
                "The uploaded file does not have a valid DOCX signature."
            )
        validate_docx_archive(
            file_content,
            max_uncompressed_bytes=max_docx_uncompressed_bytes,
            max_entries=max_docx_archive_entries,
            max_compression_ratio=max_docx_compression_ratio,
        )

    binary_signatures = (
        b"%PDF-",
        b"PK\x03\x04",
        b"\x89PNG\r\n\x1a\n",
        b"\xff\xd8\xff",
        b"GIF87a",
        b"GIF89a",
        b"MZ",
    )
    if extension == ".txt" and file_content.startswith(binary_signatures):
        raise DocumentValidationError(
            "The uploaded file's contents do not match its TXT extension."
        )


def validate_docx_archive(
    file_content: bytes,
    *,
    max_uncompressed_bytes: int,
    max_entries: int,
    max_compression_ratio: int,
) -> None:
    try:
        with ZipFile(BytesIO(file_content), "r") as archive:
            members = archive.infolist()
            if len(members) > max_entries:
                raise DocumentValidationError(
                    "The DOCX archive contains too many files."
                )

            member_names = {member.filename for member in members}
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(member_names):
                raise DocumentValidationError(
                    "The uploaded DOCX file is invalid or corrupted."
                )

            declared_total = 0
            for member in members:
                _validate_archive_member_path(member.filename)
                if member.flag_bits & 0x1:
                    raise DocumentValidationError(
                        "Encrypted DOCX archives are not supported."
                    )
                declared_total += member.file_size
                if declared_total > max_uncompressed_bytes:
                    raise DocumentValidationError(
                        "The DOCX archive exceeds the decompressed size limit."
                    )
                if member.file_size and member.compress_size == 0:
                    raise DocumentValidationError(
                        "The DOCX archive has an unsafe compression ratio."
                    )
                if (
                    member.compress_size
                    and member.file_size / member.compress_size > max_compression_ratio
                ):
                    raise DocumentValidationError(
                        "The DOCX archive has an unsafe compression ratio."
                    )

            actual_total = 0
            for member in members:
                if member.is_dir():
                    continue
                with archive.open(member, "r") as member_file:
                    while True:
                        remaining = max_uncompressed_bytes - actual_total
                        chunk = member_file.read(min(64 * 1024, remaining + 1))
                        if not chunk:
                            break
                        actual_total += len(chunk)
                        if actual_total > max_uncompressed_bytes:
                            raise DocumentValidationError(
                                "The DOCX archive exceeds the decompressed size limit."
                            )
    except DocumentValidationError:
        raise
    except Exception as exc:
        raise DocumentValidationError(
            "The uploaded DOCX file is invalid or corrupted."
        ) from exc


def _normalize_content_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    return content_type.split(";", maxsplit=1)[0].strip().lower()


def _validate_archive_member_path(filename: str) -> None:
    path = PurePosixPath(filename)
    if path.is_absolute() or ".." in path.parts:
        raise DocumentValidationError(
            "The uploaded DOCX file contains an invalid archive path."
        )
