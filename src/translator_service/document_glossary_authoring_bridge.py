"""Actor-owned, custody-ID-only durable glossary authoring boundary.

This module intentionally keeps storage identities and serialized snapshots inside
server-side operations. Its public values expose revision metadata only.
"""

from __future__ import annotations

# ruff: noqa: E501
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from translator_service.admin.auth import AdminSession
from translator_service.admin.rbac import AdminRole
from translator_service.document_glossary_authoring import _revision_is_consistent
from translator_service.document_glossary_lock_attestation import _postgres_current_row
from translator_service.file_storage import LocalObjectStorage
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
    SQLiteTranslationJobStore,
    _now,
    _to_db_time,
)
from translator_service.source_registry_service import (
    SourceRegistryActor,
    SourceRegistryDenied,
    select_registered_original_docx_source,
)

_AUTHN_SCHEMA_VERSION = "admin-session-v1"


@dataclass(frozen=True)
class DocumentGlossaryAuthoringBridgeDenied:
    code: str


@dataclass(frozen=True)
class DocumentGlossaryRevisionMetadata:
    document_custody_id: str
    revision_id: str
    revision_sequence: int
    parent_revision_id: str | None
    approval_id: str
    snapshot_custody_id: str
    outcome: str


@dataclass(frozen=True)
class DocumentGlossaryEditableRow:
    """The only glossary-entry fields permitted in the owner editor."""

    source_term: str
    target_term: str
    entry_type: str


@dataclass(frozen=True)
class DocumentGlossaryEditableProjection:
    """Safe current-snapshot fields for a browser-local working copy."""

    source_language: str
    target_language: str
    rows: tuple[DocumentGlossaryEditableRow, ...]


def author_document_glossary_revision(
    *,
    store: object,
    storage: LocalObjectStorage,
    session: AdminSession,
    document_custody_id: str,
    snapshot: GlossarySnapshot,
    expected_parent_revision_id: str | None,
) -> DocumentGlossaryRevisionMetadata | DocumentGlossaryAuthoringBridgeDenied:
    """Create a first or exact-parent successor revision without key disclosure."""
    actor = _actor_from_session(session)
    if isinstance(actor, DocumentGlossaryAuthoringBridgeDenied):
        return actor
    denial = _service_denial(store, storage, actor, document_custody_id)
    if denial is not None:
        return denial
    try:
        payload = serialize_glossary_snapshot_v1(snapshot)
    except GlossarySnapshotSerializationError:
        return DocumentGlossaryAuthoringBridgeDenied("glossary_authoring_snapshot_invalid")
    payload_digest = snapshot_payload_sha256(payload)
    content_signature = glossary_snapshot_signature(snapshot)
    if isinstance(store, SQLiteTranslationJobStore):
        return _author_sqlite(
            store._connection,
            document_custody_id,
            actor,
            payload,
            payload_digest,
            content_signature,
            expected_parent_revision_id,
        )
    if _is_postgres_store(store):
        return _author_postgres(
            store.connection,
            document_custody_id,
            actor,
            payload,
            payload_digest,
            content_signature,
            expected_parent_revision_id,
        )
    return DocumentGlossaryAuthoringBridgeDenied("glossary_authoring_unsupported_backend")


def read_current_document_glossary_revision(
    *,
    store: object,
    storage: LocalObjectStorage,
    session: AdminSession,
    document_custody_id: str,
) -> DocumentGlossaryRevisionMetadata | DocumentGlossaryAuthoringBridgeDenied:
    actor = _actor_from_session(session)
    if isinstance(actor, DocumentGlossaryAuthoringBridgeDenied):
        return actor
    denial = _service_denial(store, storage, actor, document_custody_id)
    if denial is not None:
        return denial
    if isinstance(store, SQLiteTranslationJobStore):
        row = _sqlite_active_row(store._connection, document_custody_id)
        if row is None or not _revision_is_consistent(store._connection, row):
            return DocumentGlossaryAuthoringBridgeDenied(
                "glossary_authoring_provenance_inconsistent"
            )
        return _metadata(row, "current")
    if _is_postgres_store(store):
        with store.connection.transaction():
            row = _postgres_current_row(
                store.connection, document_custody_id, actor, for_update=False
            )
            if row is None or not _postgres_revision_is_consistent(
                store.connection, row, actor
            ):
                return DocumentGlossaryAuthoringBridgeDenied(
                    "glossary_authoring_provenance_inconsistent"
                )
            return _metadata(row, "current")
    return DocumentGlossaryAuthoringBridgeDenied("glossary_authoring_unsupported_backend")


def read_current_document_glossary_editable_projection(
    *,
    store: object,
    storage: LocalObjectStorage,
    session: AdminSession,
    document_custody_id: str,
) -> DocumentGlossaryEditableProjection | DocumentGlossaryAuthoringBridgeDenied:
    """Read only canonical fields after the normal owner/provenance checks."""
    actor = _actor_from_session(session)
    if isinstance(actor, DocumentGlossaryAuthoringBridgeDenied):
        return actor
    denial = _service_denial(store, storage, actor, document_custody_id)
    if denial is not None:
        return denial
    if not isinstance(store, SQLiteTranslationJobStore):
        return DocumentGlossaryAuthoringBridgeDenied(
            "glossary_authoring_unsupported_backend"
        )
    revision = _sqlite_active_row(store._connection, document_custody_id)
    if revision is None or not _revision_is_consistent(store._connection, revision):
        return DocumentGlossaryAuthoringBridgeDenied(
            "glossary_authoring_provenance_inconsistent"
        )
    row = store._connection.execute(
        """SELECT snapshot_payload FROM glossary_snapshot_custody
        WHERE custody_id = ? AND snapshot_digest = ?""",
        (revision["snapshot_custody_id"], revision["snapshot_payload_sha256"]),
    ).fetchone()
    if row is None:
        return DocumentGlossaryAuthoringBridgeDenied(
            "glossary_authoring_provenance_inconsistent"
        )
    try:
        snapshot = deserialize_glossary_snapshot_v1(bytes(row["snapshot_payload"]))
        rows = tuple(
            DocumentGlossaryEditableRow(
                source_term=entry.source_canonical,
                target_term=entry.target_canonical or "",
                entry_type=str(entry.category),
            )
            for entry in snapshot.entries
        )
    except (GlossarySnapshotSerializationError, TypeError, ValueError):
        return DocumentGlossaryAuthoringBridgeDenied(
            "glossary_authoring_provenance_inconsistent"
        )
    if not rows or any(row.entry_type not in {"term", "name"} for row in rows):
        return DocumentGlossaryAuthoringBridgeDenied(
            "glossary_authoring_provenance_inconsistent"
        )
    return DocumentGlossaryEditableProjection(
        source_language=snapshot.source_language,
        target_language=snapshot.target_language,
        rows=rows,
    )


def _actor_from_session(
    session: AdminSession,
) -> SourceRegistryActor | DocumentGlossaryAuthoringBridgeDenied:
    if not isinstance(session, AdminSession) or session.expires_at <= datetime.now(UTC):
        return DocumentGlossaryAuthoringBridgeDenied("glossary_authoring_session_invalid")
    if session.actor_id != "bootstrap-owner" or session.role is not AdminRole.OWNER:
        return DocumentGlossaryAuthoringBridgeDenied("glossary_authoring_actor_unauthorized")
    return SourceRegistryActor("bootstrap-owner", "owner", _AUTHN_SCHEMA_VERSION)


def _service_denial(store, storage, actor, document_custody_id):
    capability = document_glossary_authoring_capability_denial_code(store)
    if capability is not None:
        return DocumentGlossaryAuthoringBridgeDenied(capability)
    selected = select_registered_original_docx_source(
        store=store,
        storage=storage,
        actor=actor,
        document_custody_id=document_custody_id,
    )
    if isinstance(selected, SourceRegistryDenied):
        return DocumentGlossaryAuthoringBridgeDenied(f"glossary_authoring_{selected.code}")
    return None


def _author_sqlite(connection, custody_id, actor, payload, digest, signature, parent_id):
    try:
        connection.execute("BEGIN IMMEDIATE")
        result = _create_in_transaction(
            connection, custody_id, actor, payload, digest, signature, parent_id, sqlite=True
        )
        if isinstance(result, DocumentGlossaryAuthoringBridgeDenied):
            connection.rollback()
            return result
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise


def _author_postgres(connection, custody_id, actor, payload, digest, signature, parent_id):
    with connection.transaction():
        return _create_in_transaction(
            connection, custody_id, actor, payload, digest, signature, parent_id, sqlite=False
        )


def _create_in_transaction(
    connection, custody_id, actor, payload, digest, signature, parent_id, *, sqlite
):
    active = _sqlite_active_row(connection, custody_id) if sqlite else connection.execute(
        _POSTGRES_ACTIVE_REVISION_FOR_UPDATE_SQL, {"document_custody_id": custody_id}
    ).fetchone()
    if (parent_id is None and active is not None) or (
        parent_id is not None and (active is None or active["revision_id"] != parent_id)
    ):
        return DocumentGlossaryAuthoringBridgeDenied("glossary_authoring_parent_not_current")
    if active is not None and _active_revision_is_locked(
        connection, active, actor, sqlite=sqlite
    ):
        return DocumentGlossaryAuthoringBridgeDenied("glossary_authoring_locked")
    duplicate_sql = (
        "SELECT revision_id FROM document_glossary_revisions WHERE document_custody_id = ? "
        "AND snapshot_payload_sha256 = ?"
        if sqlite
        else _POSTGRES_DUPLICATE_SQL
    )
    duplicate_params = (custody_id, digest) if sqlite else {
        "document_custody_id": custody_id, "snapshot_digest": digest
    }
    if connection.execute(duplicate_sql, duplicate_params).fetchone() is not None:
        return DocumentGlossaryAuthoringBridgeDenied("glossary_authoring_duplicate_snapshot")
    sequence = 1 if active is None else active["revision_sequence"] + 1
    snapshot_id = f"custody-{uuid4().hex}"
    approval_id = f"approval-{uuid4().hex}"
    revision_id = f"document-glossary-revision-{uuid4().hex}"
    now = _to_db_time(_now())
    if sqlite:
        existing = connection.execute(
            "SELECT custody_id FROM glossary_snapshot_custody WHERE snapshot_digest = ?", (digest,)
        ).fetchone()
        if existing is not None:
            snapshot_id = existing["custody_id"]
        else:
            connection.execute(
                """INSERT INTO glossary_snapshot_custody (custody_id, snapshot_payload,
                snapshot_digest, snapshot_schema_version, created_at, retention_mode)
                VALUES (?, ?, ?, ?, ?, 'retain')""",
                (snapshot_id, payload, digest, GLOSSARY_SNAPSHOT_SCHEMA_VERSION, now),
            )
        _insert_sqlite_revision(
            connection, custody_id, actor, digest, signature, parent_id, sequence,
            snapshot_id, approval_id, revision_id, now
        )
    else:
        row = connection.execute(_POSTGRES_INSERT_SNAPSHOT_SQL, {
            "custody_id": snapshot_id, "snapshot_payload": payload,
            "snapshot_digest": digest, "snapshot_schema_version": GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
        }).fetchone()
        if row is None:
            existing = connection.execute(_POSTGRES_SNAPSHOT_BY_DIGEST_SQL, {"snapshot_digest": digest}).fetchone()
            if existing is None:
                return DocumentGlossaryAuthoringBridgeDenied("glossary_authoring_conflict")
            snapshot_id = existing["custody_id"]
        else:
            snapshot_id = row["custody_id"]
        _insert_postgres_revision(
            connection, custody_id, actor, digest, signature, parent_id, sequence,
            snapshot_id, approval_id, revision_id
        )
    if active is not None:
        _insert_event(connection, parent_id, revision_id, actor, now, sqlite=sqlite, event_type="superseded")
    return DocumentGlossaryRevisionMetadata(
        custody_id, revision_id, sequence, parent_id, approval_id, snapshot_id, "created"
    )


def _insert_sqlite_revision(connection, custody_id, actor, digest, signature, parent_id, sequence, snapshot_id, approval_id, revision_id, now):
    connection.execute(
        """INSERT INTO glossary_approvals (approval_id, custody_id, snapshot_digest,
        approval_schema_version, approval_status, created_at, revoked_at)
        VALUES (?, ?, ?, ?, 'approved', ?, NULL)""",
        (approval_id, snapshot_id, digest, GLOSSARY_APPROVAL_SCHEMA_VERSION, now),
    )
    connection.execute(
        """INSERT INTO document_glossary_revisions (revision_id, document_custody_id,
        revision_sequence, parent_revision_id, approval_id, snapshot_custody_id,
        snapshot_payload_sha256, glossary_content_signature, snapshot_schema_version,
        serialization_schema_version, actor_id, actor_role, authn_schema_version, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (revision_id, custody_id, sequence, parent_id, approval_id, snapshot_id, digest,
         signature, GLOSSARY_SNAPSHOT_SCHEMA_VERSION, GLOSSARY_SNAPSHOT_SERIALIZATION_VERSION,
         actor.actor_id, actor.role, actor.authn_schema_version, now),
    )
    _insert_event(connection, revision_id, None, actor, now, sqlite=True, event_type="created")


def _insert_postgres_revision(connection, custody_id, actor, digest, signature, parent_id, sequence, snapshot_id, approval_id, revision_id):
    params = {"document_custody_id": custody_id, "revision_id": revision_id,
              "revision_sequence": sequence, "parent_revision_id": parent_id,
              "approval_id": approval_id, "snapshot_custody_id": snapshot_id,
              "snapshot_digest": digest, "content_signature": signature,
              "snapshot_schema_version": GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
              "serialization_schema_version": GLOSSARY_SNAPSHOT_SERIALIZATION_VERSION,
              "actor_id": actor.actor_id, "actor_role": actor.role,
              "authn_schema_version": actor.authn_schema_version}
    connection.execute(_POSTGRES_INSERT_APPROVAL_SQL, params)
    connection.execute(_POSTGRES_INSERT_REVISION_SQL, params)
    _insert_event(connection, revision_id, None, actor, None, sqlite=False, event_type="created")


def _insert_event(connection, revision_id, successor_id, actor, now, *, sqlite, event_type):
    event_id = f"document-glossary-event-{uuid4().hex}"
    if sqlite:
        connection.execute(
            """INSERT INTO document_glossary_revision_events (event_id, revision_id,
            event_type, successor_revision_id, actor_id, actor_role, authn_schema_version,
            created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, revision_id, event_type, successor_id, actor.actor_id, actor.role,
             actor.authn_schema_version, now),
        )
    else:
        connection.execute(_POSTGRES_INSERT_EVENT_SQL, {
            "event_id": event_id, "revision_id": revision_id, "event_type": event_type,
            "successor_revision_id": successor_id, "actor_id": actor.actor_id,
            "actor_role": actor.role, "authn_schema_version": actor.authn_schema_version,
        })


def _sqlite_active_row(connection, custody_id):
    return connection.execute(
        """SELECT revision.* FROM document_glossary_revisions revision
        JOIN glossary_approvals approval ON approval.approval_id = revision.approval_id
        WHERE revision.document_custody_id = ? AND approval.approval_status = 'approved'
        AND NOT EXISTS (SELECT 1 FROM document_glossary_revision_events event
                        WHERE event.revision_id = revision.revision_id
                          AND event.event_type IN ('superseded', 'revoked'))
        ORDER BY revision.revision_sequence DESC""", (custody_id,)
    ).fetchone()


def _active_revision_is_locked(connection, active, actor, *, sqlite):
    """Check the current revision lock tuple while its authoring lock is held."""
    if sqlite:
        return connection.execute(
            """SELECT 1 FROM document_glossary_lock_attestations WHERE
            document_custody_id = ? AND revision_id = ? AND approval_id = ?
            AND snapshot_custody_id = ? AND snapshot_digest = ?
            AND snapshot_schema_version = ? AND serialization_schema_version = ?
            AND approval_schema_version = ? AND attestation_schema_version = 1
            AND actor_id = ? AND actor_role = ? AND authn_schema_version = ? LIMIT 1""",
            (
                active["document_custody_id"], active["revision_id"],
                active["approval_id"], active["snapshot_custody_id"],
                active["snapshot_payload_sha256"], active["snapshot_schema_version"],
                active["serialization_schema_version"], GLOSSARY_APPROVAL_SCHEMA_VERSION,
                actor.actor_id, actor.role, actor.authn_schema_version,
            ),
        ).fetchone() is not None
    return connection.execute(
        _POSTGRES_ACTIVE_LOCK_SQL,
        {
            "document_custody_id": active["document_custody_id"],
            "revision_id": active["revision_id"], "approval_id": active["approval_id"],
            "snapshot_custody_id": active["snapshot_custody_id"],
            "snapshot_digest": active["snapshot_payload_sha256"],
            "snapshot_schema_version": active["snapshot_schema_version"],
            "serialization_schema_version": active["serialization_schema_version"],
            "approval_schema_version": GLOSSARY_APPROVAL_SCHEMA_VERSION,
            "actor_id": actor.actor_id, "actor_role": actor.role,
            "authn_schema_version": actor.authn_schema_version,
        },
    ).fetchone() is not None


def _metadata(row, outcome):
    return DocumentGlossaryRevisionMetadata(
        row["document_custody_id"], row["revision_id"], row["revision_sequence"],
        row["parent_revision_id"], row["approval_id"], row["snapshot_custody_id"], outcome
    )


def _is_postgres_store(store):
    return hasattr(store, "connection") and hasattr(store.connection, "transaction")


def _postgres_row_is_consistent(row, actor):
    """Validate bridge-specific fields which are not covered by attestation."""
    return (
        row["serialization_schema_version"]
        == GLOSSARY_SNAPSHOT_SERIALIZATION_VERSION
        and (row["actor_id"], row["actor_role"], row["authn_schema_version"])
        == (actor.actor_id, actor.role, actor.authn_schema_version)
    )


def _postgres_revision_is_consistent(connection, revision, actor):
    """Validate payload, ancestry, and event history without exposing custody data."""
    successor = None
    seen_revision_ids = set()
    current = connection.execute(
        _POSTGRES_REVISION_BY_ID_SQL, {"revision_id": revision["revision_id"]}
    ).fetchone()
    if current is None or not _postgres_current_row_matches(revision, current):
        return False
    while current is not None:
        revision_id = current["revision_id"]
        if revision_id in seen_revision_ids:
            return False
        seen_revision_ids.add(revision_id)
        if (
            not _postgres_payload_is_consistent(current, actor)
        ):
            return False
        events = connection.execute(
            _POSTGRES_REVISION_EVENTS_SQL, {"revision_id": revision_id}
        ).fetchall()
        if not _postgres_revision_events_are_consistent(current, successor, events):
            return False
        parent_id = current["parent_revision_id"]
        if parent_id is None:
            return current["revision_sequence"] == 1
        parent = connection.execute(
            _POSTGRES_REVISION_BY_ID_SQL, {"revision_id": parent_id}
        ).fetchone()
        if (
            parent is None
            or parent["document_custody_id"] != current["document_custody_id"]
            or parent["revision_sequence"] != current["revision_sequence"] - 1
        ):
            return False
        successor = current
        current = parent
    return False


def _postgres_current_row_matches(attested_row, revision):
    try:
        return all(
            attested_row[field] == revision[field]
            for field in (
                "document_custody_id",
                "revision_id",
                "revision_sequence",
                "parent_revision_id",
                "approval_id",
                "snapshot_custody_id",
                "snapshot_digest",
                "snapshot_schema_version",
                "serialization_schema_version",
                "actor_id",
                "actor_role",
                "authn_schema_version",
                "approval_custody_id",
                "approval_digest",
                "approval_schema_version",
                "approval_status",
                "custody_digest",
                "custody_schema",
            )
        )
    except KeyError:
        return False


def _postgres_payload_is_consistent(revision, actor):
    try:
        if not _postgres_row_is_consistent(revision, actor):
            return False
        if (
            revision["snapshot_schema_version"] != GLOSSARY_SNAPSHOT_SCHEMA_VERSION
            or revision["custody_schema"] != revision["snapshot_schema_version"]
            or revision["approval_schema_version"] != GLOSSARY_APPROVAL_SCHEMA_VERSION
            or revision["approval_status"] != "approved"
            or revision["approval_custody_id"] != revision["snapshot_custody_id"]
        ):
            return False
        payload = bytes(revision["snapshot_payload"])
        if (
            snapshot_payload_sha256(payload) != revision["snapshot_digest"]
            or revision["approval_digest"] != revision["snapshot_digest"]
            or revision["custody_digest"] != revision["snapshot_digest"]
        ):
            return False
        snapshot = deserialize_glossary_snapshot_v1(payload)
    except (GlossarySnapshotSerializationError, KeyError, TypeError, ValueError):
        return False
    return glossary_snapshot_signature(snapshot) == revision["glossary_content_signature"]


def _postgres_revision_events_are_consistent(revision, successor, events):
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


_POSTGRES_ACTIVE_REVISION_SQL = """SELECT revision.* FROM document_glossary_revisions revision
JOIN glossary_approvals approval ON approval.approval_id = revision.approval_id
WHERE revision.document_custody_id = %(document_custody_id)s
  AND approval.approval_status = 'approved'
  AND NOT EXISTS (SELECT 1 FROM document_glossary_revision_events event
                  WHERE event.revision_id = revision.revision_id
                    AND event.event_type IN ('superseded', 'revoked'))
ORDER BY revision.revision_sequence DESC LIMIT 1"""
_POSTGRES_ACTIVE_REVISION_FOR_UPDATE_SQL = _POSTGRES_ACTIVE_REVISION_SQL + " FOR UPDATE OF revision, approval"
_POSTGRES_REVISION_BY_ID_SQL = """SELECT revision.document_custody_id, revision.revision_id,
revision.revision_sequence, revision.parent_revision_id, revision.approval_id,
revision.snapshot_custody_id, revision.snapshot_payload_sha256 AS snapshot_digest,
revision.glossary_content_signature, revision.snapshot_schema_version,
revision.serialization_schema_version, revision.actor_id, revision.actor_role,
revision.authn_schema_version, approval.custody_id AS approval_custody_id,
approval.snapshot_digest AS approval_digest, approval.approval_schema_version,
approval.approval_status, snapshot.snapshot_payload,
snapshot.snapshot_digest AS custody_digest,
snapshot.snapshot_schema_version AS custody_schema
FROM document_glossary_revisions revision
JOIN glossary_approvals approval ON approval.approval_id = revision.approval_id
JOIN glossary_snapshot_custody snapshot
  ON snapshot.custody_id = revision.snapshot_custody_id
WHERE revision.revision_id = %(revision_id)s"""
_POSTGRES_REVISION_EVENTS_SQL = """SELECT event_type, successor_revision_id,
actor_id, actor_role, authn_schema_version
FROM document_glossary_revision_events
WHERE revision_id = %(revision_id)s ORDER BY created_at, event_id"""
_POSTGRES_DUPLICATE_SQL = """SELECT revision_id FROM document_glossary_revisions
WHERE document_custody_id = %(document_custody_id)s
  AND snapshot_payload_sha256 = %(snapshot_digest)s"""
_POSTGRES_ACTIVE_LOCK_SQL = """SELECT 1 FROM document_glossary_lock_attestations
WHERE document_custody_id = %(document_custody_id)s
  AND revision_id = %(revision_id)s AND approval_id = %(approval_id)s
  AND snapshot_custody_id = %(snapshot_custody_id)s
  AND snapshot_digest = %(snapshot_digest)s
  AND snapshot_schema_version = %(snapshot_schema_version)s
  AND serialization_schema_version = %(serialization_schema_version)s
  AND approval_schema_version = %(approval_schema_version)s
  AND attestation_schema_version = 1
  AND actor_id = %(actor_id)s AND actor_role = %(actor_role)s
  AND authn_schema_version = %(authn_schema_version)s LIMIT 1"""
_POSTGRES_INSERT_SNAPSHOT_SQL = """INSERT INTO glossary_snapshot_custody (custody_id,
snapshot_payload, snapshot_digest, snapshot_schema_version, retention_mode)
VALUES (%(custody_id)s, %(snapshot_payload)s, %(snapshot_digest)s,
%(snapshot_schema_version)s, 'retain') ON CONFLICT (snapshot_digest) DO NOTHING
RETURNING custody_id"""
_POSTGRES_SNAPSHOT_BY_DIGEST_SQL = "SELECT custody_id FROM glossary_snapshot_custody WHERE snapshot_digest = %(snapshot_digest)s"
_POSTGRES_INSERT_APPROVAL_SQL = """INSERT INTO glossary_approvals (approval_id, custody_id,
snapshot_digest, approval_schema_version, approval_status)
VALUES (%(approval_id)s, %(snapshot_custody_id)s, %(snapshot_digest)s, 1, 'approved')"""
_POSTGRES_INSERT_REVISION_SQL = """INSERT INTO document_glossary_revisions (revision_id,
document_custody_id, revision_sequence, parent_revision_id, approval_id,
snapshot_custody_id, snapshot_payload_sha256, glossary_content_signature,
snapshot_schema_version, serialization_schema_version, actor_id, actor_role,
authn_schema_version) VALUES (%(revision_id)s, %(document_custody_id)s,
%(revision_sequence)s, %(parent_revision_id)s, %(approval_id)s,
%(snapshot_custody_id)s, %(snapshot_digest)s, %(content_signature)s,
%(snapshot_schema_version)s, %(serialization_schema_version)s, %(actor_id)s,
%(actor_role)s, %(authn_schema_version)s)"""
_POSTGRES_INSERT_EVENT_SQL = """INSERT INTO document_glossary_revision_events (event_id,
revision_id, event_type, successor_revision_id, actor_id, actor_role,
authn_schema_version) VALUES (%(event_id)s, %(revision_id)s, %(event_type)s,
%(successor_revision_id)s, %(actor_id)s, %(actor_role)s, %(authn_schema_version)s)"""
