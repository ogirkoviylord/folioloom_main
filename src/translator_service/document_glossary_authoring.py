from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from translator_service.admin.auth import AdminSession
from translator_service.admin.rbac import AdminRole
from translator_service.file_storage import (
    LocalObjectStorage,
    StoredFile,
    StoredFileKind,
)
from translator_service.glossary_contracts import (
    GlossarySnapshot,
    glossary_snapshot_signature,
)
from translator_service.glossary_snapshot_serialization import (
    GLOSSARY_SNAPSHOT_SERIALIZATION_VERSION,
    GlossarySnapshotSerializationError,
    deserialize_glossary_snapshot_v1,
    serialize_glossary_snapshot_v1,
    snapshot_payload_sha256,
)
from translator_service.persistent_job_store import (
    document_glossary_authoring_capability_denial_code,
)
from translator_service.persistent_jobs import (
    GLOSSARY_APPROVAL_SCHEMA_VERSION,
    GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
    DocumentGlossaryRevision,
    SQLiteTranslationJobStore,
    _from_db_time,
    _now,
    _to_db_time,
)

_GLOSSARY_AUTHORING_AUTHN_SCHEMA_VERSION = "admin-session-v1"


@dataclass(frozen=True)
class GlossaryAuthoringActor:
    actor_id: str
    role: str
    authn_schema_version: str = _GLOSSARY_AUTHORING_AUTHN_SCHEMA_VERSION


@dataclass(frozen=True)
class GlossaryAuthoringDenied:
    code: str


@dataclass(frozen=True)
class VerifiedDocxCustody:
    document_custody_id: str
    source_object_key: str
    source_sha256: str
    source_size_bytes: int


def glossary_authoring_actor_from_session(
    session: AdminSession,
) -> GlossaryAuthoringActor | GlossaryAuthoringDenied:
    if not isinstance(session, AdminSession) or session.expires_at <= datetime.now(UTC):
        return GlossaryAuthoringDenied("glossary_authoring_session_invalid")
    return GlossaryAuthoringActor(
        actor_id=session.actor_id,
        role=session.role.value,
    )


def create_document_glossary_revision(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    actor: GlossaryAuthoringActor | GlossaryAuthoringDenied,
    source_object_key: str,
    snapshot: GlossarySnapshot,
    expected_parent_revision_id: str | None,
) -> DocumentGlossaryRevision | GlossaryAuthoringDenied:
    denial = _actor_denial(actor)
    if denial is not None:
        return denial
    assert isinstance(actor, GlossaryAuthoringActor)
    capability_denial = document_glossary_authoring_capability_denial_code(store)
    if capability_denial is not None:
        return GlossaryAuthoringDenied(capability_denial)
    if not isinstance(store, SQLiteTranslationJobStore):
        return GlossaryAuthoringDenied("glossary_authoring_unsupported_backend")
    try:
        payload = serialize_glossary_snapshot_v1(snapshot)
    except GlossarySnapshotSerializationError:
        return GlossaryAuthoringDenied("glossary_authoring_snapshot_invalid")
    source = _verified_original_docx_source(storage, source_object_key)
    if isinstance(source, GlossaryAuthoringDenied):
        return source
    payload_digest = snapshot_payload_sha256(payload)
    content_signature = glossary_snapshot_signature(snapshot)
    connection = store._connection
    try:
        connection.execute("BEGIN IMMEDIATE")
        result = _create_revision_in_transaction(
            connection=connection,
            source=source,
            actor=actor,
            payload=payload,
            payload_digest=payload_digest,
            content_signature=content_signature,
            expected_parent_revision_id=expected_parent_revision_id,
        )
        if isinstance(result, GlossaryAuthoringDenied):
            connection.rollback()
            return result
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return result


def _actor_denial(
    actor: GlossaryAuthoringActor | GlossaryAuthoringDenied,
) -> GlossaryAuthoringDenied | None:
    if isinstance(actor, GlossaryAuthoringDenied):
        return actor
    if not isinstance(actor, GlossaryAuthoringActor):
        return GlossaryAuthoringDenied("glossary_authoring_actor_unauthorized")
    if actor.actor_id != "bootstrap-owner" or actor.role != AdminRole.OWNER.value:
        return GlossaryAuthoringDenied("glossary_authoring_actor_unauthorized")
    if actor.authn_schema_version != _GLOSSARY_AUTHORING_AUTHN_SCHEMA_VERSION:
        return GlossaryAuthoringDenied("glossary_authoring_session_invalid")
    return None


def _create_revision_in_transaction(
    *,
    connection,
    source,
    actor: GlossaryAuthoringActor,
    payload: bytes,
    payload_digest: str,
    content_signature: str,
    expected_parent_revision_id: str | None,
) -> DocumentGlossaryRevision | GlossaryAuthoringDenied:
    now = _now()
    custody = connection.execute(
        "SELECT * FROM strict_docx_v3_document_custody WHERE source_object_key = ?",
        (source.object_key,),
    ).fetchone()
    if custody is None:
        custody_id = f"document-custody-{uuid4().hex}"
        connection.execute(
            """
            INSERT INTO strict_docx_v3_document_custody (
                document_custody_id, source_object_key, source_sha256,
                source_size_bytes, document_kind, created_at
            ) VALUES (?, ?, ?, ?, 'docx', ?)
            """,
            (
                custody_id,
                source.object_key,
                source.sha256,
                source.size_bytes,
                _to_db_time(now),
            ),
        )
    elif (
        custody["source_sha256"] != source.sha256
        or custody["source_size_bytes"] != source.size_bytes
        or custody["document_kind"] != "docx"
    ):
        return GlossaryAuthoringDenied("glossary_authoring_document_custody_conflict")
    else:
        custody_id = custody["document_custody_id"]

    active = _active_revision(connection, custody_id)
    if expected_parent_revision_id is None and active is not None:
        return GlossaryAuthoringDenied("glossary_authoring_parent_not_current")
    if expected_parent_revision_id is not None and (
        active is None or active["revision_id"] != expected_parent_revision_id
    ):
        return GlossaryAuthoringDenied("glossary_authoring_parent_not_current")
    duplicate = connection.execute(
        """SELECT revision_id FROM document_glossary_revisions
        WHERE document_custody_id = ? AND snapshot_payload_sha256 = ?""",
        (custody_id, payload_digest),
    ).fetchone()
    if duplicate is not None:
        return GlossaryAuthoringDenied("glossary_authoring_duplicate_snapshot")
    sequence = 1 if active is None else active["revision_sequence"] + 1
    existing_custody = connection.execute(
        "SELECT custody_id FROM glossary_snapshot_custody WHERE snapshot_digest = ?",
        (payload_digest,),
    ).fetchone()
    snapshot_custody_id = (
        existing_custody["custody_id"]
        if existing_custody is not None
        else f"custody-{uuid4().hex}"
    )
    if existing_custody is None:
        connection.execute(
            """
            INSERT INTO glossary_snapshot_custody (
                custody_id, snapshot_payload, snapshot_digest,
                snapshot_schema_version, created_at, retention_mode
            ) VALUES (?, ?, ?, ?, ?, 'retain')
            """,
            (
                snapshot_custody_id,
                payload,
                payload_digest,
                GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
                _to_db_time(now),
            ),
        )
    approval_id = f"approval-{uuid4().hex}"
    connection.execute(
        """
        INSERT INTO glossary_approvals (
            approval_id, custody_id, snapshot_digest, approval_schema_version,
            approval_status, created_at, revoked_at
        ) VALUES (?, ?, ?, ?, 'approved', ?, NULL)
        """,
        (
            approval_id,
            snapshot_custody_id,
            payload_digest,
            GLOSSARY_APPROVAL_SCHEMA_VERSION,
            _to_db_time(now),
        ),
    )
    revision_id = f"document-glossary-revision-{uuid4().hex}"
    connection.execute(
        """
        INSERT INTO document_glossary_revisions (
            revision_id, document_custody_id, revision_sequence, parent_revision_id,
            approval_id, snapshot_custody_id, snapshot_payload_sha256,
            glossary_content_signature, snapshot_schema_version,
            serialization_schema_version, actor_id, actor_role,
            authn_schema_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            revision_id,
            custody_id,
            sequence,
            expected_parent_revision_id,
            approval_id,
            snapshot_custody_id,
            payload_digest,
            content_signature,
            GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
            GLOSSARY_SNAPSHOT_SERIALIZATION_VERSION,
            actor.actor_id,
            actor.role,
            actor.authn_schema_version,
            _to_db_time(now),
        ),
    )
    connection.execute(
        """
        INSERT INTO document_glossary_revision_events (
            event_id, revision_id, event_type, successor_revision_id, actor_id,
            actor_role, authn_schema_version, created_at
        ) VALUES (?, ?, 'created', NULL, ?, ?, ?, ?)
        """,
        (
            f"document-glossary-event-{uuid4().hex}",
            revision_id,
            actor.actor_id,
            actor.role,
            actor.authn_schema_version,
            _to_db_time(now),
        ),
    )
    return DocumentGlossaryRevision(
        revision_id=revision_id,
        document_custody_id=custody_id,
        source_object_key=source.object_key,
        source_sha256=source.sha256,
        source_size_bytes=source.size_bytes,
        revision_sequence=sequence,
        parent_revision_id=expected_parent_revision_id,
        approval_id=approval_id,
        snapshot_custody_id=snapshot_custody_id,
        snapshot_payload_sha256=payload_digest,
        glossary_content_signature=content_signature,
        actor_id=actor.actor_id,
        actor_role=actor.role,
        authn_schema_version=actor.authn_schema_version,
        created_at=now,
    )


def _verified_original_docx_source(
    storage: LocalObjectStorage, source_object_key: str
) -> StoredFile | GlossaryAuthoringDenied:
    try:
        metadata = storage.get_metadata(source_object_key)
        content = storage.get_bytes(source_object_key)
    except (FileNotFoundError, KeyError, ValueError):
        return GlossaryAuthoringDenied("glossary_authoring_document_missing")
    if metadata.object_key != source_object_key:
        return GlossaryAuthoringDenied("glossary_authoring_document_metadata_mismatch")
    if (
        metadata.kind is not StoredFileKind.ORIGINAL
        or not metadata.file_name.lower().endswith(".docx")
    ):
        return GlossaryAuthoringDenied("glossary_authoring_document_kind_invalid")
    if metadata.size_bytes != len(content):
        return GlossaryAuthoringDenied("glossary_authoring_document_size_mismatch")
    if metadata.sha256 != sha256(content).hexdigest():
        return GlossaryAuthoringDenied("glossary_authoring_document_digest_mismatch")
    return metadata


def _active_revision(connection, custody_id: str):
    return connection.execute(
        """
        SELECT revision.* FROM document_glossary_revisions revision
        JOIN glossary_approvals approval ON approval.approval_id = revision.approval_id
        WHERE revision.document_custody_id = ?
          AND approval.approval_status = 'approved'
          AND NOT EXISTS (
              SELECT 1 FROM document_glossary_revision_events event
              WHERE event.revision_id = revision.revision_id
                AND event.event_type IN ('superseded', 'revoked')
          )
        ORDER BY revision.revision_sequence DESC
        """,
        (custody_id,),
    ).fetchone()


def register_verified_docx_custody(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    source_object_key: str,
) -> VerifiedDocxCustody | GlossaryAuthoringDenied:
    """Register verified ORIGINAL DOCX custody without authorization or approval."""
    capability_denial = document_glossary_authoring_capability_denial_code(store)
    if capability_denial is not None:
        return GlossaryAuthoringDenied(capability_denial)
    if not isinstance(store, SQLiteTranslationJobStore):
        return GlossaryAuthoringDenied("glossary_authoring_unsupported_backend")
    source = _verified_original_docx_source(storage, source_object_key)
    if isinstance(source, GlossaryAuthoringDenied):
        return source
    connection = store._connection
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM strict_docx_v3_document_custody WHERE source_object_key = ?",
            (source.object_key,),
        ).fetchone()
        if row is None:
            result = VerifiedDocxCustody(
                f"document-custody-{uuid4().hex}",
                source.object_key,
                source.sha256,
                source.size_bytes,
            )
            connection.execute(
                """INSERT INTO strict_docx_v3_document_custody (
                document_custody_id, source_object_key, source_sha256,
                source_size_bytes, document_kind, created_at
                ) VALUES (?, ?, ?, ?, 'docx', ?)""",
                (
                    result.document_custody_id,
                    result.source_object_key,
                    result.source_sha256,
                    result.source_size_bytes,
                    _to_db_time(_now()),
                ),
            )
        elif (
            row["source_sha256"] != source.sha256
            or row["source_size_bytes"] != source.size_bytes
            or row["document_kind"] != "docx"
        ):
            connection.rollback()
            return GlossaryAuthoringDenied(
                "glossary_authoring_document_custody_conflict"
            )
        else:
            result = VerifiedDocxCustody(
                row["document_custody_id"],
                row["source_object_key"],
                row["source_sha256"],
                row["source_size_bytes"],
            )
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise


def supersede_document_glossary_revision(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    actor: GlossaryAuthoringActor | GlossaryAuthoringDenied,
    predecessor_revision_id: str,
    snapshot: GlossarySnapshot,
) -> DocumentGlossaryRevision | GlossaryAuthoringDenied:
    denial = _actor_denial(actor)
    if denial is not None:
        return denial
    capability_denial = document_glossary_authoring_capability_denial_code(store)
    if capability_denial is not None:
        return GlossaryAuthoringDenied(capability_denial)
    if not isinstance(store, SQLiteTranslationJobStore):
        return GlossaryAuthoringDenied("glossary_authoring_unsupported_backend")
    assert isinstance(actor, GlossaryAuthoringActor)
    try:
        payload = serialize_glossary_snapshot_v1(snapshot)
    except GlossarySnapshotSerializationError:
        return GlossaryAuthoringDenied("glossary_authoring_snapshot_invalid")
    payload_digest = snapshot_payload_sha256(payload)
    content_signature = glossary_snapshot_signature(snapshot)
    connection = store._connection
    predecessor = _revision_row(connection, predecessor_revision_id)
    if predecessor is None:
        return GlossaryAuthoringDenied("glossary_authoring_parent_missing")
    source = _verified_original_docx_source(storage, predecessor["source_object_key"])
    if isinstance(source, GlossaryAuthoringDenied):
        return source
    try:
        connection.execute("BEGIN IMMEDIATE")
        predecessor = _revision_row(connection, predecessor_revision_id)
        if predecessor is None:
            connection.rollback()
            return GlossaryAuthoringDenied("glossary_authoring_parent_missing")
        result = _create_revision_in_transaction(
            connection=connection,
            source=source,
            actor=actor,
            payload=payload,
            payload_digest=payload_digest,
            content_signature=content_signature,
            expected_parent_revision_id=predecessor_revision_id,
        )
        if isinstance(result, GlossaryAuthoringDenied):
            connection.rollback()
            return result
        connection.execute(
            """INSERT INTO document_glossary_revision_events (
            event_id, revision_id, event_type, successor_revision_id, actor_id,
            actor_role, authn_schema_version, created_at
            ) VALUES (?, ?, 'superseded', ?, ?, ?, ?, ?)""",
            (
                f"document-glossary-event-{uuid4().hex}",
                predecessor_revision_id,
                result.revision_id,
                result.actor_id,
                result.actor_role,
                result.authn_schema_version,
                _to_db_time(_now()),
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return result


def revoke_document_glossary_revision(
    *,
    store: SQLiteTranslationJobStore,
    actor: GlossaryAuthoringActor | GlossaryAuthoringDenied,
    revision_id: str,
) -> DocumentGlossaryRevision | GlossaryAuthoringDenied:
    denial = _actor_denial(actor)
    if denial is not None:
        return denial
    capability_denial = document_glossary_authoring_capability_denial_code(store)
    if capability_denial is not None:
        return GlossaryAuthoringDenied(capability_denial)
    if not isinstance(store, SQLiteTranslationJobStore):
        return GlossaryAuthoringDenied("glossary_authoring_unsupported_backend")
    assert isinstance(actor, GlossaryAuthoringActor)
    connection = store._connection
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = _revision_row(connection, revision_id)
        active = (
            _active_revision(connection, row["document_custody_id"]) if row else None
        )
        if active is None or active["revision_id"] != revision_id:
            connection.rollback()
            return GlossaryAuthoringDenied("glossary_authoring_parent_not_current")
        now = _now()
        connection.execute(
            """
            UPDATE glossary_approvals
            SET approval_status = 'revoked', revoked_at = ?
            WHERE approval_id = ?
            """,
            (_to_db_time(now), row["approval_id"]),
        )
        connection.execute(
            """INSERT INTO document_glossary_revision_events (
            event_id, revision_id, event_type, successor_revision_id, actor_id,
            actor_role, authn_schema_version, created_at
            ) VALUES (?, ?, 'revoked', NULL, ?, ?, ?, ?)""",
            (
                f"document-glossary-event-{uuid4().hex}",
                revision_id,
                actor.actor_id,
                actor.role,
                actor.authn_schema_version,
                _to_db_time(now),
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return _revision_from_row(row)


def read_active_document_glossary_revision(
    *,
    store: SQLiteTranslationJobStore,
    document_custody_id: str,
) -> DocumentGlossaryRevision | GlossaryAuthoringDenied:
    capability_denial = document_glossary_authoring_capability_denial_code(store)
    if capability_denial is not None:
        return GlossaryAuthoringDenied(capability_denial)
    if not isinstance(store, SQLiteTranslationJobStore):
        return GlossaryAuthoringDenied("glossary_authoring_unsupported_backend")
    row = _active_revision(store._connection, document_custody_id)
    if row is None:
        return GlossaryAuthoringDenied("glossary_authoring_approval_revoked")
    if not _revision_is_consistent(store._connection, row):
        return GlossaryAuthoringDenied("glossary_authoring_provenance_inconsistent")
    return _revision_from_row(_revision_row(store._connection, row["revision_id"]))


def _revision_row(connection, revision_id: str):
    return connection.execute(
        """SELECT revision.*, custody.source_object_key, custody.source_sha256,
        custody.source_size_bytes FROM document_glossary_revisions revision
        JOIN strict_docx_v3_document_custody custody
        ON custody.document_custody_id = revision.document_custody_id
        WHERE revision.revision_id = ?""",
        (revision_id,),
    ).fetchone()


def _revision_from_row(row) -> DocumentGlossaryRevision:
    return DocumentGlossaryRevision(
        revision_id=row["revision_id"],
        document_custody_id=row["document_custody_id"],
        source_object_key=row["source_object_key"],
        source_sha256=row["source_sha256"],
        source_size_bytes=row["source_size_bytes"],
        revision_sequence=row["revision_sequence"],
        parent_revision_id=row["parent_revision_id"],
        approval_id=row["approval_id"],
        snapshot_custody_id=row["snapshot_custody_id"],
        snapshot_payload_sha256=row["snapshot_payload_sha256"],
        glossary_content_signature=row["glossary_content_signature"],
        actor_id=row["actor_id"],
        actor_role=row["actor_role"],
        authn_schema_version=row["authn_schema_version"],
        created_at=_from_db_time(row["created_at"]),
    )


def _revision_is_consistent(connection, revision) -> bool:
    """Validate the active revision and every predecessor event in its lineage."""
    successor = None
    seen_revision_ids = set()
    current = revision
    while current is not None:
        revision_id = current["revision_id"]
        if revision_id in seen_revision_ids:
            return False
        seen_revision_ids.add(revision_id)
        if not _revision_payload_is_consistent(connection, current):
            return False
        events = connection.execute(
            """SELECT event_type, successor_revision_id, actor_id, actor_role,
            authn_schema_version FROM document_glossary_revision_events
            WHERE revision_id = ? ORDER BY created_at, event_id""",
            (revision_id,),
        ).fetchall()
        if not _revision_events_are_consistent(current, successor, events):
            return False
        parent_id = current["parent_revision_id"]
        if parent_id is None:
            return current["revision_sequence"] == 1
        parent = _revision_row(connection, parent_id)
        if (
            parent is None
            or parent["document_custody_id"] != current["document_custody_id"]
            or parent["revision_sequence"] != current["revision_sequence"] - 1
        ):
            return False
        successor = current
        current = parent
    return False


def _revision_payload_is_consistent(connection, revision) -> bool:
    if (
        revision["actor_id"] != "bootstrap-owner"
        or revision["actor_role"] != AdminRole.OWNER.value
        or revision["authn_schema_version"] != _GLOSSARY_AUTHORING_AUTHN_SCHEMA_VERSION
        or revision["snapshot_schema_version"] != GLOSSARY_SNAPSHOT_SCHEMA_VERSION
        or revision["serialization_schema_version"]
        != GLOSSARY_SNAPSHOT_SERIALIZATION_VERSION
    ):
        return False
    row = connection.execute(
        """SELECT custody.snapshot_payload, custody.snapshot_digest,
        approval.snapshot_digest AS approval_digest, approval.approval_status
        FROM glossary_approvals approval JOIN glossary_snapshot_custody custody
        ON custody.custody_id = approval.custody_id
        WHERE approval.approval_id = ? AND custody.custody_id = ?""",
        (revision["approval_id"], revision["snapshot_custody_id"]),
    ).fetchone()
    if row is None or row["approval_status"] != "approved":
        return False
    payload = bytes(row["snapshot_payload"])
    if (
        snapshot_payload_sha256(payload) != revision["snapshot_payload_sha256"]
        or row["snapshot_digest"] != revision["snapshot_payload_sha256"]
        or row["approval_digest"] != revision["snapshot_payload_sha256"]
    ):
        return False
    try:
        snapshot = deserialize_glossary_snapshot_v1(payload)
    except GlossarySnapshotSerializationError:
        return False
    return (
        glossary_snapshot_signature(snapshot)
        == revision["glossary_content_signature"]
    )


def _revision_events_are_consistent(revision, successor, events) -> bool:
    expected_count = 1 if successor is None else 2
    if len(events) != expected_count or events[0]["event_type"] != "created":
        return False
    created_event = events[0]
    if (
        created_event["successor_revision_id"] is not None
        or created_event["actor_id"] != revision["actor_id"]
        or created_event["actor_role"] != revision["actor_role"]
        or created_event["authn_schema_version"] != revision["authn_schema_version"]
    ):
        return False
    if successor is None:
        return True
    superseded_event = events[1]
    return (
        superseded_event["event_type"] == "superseded"
        and superseded_event["successor_revision_id"] == successor["revision_id"]
        and superseded_event["actor_id"] == successor["actor_id"]
        and superseded_event["actor_role"] == successor["actor_role"]
        and superseded_event["authn_schema_version"]
        == successor["authn_schema_version"]
    )
