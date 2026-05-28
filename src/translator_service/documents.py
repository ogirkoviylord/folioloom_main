from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from pathlib import PurePath, PurePosixPath, PureWindowsPath
from zipfile import BadZipFile, ZipFile


class DocumentFormat(StrEnum):
    EPUB = "epub"
    DOCX = "docx"
    PDF = "pdf"
    TXT = "txt"


SUPPORTED_UPLOAD_FORMATS = frozenset(
    {
        DocumentFormat.EPUB,
        DocumentFormat.DOCX,
        DocumentFormat.TXT,
    }
)
MAX_ARCHIVE_ENTRY_COUNT = 512
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 20 * 1024 * 1024
MAX_ARCHIVE_COMPRESSION_RATIO = 100
MIN_ARCHIVE_RATIO_CHECK_BYTES = 512
_SUPPORTED_FORMATS_MESSAGE = "Supported formats: TXT, DOCX, and EPUB"
_EXECUTABLE_ARCHIVE_SUFFIXES = frozenset(
    {
        ".app",
        ".bat",
        ".cmd",
        ".com",
        ".dll",
        ".dylib",
        ".exe",
        ".js",
        ".msi",
        ".ps1",
        ".scr",
        ".sh",
        ".so",
        ".vbs",
    }
)


class UnsupportedDocumentError(ValueError):
    pass


class FileTooLargeError(ValueError):
    pass


class EmptyDocumentError(ValueError):
    pass


class DocumentContentRejectedError(ValueError):
    def __init__(
        self,
        safe_error_class: str,
        *,
        container_failed: bool = False,
    ) -> None:
        super().__init__("Document failed safety validation")
        self.safe_error_class = safe_error_class
        self.container_failed = container_failed


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
            f"Unsupported document format. {_SUPPORTED_FORMATS_MESSAGE}"
        ) from error

    if document_format not in SUPPORTED_UPLOAD_FORMATS:
        raise UnsupportedDocumentError(
            f"Unsupported document format. {_SUPPORTED_FORMATS_MESSAGE}"
        )

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


def validate_document_content(
    *,
    file_name: str,
    content: bytes,
    document_format: DocumentFormat,
) -> None:
    del file_name

    if document_format is DocumentFormat.TXT:
        _validate_txt_content(content)
        return

    if document_format is DocumentFormat.DOCX:
        with _validated_zip(content) as archive:
            _require_zip_member(archive, "word/document.xml", "docx_missing_document")
        return

    if document_format is DocumentFormat.EPUB:
        with _validated_zip(content) as archive:
            _validate_epub_structure(archive)
        return

    raise DocumentContentRejectedError("unsupported_format", container_failed=True)


def _validate_txt_content(content: bytes) -> None:
    if b"\x00" in content:
        raise DocumentContentRejectedError("binary_txt")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise DocumentContentRejectedError(
            "invalid_txt_utf8",
            container_failed=True,
        ) from error
    control_chars = sum(
        1
        for character in text
        if ord(character) < 32 and character not in "\n\r\t\f\b"
    )
    if control_chars > max(8, len(text) // 100):
        raise DocumentContentRejectedError("binary_txt")


def _validated_zip(content: bytes) -> ZipFile:
    if not content.startswith(b"PK\x03\x04"):
        raise DocumentContentRejectedError(
            "zip_invalid_signature",
            container_failed=True,
        )
    try:
        archive = ZipFile(BytesIO(content))
        _validate_archive_members(archive)
        if archive.testzip() is not None:
            raise DocumentContentRejectedError(
                "zip_corrupt",
                container_failed=True,
            )
        return archive
    except DocumentContentRejectedError:
        raise
    except BadZipFile as error:
        raise DocumentContentRejectedError(
            "zip_corrupt",
            container_failed=True,
        ) from error


def _validate_archive_members(archive: ZipFile) -> None:
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_ENTRY_COUNT:
        raise DocumentContentRejectedError("archive_too_many_entries")

    total_uncompressed = 0
    member_names: set[str] = set()
    for member in members:
        if member.filename in member_names:
            raise DocumentContentRejectedError("archive_duplicate_member")
        member_names.add(member.filename)
        if _is_unsafe_archive_path(member.filename):
            raise DocumentContentRejectedError("unsafe_archive_path")
        if _is_executable_archive_member(member.filename):
            raise DocumentContentRejectedError("executable_archive_member")
        if member.file_size > MAX_ARCHIVE_MEMBER_BYTES:
            raise DocumentContentRejectedError("archive_member_too_large")
        total_uncompressed += member.file_size
        if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise DocumentContentRejectedError("archive_uncompressed_too_large")
        if _is_high_compression_ratio(member):
            raise DocumentContentRejectedError("archive_compression_ratio")


def _is_unsafe_archive_path(file_name: str) -> bool:
    if not file_name or "\\" in file_name:
        return True
    posix_path = PurePosixPath(file_name)
    windows_path = PureWindowsPath(file_name)
    return (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or ".." in posix_path.parts
        or ".." in windows_path.parts
    )


def _is_executable_archive_member(file_name: str) -> bool:
    return PurePosixPath(file_name).suffix.lower() in _EXECUTABLE_ARCHIVE_SUFFIXES


def _is_high_compression_ratio(member) -> bool:
    if member.file_size < MIN_ARCHIVE_RATIO_CHECK_BYTES:
        return False
    compressed_size = max(1, member.compress_size)
    return member.file_size / compressed_size > MAX_ARCHIVE_COMPRESSION_RATIO


def _require_zip_member(
    archive: ZipFile,
    member_name: str,
    safe_error_class: str,
) -> bytes:
    try:
        return archive.read(member_name)
    except KeyError as error:
        raise DocumentContentRejectedError(safe_error_class) from error
    except RuntimeError as error:
        raise DocumentContentRejectedError(
            "zip_corrupt",
            container_failed=True,
        ) from error


def _validate_epub_structure(archive: ZipFile) -> None:
    mimetype = _require_zip_member(
        archive,
        "mimetype",
        "epub_missing_mimetype",
    )
    if mimetype.strip() != b"application/epub+zip":
        raise DocumentContentRejectedError("epub_invalid_mimetype")
    _require_zip_member(
        archive,
        "META-INF/container.xml",
        "epub_missing_container",
    )
