from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath


class DocumentFormat(StrEnum):
    EPUB = "epub"
    DOCX = "docx"
    PDF = "pdf"
    TXT = "txt"


class UnsupportedDocumentError(ValueError):
    pass


class FileTooLargeError(ValueError):
    pass


class EmptyDocumentError(ValueError):
    pass


@dataclass(frozen=True)
class DocumentUpload:
    file_name: str
    document_format: DocumentFormat
    size_bytes: int


def validate_document_upload(
    *,
    file_name: str,
    size_bytes: int,
    max_upload_mb: int,
) -> DocumentUpload:
    if size_bytes <= 0:
        raise EmptyDocumentError("Document file is empty")

    extension = PurePath(file_name).suffix.lower().lstrip(".")

    try:
        document_format = DocumentFormat(extension)
    except ValueError as error:
        raise UnsupportedDocumentError(
            f"Unsupported document format for file: {file_name}"
        ) from error

    max_upload_bytes = max_upload_mb * 1024 * 1024
    if size_bytes > max_upload_bytes:
        raise FileTooLargeError(
            f"File exceeds the upload limit of {max_upload_mb} MB"
        )

    return DocumentUpload(
        file_name=file_name,
        document_format=document_format,
        size_bytes=size_bytes,
    )
