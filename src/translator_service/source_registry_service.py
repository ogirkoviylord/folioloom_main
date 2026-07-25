from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from translator_service.file_storage import LocalObjectStorage
from translator_service.persistent_jobs import (
    SQLiteTranslationJobStore,
    _now,
    _to_db_time,
)
from translator_service.verified_original_docx import (
    VerifiedOriginalDocxDenied,
    VerifiedOriginalDocxSource,
    verify_original_docx_source,
)


@dataclass(frozen=True)
class SourceRegistryActor:
    actor_id: str
    role: str
    authn_schema_version: str


@dataclass(frozen=True)
class SourceRegistryDenied:
    code: str


@dataclass(frozen=True)
class RegisteredOriginalDocxSource:
    """Actor-visible registry metadata; intentionally excludes the storage key."""

    document_custody_id: str
    source_sha256: str
    source_size_bytes: int


_POSTGRES_SELECT_BY_KEY_SQL = """
SELECT document_custody_id, source_sha256, source_size_bytes, document_kind,
       registry_owner_actor_id, registry_actor_role, registry_authn_schema_version
FROM strict_docx_v3_document_custody
WHERE source_object_key = %(source_object_key)s
"""
_POSTGRES_SELECT_BY_CUSTODY_SQL = """
SELECT document_custody_id, source_object_key, source_sha256, source_size_bytes,
       document_kind, registry_owner_actor_id, registry_actor_role,
       registry_authn_schema_version
FROM strict_docx_v3_document_custody
WHERE document_custody_id = %(document_custody_id)s
"""
_POSTGRES_INSERT_CUSTODY_SQL = """
INSERT INTO strict_docx_v3_document_custody (
    document_custody_id, source_object_key, source_sha256, source_size_bytes,
    document_kind, registry_owner_actor_id, registry_actor_role,
    registry_authn_schema_version
) VALUES (
    %(document_custody_id)s, %(source_object_key)s, %(source_sha256)s,
    %(source_size_bytes)s, 'docx', %(registry_owner_actor_id)s,
    %(registry_actor_role)s, %(registry_authn_schema_version)s
)
ON CONFLICT (source_object_key) DO NOTHING
RETURNING document_custody_id
"""
_POSTGRES_INSERT_EVENT_SQL = """
INSERT INTO source_registry_events (
    registry_event_id, document_custody_id, event_type, registry_owner_actor_id,
    registry_actor_role, registry_authn_schema_version
) VALUES (
    %(registry_event_id)s, %(document_custody_id)s, %(event_type)s,
    %(registry_owner_actor_id)s, %(registry_actor_role)s,
    %(registry_authn_schema_version)s
)
"""


def register_verified_original_docx_source(
    *,
    store: object,
    actor: SourceRegistryActor | SourceRegistryDenied,
    source: VerifiedOriginalDocxSource,
) -> RegisteredOriginalDocxSource | SourceRegistryDenied:
    """Register an already verified ORIGINAL DOCX source without exposing its key."""
    denial = _actor_or_capability_denial(store, actor)
    if denial is not None:
        return denial
    assert isinstance(actor, SourceRegistryActor)
    if isinstance(store, SQLiteTranslationJobStore):
        return _register_sqlite(store, source, actor)
    if _is_postgres_store(store):
        return _register_postgres(store, source, actor)
    return SourceRegistryDenied("source_registry_unsupported_backend")


def _register_sqlite(
    store: SQLiteTranslationJobStore,
    source: VerifiedOriginalDocxSource,
    actor: SourceRegistryActor,
) -> RegisteredOriginalDocxSource | SourceRegistryDenied:
    connection = store._connection
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """SELECT document_custody_id, source_sha256, source_size_bytes,
            document_kind, registry_owner_actor_id, registry_actor_role,
            registry_authn_schema_version
            FROM strict_docx_v3_document_custody WHERE source_object_key = ?""",
            (source.object_key,),
        ).fetchone()
        if row is None:
            result = _insert_sqlite_registration(connection, source, actor)
            event_type = "registered"
        else:
            result_or_denial = _reused_registration(row, source, actor)
            if isinstance(result_or_denial, SourceRegistryDenied):
                connection.rollback()
                return result_or_denial
            result = result_or_denial
            event_type = "registration_reused"
        _insert_sqlite_event(connection, result.document_custody_id, event_type, actor)
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise


def _register_postgres(
    store: object,
    source: VerifiedOriginalDocxSource,
    actor: SourceRegistryActor,
) -> RegisteredOriginalDocxSource | SourceRegistryDenied:
    connection = _postgres_connection(store)
    with connection.transaction():
        inserted = connection.execute(
            _POSTGRES_INSERT_CUSTODY_SQL,
            {
                "document_custody_id": f"document-custody-{uuid4().hex}",
                "source_object_key": source.object_key,
                "source_sha256": source.sha256,
                "source_size_bytes": source.size_bytes,
                "registry_owner_actor_id": actor.actor_id,
                "registry_actor_role": actor.role,
                "registry_authn_schema_version": actor.authn_schema_version,
            },
        ).fetchone()
        row = connection.execute(
            _POSTGRES_SELECT_BY_KEY_SQL,
            {"source_object_key": source.object_key},
        ).fetchone()
        if row is None:
            return SourceRegistryDenied("source_registry_custody_not_found")
        result_or_denial = _reused_registration(row, source, actor)
        if isinstance(result_or_denial, SourceRegistryDenied):
            return result_or_denial
        result = result_or_denial
        event_type = "registered" if inserted is not None else "registration_reused"
        connection.execute(
            _POSTGRES_INSERT_EVENT_SQL,
            {
                "registry_event_id": f"source-registry-event-{uuid4().hex}",
                "document_custody_id": result.document_custody_id,
                "event_type": event_type,
                "registry_owner_actor_id": actor.actor_id,
                "registry_actor_role": actor.role,
                "registry_authn_schema_version": actor.authn_schema_version,
            },
        )
    return result


def select_registered_original_docx_source(
    *,
    store: object,
    storage: LocalObjectStorage,
    actor: SourceRegistryActor | SourceRegistryDenied,
    document_custody_id: str,
) -> RegisteredOriginalDocxSource | SourceRegistryDenied:
    """Select actor-owned metadata after re-verifying its hidden storage identity."""
    denial = _actor_or_capability_denial(store, actor)
    if denial is not None:
        return denial
    assert isinstance(actor, SourceRegistryActor)
    if isinstance(store, SQLiteTranslationJobStore):
        row = store._connection.execute(
            """SELECT document_custody_id, source_object_key, source_sha256,
            source_size_bytes, document_kind, registry_owner_actor_id,
            registry_actor_role, registry_authn_schema_version
            FROM strict_docx_v3_document_custody WHERE document_custody_id = ?""",
            (document_custody_id,),
        ).fetchone()
    elif _is_postgres_store(store):
        row = _postgres_connection(store).execute(
            _POSTGRES_SELECT_BY_CUSTODY_SQL,
            {"document_custody_id": document_custody_id},
        ).fetchone()
    else:
        return SourceRegistryDenied("source_registry_unsupported_backend")
    if row is None:
        return SourceRegistryDenied("source_registry_custody_not_found")
    ownership_denial = _ownership_denial(row, actor)
    if ownership_denial is not None:
        return ownership_denial
    source = verify_original_docx_source(storage, row["source_object_key"])
    if isinstance(source, VerifiedOriginalDocxDenied):
        return SourceRegistryDenied(f"source_registry_source_{source.code}")
    if not _exact_source_identity(row, source):
        return SourceRegistryDenied("source_registry_reconciliation_denied")
    return _metadata_from_row(row)


def _actor_or_capability_denial(
    store: object,
    actor: SourceRegistryActor | SourceRegistryDenied,
) -> SourceRegistryDenied | None:
    if isinstance(actor, SourceRegistryDenied):
        return actor
    if (
        not isinstance(actor, SourceRegistryActor)
        or not actor.actor_id
        or actor.role != "owner"
        or not actor.authn_schema_version
    ):
        return SourceRegistryDenied("source_registry_actor_unauthorized")
    return None


def _insert_sqlite_registration(
    connection,
    source: VerifiedOriginalDocxSource,
    actor: SourceRegistryActor,
) -> RegisteredOriginalDocxSource:
    result = RegisteredOriginalDocxSource(
        document_custody_id=f"document-custody-{uuid4().hex}",
        source_sha256=source.sha256,
        source_size_bytes=source.size_bytes,
    )
    connection.execute(
        """INSERT INTO strict_docx_v3_document_custody (
        document_custody_id, source_object_key, source_sha256, source_size_bytes,
        document_kind, created_at, registry_owner_actor_id, registry_actor_role,
        registry_authn_schema_version
        ) VALUES (?, ?, ?, ?, 'docx', ?, ?, ?, ?)""",
        (
            result.document_custody_id,
            source.object_key,
            source.sha256,
            source.size_bytes,
            _to_db_time(_now()),
            actor.actor_id,
            actor.role,
            actor.authn_schema_version,
        ),
    )
    return result


def _reused_registration(
    row,
    source: VerifiedOriginalDocxSource,
    actor: SourceRegistryActor,
) -> RegisteredOriginalDocxSource | SourceRegistryDenied:
    if not _exact_source_identity(row, source):
        return SourceRegistryDenied("source_registry_custody_denied")
    ownership_denial = _ownership_denial(row, actor)
    if ownership_denial is not None:
        return ownership_denial
    return _metadata_from_row(row)


def _exact_source_identity(row, source: VerifiedOriginalDocxSource) -> bool:
    return (
        row["source_sha256"] == source.sha256
        and row["source_size_bytes"] == source.size_bytes
        and row["document_kind"] == "docx"
    )


def _ownership_denial(row, actor: SourceRegistryActor) -> SourceRegistryDenied | None:
    ownership = (
        row["registry_owner_actor_id"],
        row["registry_actor_role"],
        row["registry_authn_schema_version"],
    )
    if any(value is None for value in ownership):
        return SourceRegistryDenied("source_registry_reconciliation_denied")
    if ownership != (actor.actor_id, actor.role, actor.authn_schema_version):
        return SourceRegistryDenied("source_registry_ownership_denied")
    return None


def _insert_sqlite_event(
    connection,
    document_custody_id: str,
    event_type: str,
    actor: SourceRegistryActor,
) -> None:
    connection.execute(
        """INSERT INTO source_registry_events (
        registry_event_id, document_custody_id, event_type, registry_owner_actor_id,
        registry_actor_role, registry_authn_schema_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            f"source-registry-event-{uuid4().hex}",
            document_custody_id,
            event_type,
            actor.actor_id,
            actor.role,
            actor.authn_schema_version,
            _to_db_time(_now()),
        ),
    )


def _is_postgres_store(store: object) -> bool:
    return hasattr(store, "connection") and hasattr(
        _postgres_connection(store), "transaction"
    )


def _postgres_connection(store: object):
    return object.__getattribute__(store, "connection")


def _metadata_from_row(row) -> RegisteredOriginalDocxSource:
    return RegisteredOriginalDocxSource(
        document_custody_id=row["document_custody_id"],
        source_sha256=row["source_sha256"],
        source_size_bytes=row["source_size_bytes"],
    )
