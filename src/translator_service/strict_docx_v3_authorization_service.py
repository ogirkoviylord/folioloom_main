from dataclasses import dataclass, replace
from hashlib import sha256

from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.persistent_job_store import (
    PersistentJobStore,
    StrictDocxV3JobStore,
    strict_docx_capability_denial_code,
)
from translator_service.persistent_jobs import (
    StrictAdmissionResult,
    StrictDocxV3AdmissionRequest,
    StrictDocxV3Authorization,
)


@dataclass(frozen=True)
class StrictDocxV3AuthorizationServiceRequest:
    """Internal request that seals one v3 authorization from local object storage."""

    store: PersistentJobStore
    storage: LocalObjectStorage
    approval_id: str
    source_object_key: str


@dataclass(frozen=True)
class StrictDocxV3AuthorizationDenied:
    code: str


@dataclass(frozen=True)
class StrictDocxV3AdmissionServiceRequest:
    """Internal v3 admission request with server-owned object storage access."""

    store: PersistentJobStore
    storage: LocalObjectStorage
    request: StrictDocxV3AdmissionRequest


def seal_strict_docx_v3_authorization(
    request: StrictDocxV3AuthorizationServiceRequest,
) -> StrictDocxV3Authorization | StrictDocxV3AuthorizationDenied:
    """Seal a v3 authorization only from verified server-resolved DOCX bytes."""
    if not isinstance(request.store, StrictDocxV3JobStore):
        return StrictDocxV3AuthorizationDenied(
            code="strict_docx_v3_unsupported_backend"
        )
    capability_denial = strict_docx_capability_denial_code(request.store)
    if capability_denial is not None:
        return StrictDocxV3AuthorizationDenied(code=capability_denial)

    source = _verified_original_docx_source(request.storage, request.source_object_key)
    if isinstance(source, StrictDocxV3AuthorizationDenied):
        return source

    approved_snapshot = request.store.read_approved_glossary_snapshot(
        approval_id=request.approval_id
    )
    if approved_snapshot is None:
        return StrictDocxV3AuthorizationDenied(
            code="strict_docx_v3_source_approval_unavailable"
        )
    try:
        return request.store.create_strict_docx_v3_authorization(
            approval_id=request.approval_id,
            source_object_key=source.object_key,
            source_sha256=source.sha256,
            source_size_bytes=source.size_bytes,
            document_kind="docx",
        )
    except ValueError:
        return StrictDocxV3AuthorizationDenied(
            code="strict_docx_v3_source_custody_mismatch"
        )


def admit_verified_strict_docx_v3_job(
    service_request: StrictDocxV3AdmissionServiceRequest,
) -> StrictAdmissionResult:
    """Re-verify sealed source bytes before delegating v3 persistence."""
    store = service_request.store
    if not isinstance(store, StrictDocxV3JobStore):
        return StrictAdmissionResult(None, [], "strict_docx_v3_unsupported_backend")
    capability_denial = strict_docx_capability_denial_code(store)
    if capability_denial is not None:
        return StrictAdmissionResult(None, [], capability_denial)

    request = service_request.request
    authorization = store.read_strict_docx_v3_authorization(
        authorization_id=request.authorization_id
    )
    if authorization is None:
        return StrictAdmissionResult(None, [], "strict_docx_v3_authorization_missing")
    if authorization.authorization_status != "approved":
        return StrictAdmissionResult(None, [], "strict_docx_v3_authorization_revoked")
    source = _verified_original_docx_source(
        service_request.storage,
        authorization.source_object_key,
    )
    if isinstance(source, StrictDocxV3AuthorizationDenied):
        return StrictAdmissionResult(None, [], source.code)
    if (
        source.object_key != authorization.source_object_key
        or source.sha256 != authorization.source_sha256
        or source.size_bytes != authorization.source_size_bytes
        or authorization.document_kind != "docx"
    ):
        return StrictAdmissionResult(None, [], "strict_docx_v3_source_custody_mismatch")

    authoritative_request = replace(
        request,
        document_kind=authorization.document_kind,
        source_object_key=authorization.source_object_key,
        source_sha256=authorization.source_sha256,
        source_size_bytes=authorization.source_size_bytes,
        work_units=[
            replace(unit, source_object_key=authorization.source_object_key)
            for unit in request.work_units
        ],
    )
    return store.admit_strict_docx_v3_job(authoritative_request)


def _verified_original_docx_source(
    storage: LocalObjectStorage,
    source_object_key: str,
):
    try:
        metadata = storage.get_metadata(source_object_key)
        content = storage.get_bytes(source_object_key)
    except (FileNotFoundError, KeyError, ValueError):
        return StrictDocxV3AuthorizationDenied(code="strict_docx_v3_source_missing")

    if metadata.object_key != source_object_key:
        return StrictDocxV3AuthorizationDenied(
            code="strict_docx_v3_source_metadata_mismatch"
        )
    if metadata.kind is not StoredFileKind.ORIGINAL:
        return StrictDocxV3AuthorizationDenied(
            code="strict_docx_v3_source_kind_mismatch"
        )
    if not metadata.file_name.lower().endswith(".docx"):
        return StrictDocxV3AuthorizationDenied(code="document_kind_not_docx")
    if metadata.size_bytes != len(content):
        return StrictDocxV3AuthorizationDenied(
            code="strict_docx_v3_source_size_mismatch"
        )
    if metadata.sha256 != sha256(content).hexdigest():
        return StrictDocxV3AuthorizationDenied(
            code="strict_docx_v3_source_digest_mismatch"
        )
    return metadata
