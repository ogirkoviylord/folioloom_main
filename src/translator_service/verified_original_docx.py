from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from weakref import WeakValueDictionary

from translator_service.file_storage import LocalObjectStorage, StoredFileKind


@dataclass(frozen=True)
class VerifiedOriginalDocxSource:
    object_key: str
    sha256: str
    size_bytes: int
    _verification_capability: object | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )


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
    except OSError:
        return VerifiedOriginalDocxDenied("document_storage_unavailable")
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
    source = VerifiedOriginalDocxSource(
        object_key=metadata.object_key,
        sha256=metadata.sha256,
        size_bytes=metadata.size_bytes,
    )
    object.__setattr__(source, "_verification_capability", _VERIFICATION_CAPABILITY)
    _VERIFIED_SOURCE_BY_ID[id(source)] = source
    return source


_VERIFICATION_CAPABILITY = object()
_VERIFIED_SOURCE_BY_ID: WeakValueDictionary[int, VerifiedOriginalDocxSource] = (
    WeakValueDictionary()
)


def is_verified_original_docx_source(source: object) -> bool:
    return (
        isinstance(source, VerifiedOriginalDocxSource)
        and source._verification_capability is _VERIFICATION_CAPABILITY
        and _VERIFIED_SOURCE_BY_ID.get(id(source)) is source
    )
