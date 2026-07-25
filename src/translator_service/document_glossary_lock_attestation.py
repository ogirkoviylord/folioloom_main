from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from translator_service.admin.auth import AdminSession
from translator_service.admin.rbac import AdminRole
from translator_service.file_storage import LocalObjectStorage
from translator_service.persistent_job_store import (
    document_glossary_lock_attestation_capability_denial_code,
)
from translator_service.persistent_jobs import (
    GLOSSARY_APPROVAL_SCHEMA_VERSION,
    GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
    _now,
    _to_db_time,
)
from translator_service.source_registry_service import (
    SourceRegistryActor,
    SourceRegistryDenied,
    select_registered_original_docx_source,
)

_ATTESTATION_SCHEMA_VERSION = 1
_AUTHN_SCHEMA_VERSION = "admin-session-v1"


@dataclass(frozen=True)
class DocumentGlossaryLockDenied:
    code: str


@dataclass(frozen=True)
class DocumentGlossaryLockAttestation:
    attestation_id: str
    document_custody_id: str
    revision_id: str
    outcome: str


@dataclass(frozen=True)
class DocumentGlossaryLockStatus:
    document_custody_id: str
    status: str


def document_glossary_lock_actor_from_session(
    session: AdminSession,
) -> SourceRegistryActor | DocumentGlossaryLockDenied:
    if not isinstance(session, AdminSession) or session.expires_at <= datetime.now(UTC):
        return DocumentGlossaryLockDenied("glossary_lock_attestation_session_invalid")
    if session.actor_id != "bootstrap-owner" or session.role is not AdminRole.OWNER:
        return DocumentGlossaryLockDenied(
            "glossary_lock_attestation_actor_unauthorized"
        )
    return SourceRegistryActor("bootstrap-owner", "owner", _AUTHN_SCHEMA_VERSION)


def attest_document_glossary_lock(
    *,
    store: object,
    storage: LocalObjectStorage,
    session: AdminSession,
    document_custody_id: str,
) -> DocumentGlossaryLockAttestation | DocumentGlossaryLockDenied:
    actor = document_glossary_lock_actor_from_session(session)
    if isinstance(actor, DocumentGlossaryLockDenied):
        return actor
    denial = _service_denial(store, storage, actor, document_custody_id)
    if denial is not None:
        return denial
    return store.attest_document_glossary_lock(
        document_custody_id=document_custody_id, actor=actor
    )


def read_document_glossary_lock_status(
    *,
    store: object,
    storage: LocalObjectStorage,
    session: AdminSession,
    document_custody_id: str,
) -> DocumentGlossaryLockStatus | DocumentGlossaryLockDenied:
    actor = document_glossary_lock_actor_from_session(session)
    if isinstance(actor, DocumentGlossaryLockDenied):
        return actor
    denial = _service_denial(store, storage, actor, document_custody_id)
    if denial is not None:
        return denial
    return store.read_document_glossary_lock_status(
        document_custody_id=document_custody_id, actor=actor
    )


def _service_denial(store, storage, actor, document_custody_id):
    capability = document_glossary_lock_attestation_capability_denial_code(store)
    if capability is not None:
        return DocumentGlossaryLockDenied(capability)
    selected = select_registered_original_docx_source(
        store=store,
        storage=storage,
        actor=actor,
        document_custody_id=document_custody_id,
    )
    if isinstance(selected, SourceRegistryDenied):
        return DocumentGlossaryLockDenied(f"glossary_lock_attestation_{selected.code}")
    return None


def _attest_sqlite_document_glossary_lock(store, document_custody_id, actor):
    connection = store._connection
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = _sqlite_current_row(connection, document_custody_id, actor)
        if row is None:
            connection.rollback()
            return DocumentGlossaryLockDenied(
                "glossary_lock_attestation_provenance_inconsistent"
            )
        existing = _sqlite_attestation_row(connection, row, actor)
        if existing is not None:
            connection.commit()
            return _attestation_from_row(existing, "idempotent")
        attestation_id = f"document-glossary-lock-attestation-{uuid4().hex}"
        connection.execute(
            """INSERT INTO document_glossary_lock_attestations (
            attestation_id, document_custody_id, revision_id, approval_id,
            snapshot_custody_id, snapshot_digest, snapshot_schema_version,
            serialization_schema_version, approval_schema_version,
            attestation_schema_version, actor_id, actor_role,
            authn_schema_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                attestation_id,
                row["document_custody_id"],
                row["revision_id"],
                row["approval_id"],
                row["snapshot_custody_id"],
                row["snapshot_digest"],
                row["snapshot_schema_version"],
                row["serialization_schema_version"],
                row["approval_schema_version"],
                _ATTESTATION_SCHEMA_VERSION,
                actor.actor_id,
                actor.role,
                actor.authn_schema_version,
                _to_db_time(_now()),
            ),
        )
        connection.commit()
        return DocumentGlossaryLockAttestation(
            attestation_id, document_custody_id, row["revision_id"], "created"
        )
    except Exception:
        connection.rollback()
        raise


def _read_sqlite_document_glossary_lock_status(store, document_custody_id, actor):
    connection = store._connection
    custody = connection.execute(
        """SELECT document_custody_id, document_kind, registry_owner_actor_id,
        registry_actor_role, registry_authn_schema_version
        FROM strict_docx_v3_document_custody WHERE document_custody_id = ?""",
        (document_custody_id,),
    ).fetchone()
    if not _owned_custody(custody, actor):
        return DocumentGlossaryLockDenied(
            "glossary_lock_attestation_provenance_inconsistent"
        )
    attestation = connection.execute(
        """SELECT * FROM document_glossary_lock_attestations
        WHERE document_custody_id = ? AND actor_id = ? AND actor_role = ?
          AND authn_schema_version = ?
        ORDER BY created_at DESC, attestation_id DESC LIMIT 1""",
        (document_custody_id, actor.actor_id, actor.role, actor.authn_schema_version),
    ).fetchone()
    current = _sqlite_current_row(connection, document_custody_id, actor)
    if attestation is None:
        if current is None:
            return DocumentGlossaryLockDenied(
                "glossary_lock_attestation_provenance_inconsistent"
            )
        return DocumentGlossaryLockStatus(document_custody_id, "absent")
    lifecycle = _sqlite_attestation_lifecycle(connection, attestation)
    if lifecycle is not None:
        return DocumentGlossaryLockStatus(document_custody_id, lifecycle)
    if current is None or not _tuple_matches(attestation, current, actor):
        return DocumentGlossaryLockDenied(
            "glossary_lock_attestation_provenance_inconsistent"
        )
    return DocumentGlossaryLockStatus(document_custody_id, "active")


def _sqlite_current_row(connection, document_custody_id, actor):
    row = connection.execute(
        """SELECT custody.document_custody_id, custody.document_kind,
        custody.registry_owner_actor_id, custody.registry_actor_role,
        custody.registry_authn_schema_version, revision.revision_id,
        revision.revision_sequence, revision.parent_revision_id, revision.approval_id,
        revision.snapshot_custody_id,
        revision.snapshot_payload_sha256 AS snapshot_digest,
        revision.snapshot_schema_version, revision.serialization_schema_version,
        revision.actor_id, revision.actor_role, revision.authn_schema_version,
        approval.custody_id AS approval_custody_id,
        approval.snapshot_digest AS approval_digest,
        approval.approval_schema_version, approval.approval_status,
        snapshot.snapshot_digest AS custody_digest,
        snapshot.snapshot_schema_version AS custody_schema
        FROM strict_docx_v3_document_custody custody
        JOIN document_glossary_revisions revision
          ON revision.document_custody_id = custody.document_custody_id
        JOIN glossary_approvals approval ON approval.approval_id = revision.approval_id
        JOIN glossary_snapshot_custody snapshot
          ON snapshot.custody_id = revision.snapshot_custody_id
        WHERE custody.document_custody_id = ?
          AND NOT EXISTS (SELECT 1 FROM document_glossary_revisions newer
                          WHERE newer.document_custody_id = revision.document_custody_id
                            AND newer.revision_sequence > revision.revision_sequence)
          AND NOT EXISTS (SELECT 1 FROM document_glossary_revision_events event
                          WHERE event.revision_id = revision.revision_id
                            AND event.event_type IN ('superseded', 'revoked'))""",
        (document_custody_id,),
    ).fetchone()
    if row is None or not _owned_custody(row, actor):
        return None
    if (row["actor_id"], row["actor_role"], row["authn_schema_version"]) != (
        actor.actor_id,
        actor.role,
        actor.authn_schema_version,
    ):
        return None
    if (
        row["approval_status"] != "approved"
        or row["approval_custody_id"] != row["snapshot_custody_id"]
        or row["approval_digest"] != row["snapshot_digest"]
        or row["custody_digest"] != row["snapshot_digest"]
        or row["snapshot_schema_version"] != GLOSSARY_SNAPSHOT_SCHEMA_VERSION
        or row["custody_schema"] != row["snapshot_schema_version"]
        or row["approval_schema_version"] != GLOSSARY_APPROVAL_SCHEMA_VERSION
    ):
        return None
    return row


def _sqlite_attestation_row(connection, row, actor):
    return connection.execute(
        """SELECT * FROM document_glossary_lock_attestations WHERE
        document_custody_id = ? AND revision_id = ? AND approval_id = ?
        AND snapshot_custody_id = ? AND snapshot_digest = ?
        AND snapshot_schema_version = ? AND serialization_schema_version = ?
        AND approval_schema_version = ? AND attestation_schema_version = ?
        AND actor_id = ? AND actor_role = ? AND authn_schema_version = ?""",
        _tuple_values(row, actor),
    ).fetchone()


def _sqlite_attestation_lifecycle(connection, attestation):
    approval = connection.execute(
        "SELECT approval_status FROM glossary_approvals WHERE approval_id = ?",
        (attestation["approval_id"],),
    ).fetchone()
    events = connection.execute(
        "SELECT event_type FROM document_glossary_revision_events "
        "WHERE revision_id = ?",
        (attestation["revision_id"],),
    ).fetchall()
    event_types = {event["event_type"] for event in events}
    if (
        approval is None
        or approval["approval_status"] == "revoked"
        or "revoked" in event_types
    ):
        return "revoked"
    if "superseded" in event_types:
        return "superseded"
    return None


def _owned_custody(row, actor):
    return row is not None and (
        row["document_kind"],
        row["registry_owner_actor_id"],
        row["registry_actor_role"],
        row["registry_authn_schema_version"],
    ) == ("docx", actor.actor_id, actor.role, actor.authn_schema_version)


def _tuple_values(row, actor):
    return (
        row["document_custody_id"],
        row["revision_id"],
        row["approval_id"],
        row["snapshot_custody_id"],
        row["snapshot_digest"],
        row["snapshot_schema_version"],
        row["serialization_schema_version"],
        row["approval_schema_version"],
        _ATTESTATION_SCHEMA_VERSION,
        actor.actor_id,
        actor.role,
        actor.authn_schema_version,
    )


def _tuple_matches(attestation, row, actor):
    return tuple(
        attestation[column]
        for column in (
            "document_custody_id",
            "revision_id",
            "approval_id",
            "snapshot_custody_id",
            "snapshot_digest",
            "snapshot_schema_version",
            "serialization_schema_version",
            "approval_schema_version",
            "attestation_schema_version",
            "actor_id",
            "actor_role",
            "authn_schema_version",
        )
    ) == _tuple_values(row, actor)


def _attestation_from_row(row, outcome):
    return DocumentGlossaryLockAttestation(
        row["attestation_id"], row["document_custody_id"], row["revision_id"], outcome
    )


def _attest_postgres_document_glossary_lock(store, document_custody_id, actor):
    connection = store.connection
    with connection.transaction():
        row = _postgres_current_row(connection, document_custody_id, actor)
        if row is None:
            return DocumentGlossaryLockDenied(
                "glossary_lock_attestation_provenance_inconsistent"
            )
        params = _postgres_tuple_params(row, actor)
        existing = connection.execute(
            _POSTGRES_SELECT_ATTESTATION_SQL, params
        ).fetchone()
        if existing is not None:
            return _attestation_from_row(existing, "idempotent")
        params["attestation_id"] = f"document-glossary-lock-attestation-{uuid4().hex}"
        inserted = connection.execute(
            _POSTGRES_INSERT_ATTESTATION_SQL, params
        ).fetchone()
        if inserted is not None:
            return _attestation_from_row(inserted, "created")
        existing = connection.execute(
            _POSTGRES_SELECT_ATTESTATION_SQL, params
        ).fetchone()
        if existing is None:
            return DocumentGlossaryLockDenied("glossary_lock_attestation_conflict")
        return _attestation_from_row(existing, "idempotent")


def _read_postgres_document_glossary_lock_status(store, document_custody_id, actor):
    connection = store.connection
    with connection.transaction():
        row = _postgres_current_row(
            connection, document_custody_id, actor, for_update=False
        )
        attestation = connection.execute(
            """SELECT * FROM document_glossary_lock_attestations
            WHERE document_custody_id = %(document_custody_id)s
              AND actor_id = %(actor_id)s AND actor_role = %(actor_role)s
              AND authn_schema_version = %(authn_schema_version)s
            ORDER BY created_at DESC, attestation_id DESC LIMIT 1""",
            {
                "document_custody_id": document_custody_id,
                "actor_id": actor.actor_id,
                "actor_role": actor.role,
                "authn_schema_version": actor.authn_schema_version,
            },
        ).fetchone()
        lifecycle = (
            _postgres_attestation_lifecycle(connection, attestation)
            if attestation is not None
            else None
        )
    if attestation is None:
        if row is None:
            return DocumentGlossaryLockDenied(
                "glossary_lock_attestation_provenance_inconsistent"
            )
        return DocumentGlossaryLockStatus(document_custody_id, "absent")
    if lifecycle is not None:
        return DocumentGlossaryLockStatus(document_custody_id, lifecycle)
    if row is None or not _tuple_matches(attestation, row, actor):
        return DocumentGlossaryLockDenied(
            "glossary_lock_attestation_provenance_inconsistent"
        )
    return DocumentGlossaryLockStatus(document_custody_id, "active")


def _postgres_attestation_lifecycle(connection, attestation):
    approval = connection.execute(
        "SELECT approval_status FROM glossary_approvals "
        "WHERE approval_id = %(approval_id)s",
        {"approval_id": attestation["approval_id"]},
    ).fetchone()
    events = connection.execute(
        "SELECT event_type FROM document_glossary_revision_events "
        "WHERE revision_id = %(revision_id)s",
        {"revision_id": attestation["revision_id"]},
    ).fetchall()
    event_types = {event["event_type"] for event in events}
    if (
        approval is None
        or approval["approval_status"] == "revoked"
        or "revoked" in event_types
    ):
        return "revoked"
    if "superseded" in event_types:
        return "superseded"
    return None


_POSTGRES_CURRENT_ROW_SQL = """
SELECT custody.document_custody_id, custody.document_kind,
       custody.registry_owner_actor_id, custody.registry_actor_role,
       custody.registry_authn_schema_version, revision.revision_id,
       revision.revision_sequence, revision.parent_revision_id,
       revision.approval_id, revision.snapshot_custody_id,
       revision.snapshot_payload_sha256 AS snapshot_digest,
       revision.snapshot_schema_version, revision.serialization_schema_version,
       revision.actor_id, revision.actor_role, revision.authn_schema_version,
       approval.custody_id AS approval_custody_id,
       approval.snapshot_digest AS approval_digest,
       approval.approval_schema_version, approval.approval_status,
       snapshot.snapshot_digest AS custody_digest,
       snapshot.snapshot_schema_version AS custody_schema
FROM strict_docx_v3_document_custody custody
JOIN document_glossary_revisions revision
  ON revision.document_custody_id = custody.document_custody_id
JOIN glossary_approvals approval ON approval.approval_id = revision.approval_id
JOIN glossary_snapshot_custody snapshot
  ON snapshot.custody_id = revision.snapshot_custody_id
WHERE custody.document_custody_id = %(document_custody_id)s
  AND NOT EXISTS (
      SELECT 1 FROM document_glossary_revisions newer
      WHERE newer.document_custody_id = revision.document_custody_id
        AND newer.revision_sequence > revision.revision_sequence
  )
  AND NOT EXISTS (
      SELECT 1 FROM document_glossary_revision_events event
      WHERE event.revision_id = revision.revision_id
        AND event.event_type IN ('superseded', 'revoked')
  )
FOR UPDATE OF custody, revision, approval, snapshot
"""
_POSTGRES_CURRENT_ROW_FOR_READ_SQL = _POSTGRES_CURRENT_ROW_SQL.removesuffix(
    "FOR UPDATE OF custody, revision, approval, snapshot\n"
)
_POSTGRES_SELECT_ATTESTATION_SQL = """SELECT * FROM document_glossary_lock_attestations
WHERE document_custody_id = %(document_custody_id)s
  AND revision_id = %(revision_id)s
  AND approval_id = %(approval_id)s
  AND snapshot_custody_id = %(snapshot_custody_id)s
  AND snapshot_digest = %(snapshot_digest)s
  AND snapshot_schema_version = %(snapshot_schema_version)s
  AND serialization_schema_version = %(serialization_schema_version)s
  AND approval_schema_version = %(approval_schema_version)s
  AND attestation_schema_version = %(attestation_schema_version)s
  AND actor_id = %(actor_id)s
  AND actor_role = %(actor_role)s
  AND authn_schema_version = %(authn_schema_version)s"""
_POSTGRES_INSERT_ATTESTATION_SQL = """INSERT INTO document_glossary_lock_attestations (
    attestation_id, document_custody_id, revision_id, approval_id,
    snapshot_custody_id, snapshot_digest, snapshot_schema_version,
    serialization_schema_version, approval_schema_version,
    attestation_schema_version, actor_id, actor_role, authn_schema_version
) VALUES (
    %(attestation_id)s, %(document_custody_id)s, %(revision_id)s, %(approval_id)s,
    %(snapshot_custody_id)s, %(snapshot_digest)s, %(snapshot_schema_version)s,
    %(serialization_schema_version)s, %(approval_schema_version)s,
    %(attestation_schema_version)s, %(actor_id)s, %(actor_role)s,
    %(authn_schema_version)s
) ON CONFLICT (
    document_custody_id, revision_id, approval_id, snapshot_custody_id,
    snapshot_digest, snapshot_schema_version, serialization_schema_version,
    approval_schema_version, attestation_schema_version, actor_id, actor_role,
    authn_schema_version
) DO NOTHING RETURNING *"""


def _postgres_current_row(connection, document_custody_id, actor, *, for_update=True):
    row = connection.execute(
        (
            _POSTGRES_CURRENT_ROW_SQL
            if for_update
            else _POSTGRES_CURRENT_ROW_FOR_READ_SQL
        ),
        {"document_custody_id": document_custody_id},
    ).fetchone()
    if row is None or not _owned_custody(row, actor):
        return None
    if (row["actor_id"], row["actor_role"], row["authn_schema_version"]) != (
        actor.actor_id,
        actor.role,
        actor.authn_schema_version,
    ):
        return None
    if (
        row["approval_status"] != "approved"
        or row["approval_custody_id"] != row["snapshot_custody_id"]
        or row["approval_digest"] != row["snapshot_digest"]
        or row["custody_digest"] != row["snapshot_digest"]
        or row["snapshot_schema_version"] != GLOSSARY_SNAPSHOT_SCHEMA_VERSION
        or row["custody_schema"] != row["snapshot_schema_version"]
        or row["approval_schema_version"] != GLOSSARY_APPROVAL_SCHEMA_VERSION
    ):
        return None
    return row


def _postgres_tuple_params(row, actor):
    return dict(
        zip(
            (
                "document_custody_id",
                "revision_id",
                "approval_id",
                "snapshot_custody_id",
                "snapshot_digest",
                "snapshot_schema_version",
                "serialization_schema_version",
                "approval_schema_version",
                "attestation_schema_version",
                "actor_id",
                "actor_role",
                "authn_schema_version",
            ),
            _tuple_values(row, actor),
            strict=True,
        )
    )
