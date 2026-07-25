from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from translator_service.file_storage import LocalObjectStorage, StoredFileKind


@dataclass(frozen=True)
class VerifiedOriginalDocxSource:
    object_key: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class VerifiedOriginalDocxDenied:
    code: str


def verify_original_docx_source(
    storage: LocalObjectStorage,
    source_object_key: str,
) -> VerifiedOriginalDocxSource | VerifiedOriginalDocxDenied:
    """Read and validate a trusted server-side ORIGINAL DOCX storage key."""
    try:
        metadata = storage.get_metadata(source_object_key)
        content = storage.get_bytes(source_object_key)
    except (FileNotFoundError, KeyError, ValueError):
        return VerifiedOriginalDocxDenied("document_missing")
    if metadata.object_key != source_object_key:
        return VerifiedOriginalDocxDenied("document_metadata_mismatch")
    if (
        metadata.kind is not StoredFileKind.ORIGINAL
        or not metadata.file_name.lower().endswith(".docx")
    ):
        return VerifiedOriginalDocxDenied("document_kind_invalid")
    if metadata.size_bytes != len(content):
        return VerifiedOriginalDocxDenied("document_size_mismatch")
    if metadata.sha256 != sha256(content).hexdigest():
        return VerifiedOriginalDocxDenied("document_digest_mismatch")
    return VerifiedOriginalDocxSource(
        object_key=metadata.object_key,
        sha256=metadata.sha256,
        size_bytes=metadata.size_bytes,
    )
