from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePath

from translator_service.admin.auth import AdminSession
from translator_service.admin.rbac import AdminRole
from translator_service.documents import (
    DocumentContentRejectedError,
    DocumentFormat,
    validate_document_content,
)
from translator_service.file_storage import (
    LocalObjectStorage,
    ObjectPublishError,
    StoredFileKind,
)
from translator_service.persistent_jobs import SQLiteTranslationJobStore
from translator_service.source_registry_service import (
    RegisteredOriginalDocxSource,
    SourceRegistryActor,
    SourceRegistryDenied,
    register_verified_original_docx_source,
    select_registered_original_docx_source,
)
from translator_service.verified_original_docx import (
    VerifiedOriginalDocxDenied,
    verify_original_docx_source,
)


@dataclass(frozen=True)
class DocumentIntakeDenied:
    code: str


@dataclass(frozen=True)
class OwnerDocumentCatalogEntry:
    document_custody_id: str
    source_sha256: str
    source_size_bytes: int
    file_name: str


def source_registry_actor_from_admin_session(
    session: AdminSession,
) -> SourceRegistryActor | SourceRegistryDenied:
    """Adapt a validated Admin session without accepting caller-supplied actors."""
    if session.role is not AdminRole.OWNER or not session.actor_id:
        return SourceRegistryDenied("source_registry_actor_unauthorized")
    return SourceRegistryActor(
        actor_id=session.actor_id,
        role=session.role.value,
        authn_schema_version="admin-session-v1",
    )


def ingest_owner_docx(
    *,
    store: object,
    storage: LocalObjectStorage,
    actor: SourceRegistryActor | SourceRegistryDenied,
    file_name: str,
    content_type: str,
    content: bytes,
    maximum_size_bytes: int,
) -> RegisteredOriginalDocxSource | DocumentIntakeDenied:
    """Validate, persist, verify, and register one owner-local DOCX upload."""
    validation = _validate_docx_upload(
        file_name=file_name,
        content=content,
        maximum_size_bytes=maximum_size_bytes,
    )
    if validation is not None:
        return validation

    object_key = _original_object_key(file_name, content)
    created_by_request = False
    try:
        stored, created_by_request = storage.put_bytes_if_absent(
            kind=StoredFileKind.ORIGINAL,
            file_name=file_name,
            content_type=content_type or _DOCX_CONTENT_TYPE,
            content=content,
        )
        verified = verify_original_docx_source(storage, stored.object_key)
        if isinstance(verified, VerifiedOriginalDocxDenied):
            return _compensate(
                storage, stored.object_key, created_by_request, verified.code
            )
        registered = register_verified_original_docx_source(
            store=store, actor=actor, source=verified
        )
        if isinstance(registered, SourceRegistryDenied):
            return _compensate(
                storage, stored.object_key, created_by_request, registered.code
            )
        return registered
    except ObjectPublishError:
        return DocumentIntakeDenied("document_intake_storage_unavailable")
    except Exception:
        if created_by_request:
            storage.delete_if_unretained(object_key)
        raise


def catalog_registered_original_docx_sources(
    *,
    store: object,
    storage: LocalObjectStorage,
    actor: SourceRegistryActor | SourceRegistryDenied,
) -> tuple[OwnerDocumentCatalogEntry, ...] | DocumentIntakeDenied:
    """Return exact actor-owned registry metadata without storage discovery."""
    denial = _actor_denial(actor)
    if denial is not None:
        return denial
    assert isinstance(actor, SourceRegistryActor)
    if isinstance(store, SQLiteTranslationJobStore):
        rows = store._connection.execute(
            """SELECT document_custody_id, source_object_key, source_sha256,
            source_size_bytes FROM strict_docx_v3_document_custody
            WHERE registry_owner_actor_id = ? AND registry_actor_role = ?
            AND registry_authn_schema_version = ? AND document_kind = 'docx'
            ORDER BY created_at DESC, document_custody_id DESC""",
            (actor.actor_id, actor.role, actor.authn_schema_version),
        ).fetchall()
    elif hasattr(store, "connection"):
        rows = object.__getattribute__(store, "connection").execute(
            """SELECT document_custody_id, source_object_key, source_sha256,
            source_size_bytes FROM strict_docx_v3_document_custody
            WHERE registry_owner_actor_id = %(actor_id)s
            AND registry_actor_role = %(role)s
            AND registry_authn_schema_version = %(authn_schema_version)s
            AND document_kind = 'docx'
            ORDER BY created_at DESC, document_custody_id DESC""",
            {
                "actor_id": actor.actor_id,
                "role": actor.role,
                "authn_schema_version": actor.authn_schema_version,
            },
        ).fetchall()
    else:
        return DocumentIntakeDenied("source_registry_unsupported_backend")

    entries: list[OwnerDocumentCatalogEntry] = []
    for row in rows:
        selected = select_registered_original_docx_source(
            store=store,
            storage=storage,
            actor=actor,
            document_custody_id=row["document_custody_id"],
        )
        if isinstance(selected, SourceRegistryDenied):
            continue
        try:
            metadata = storage.get_metadata(row["source_object_key"])
        except (FileNotFoundError, KeyError, ValueError):
            continue
        entries.append(
            OwnerDocumentCatalogEntry(
                document_custody_id=selected.document_custody_id,
                source_sha256=selected.source_sha256,
                source_size_bytes=selected.source_size_bytes,
                file_name=metadata.file_name,
            )
        )
    return tuple(entries)


def select_owner_registered_original_docx_source(
    *,
    store: object,
    storage: LocalObjectStorage,
    actor: SourceRegistryActor | SourceRegistryDenied,
    document_custody_id: str,
) -> RegisteredOriginalDocxSource | DocumentIntakeDenied:
    if not document_custody_id:
        return DocumentIntakeDenied("document_intake_selection_invalid")
    selected = select_registered_original_docx_source(
        store=store,
        storage=storage,
        actor=actor,
        document_custody_id=document_custody_id,
    )
    if isinstance(selected, SourceRegistryDenied):
        return DocumentIntakeDenied(selected.code)
    return selected


def _validate_docx_upload(
    *, file_name: str, content: bytes, maximum_size_bytes: int
) -> DocumentIntakeDenied | None:
    if maximum_size_bytes < 1 or len(content) > maximum_size_bytes:
        return DocumentIntakeDenied("document_intake_file_too_large")
    if not file_name.lower().endswith(".docx") or not content:
        return DocumentIntakeDenied("document_intake_file_invalid")
    try:
        validate_document_content(
            file_name=file_name,
            content=content,
            document_format=DocumentFormat.DOCX,
        )
    except DocumentContentRejectedError:
        return DocumentIntakeDenied("document_intake_file_invalid")
    return None


def _actor_denial(
    actor: SourceRegistryActor | SourceRegistryDenied,
) -> DocumentIntakeDenied | None:
    if isinstance(actor, SourceRegistryDenied):
        return DocumentIntakeDenied(actor.code)
    if not actor.actor_id or actor.role != "owner" or not actor.authn_schema_version:
        return DocumentIntakeDenied("source_registry_actor_unauthorized")
    return None


def _compensate(
    storage: LocalObjectStorage,
    object_key: str,
    created_by_request: bool,
    code: str,
) -> DocumentIntakeDenied:
    if created_by_request:
        storage.delete_if_unretained(object_key)
    return DocumentIntakeDenied(code)


def _original_object_key(file_name: str, content: bytes) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", PurePath(file_name).name.strip())
    safe_name = re.sub(r"_+", "_", safe_name).strip("._") or "file"
    return f"original/{sha256(content).hexdigest()[:16]}-{safe_name}"


_DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
