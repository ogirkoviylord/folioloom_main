import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from translator_service import document_glossary_authoring_bridge as bridge
from translator_service.admin.auth import AdminSession
from translator_service.admin.rbac import AdminRole
from translator_service.document_glossary_authoring_bridge import (
    DocumentGlossaryAuthoringBridgeDenied,
    author_document_glossary_revision,
    read_current_document_glossary_editable_projection,
    read_current_document_glossary_revision,
)
from translator_service.document_glossary_lock_attestation import (
    DocumentGlossaryLockAttestation,
    DocumentGlossaryLockStatus,
    attest_document_glossary_lock,
    read_document_glossary_lock_status,
)
from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.glossary_contracts import (
    GlossaryEntry,
    GlossaryEntryCategory,
    GlossaryEntryStatus,
    GlossaryEvidenceRef,
    GlossaryEvidenceSurface,
    GlossaryEvidenceType,
    GlossaryLayer,
    GlossarySnapshot,
    glossary_snapshot_signature,
)
from translator_service.glossary_snapshot_serialization import (
    GLOSSARY_SNAPSHOT_SERIALIZATION_VERSION,
    serialize_glossary_snapshot_v1,
    snapshot_payload_sha256,
)
from translator_service.persistent_jobs import SQLiteTranslationJobStore
from translator_service.postgres_scheduler import PostgresSchedulerStore
from translator_service.source_registry_service import (
    SourceRegistryActor,
    register_verified_original_docx_source,
)
from translator_service.verified_original_docx import verify_original_docx_source


class DocumentGlossaryAuthoringBridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = SQLiteTranslationJobStore(root / "jobs.sqlite3")
        self.addCleanup(self.store.close)
        self.storage = LocalObjectStorage(root / "objects")
        self.session = AdminSession(
            "bootstrap-owner",
            AdminRole.OWNER,
            datetime.now(UTC) + timedelta(minutes=5),
            "csrf",
        )
        source = self.storage.put_bytes(
            kind=StoredFileKind.ORIGINAL,
            file_name="book.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            content=b"verified document bytes",
        )
        custody = register_verified_original_docx_source(
            store=self.store,
            actor=SourceRegistryActor("bootstrap-owner", "owner", "admin-session-v1"),
            source=verify_original_docx_source(self.storage, source.object_key),
        )
        self.custody_id = custody.document_custody_id

    def test_owner_authors_safe_first_revision_then_attests_it(self):
        created = author_document_glossary_revision(
            store=self.store,
            storage=self.storage,
            session=self.session,
            document_custody_id=self.custody_id,
            snapshot=_snapshot(),
            expected_parent_revision_id=None,
        )

        self.assertNotIsInstance(created, DocumentGlossaryAuthoringBridgeDenied)
        self.assertEqual(created.document_custody_id, self.custody_id)
        self.assertEqual(created.revision_sequence, 1)
        self.assertFalse(hasattr(created, "source_object_key"))
        self.assertFalse(hasattr(created, "snapshot_payload"))
        self.assertEqual(
            read_document_glossary_lock_status(
                store=self.store,
                storage=self.storage,
                session=self.session,
                document_custody_id=self.custody_id,
            ),
            DocumentGlossaryLockStatus(self.custody_id, "absent"),
        )
        attested = attest_document_glossary_lock(
            store=self.store,
            storage=self.storage,
            session=self.session,
            document_custody_id=self.custody_id,
        )
        self.assertIsInstance(attested, DocumentGlossaryLockAttestation)
        current = read_current_document_glossary_revision(
            store=self.store,
            storage=self.storage,
            session=self.session,
            document_custody_id=self.custody_id,
        )
        self.assertEqual(current.revision_id, created.revision_id)
        self.assertEqual(current.outcome, "current")

    def test_stale_parent_fails_without_successor_or_event(self):
        first = author_document_glossary_revision(
            store=self.store,
            storage=self.storage,
            session=self.session,
            document_custody_id=self.custody_id,
            snapshot=_snapshot(),
            expected_parent_revision_id=None,
        )
        result = author_document_glossary_revision(
            store=self.store,
            storage=self.storage,
            session=self.session,
            document_custody_id=self.custody_id,
            snapshot=_snapshot(snapshot_id="snapshot-2", source_canonical="Second"),
            expected_parent_revision_id="stale-revision",
        )

        self.assertNotIsInstance(first, DocumentGlossaryAuthoringBridgeDenied)
        self.assertEqual(
            result,
            DocumentGlossaryAuthoringBridgeDenied("glossary_authoring_parent_not_current"),
        )
        self.assertEqual(_count(self.store, "document_glossary_revisions"), 1)
        self.assertEqual(_count(self.store, "document_glossary_revision_events"), 1)

    def test_current_editable_projection_exposes_only_canonical_fields(self):
        author_document_glossary_revision(
            store=self.store, storage=self.storage, session=self.session,
            document_custody_id=self.custody_id, snapshot=_snapshot(),
            expected_parent_revision_id=None,
        )

        projection = read_current_document_glossary_editable_projection(
            store=self.store, storage=self.storage, session=self.session,
            document_custody_id=self.custody_id,
        )

        if isinstance(projection, DocumentGlossaryAuthoringBridgeDenied):
            self.fail(projection.code)
        self.assertEqual(projection.source_language, "en")
        self.assertEqual(projection.target_language, "ru")
        self.assertEqual(projection.rows[0].source_term, "Term")
        self.assertEqual(projection.rows[0].target_term, "")
        self.assertEqual(projection.rows[0].entry_type, "term")
        for forbidden in ("snapshot_payload", "snapshot_digest", "approval_id", "custody_id"):
            self.assertFalse(hasattr(projection, forbidden))

    def test_active_lock_rejects_successor_without_durable_write(self):
        first = author_document_glossary_revision(
            store=self.store, storage=self.storage, session=self.session,
            document_custody_id=self.custody_id, snapshot=_snapshot(),
            expected_parent_revision_id=None,
        )
        assert not isinstance(first, DocumentGlossaryAuthoringBridgeDenied)
        attested = attest_document_glossary_lock(
            store=self.store, storage=self.storage, session=self.session,
            document_custody_id=self.custody_id,
        )
        self.assertIsInstance(attested, DocumentGlossaryLockAttestation)
        before = {
            table: _count(self.store, table)
            for table in (
                "glossary_snapshot_custody", "glossary_approvals",
                "document_glossary_revisions", "document_glossary_revision_events",
            )
        }

        result = author_document_glossary_revision(
            store=self.store, storage=self.storage, session=self.session,
            document_custody_id=self.custody_id,
            snapshot=_snapshot(
                snapshot_id="snapshot-locked", source_canonical="Locked"
            ),
            expected_parent_revision_id=first.revision_id,
        )

        self.assertEqual(
            result, DocumentGlossaryAuthoringBridgeDenied("glossary_authoring_locked")
        )
        self.assertEqual(
            {table: _count(self.store, table) for table in before}, before
        )

    def test_foreign_custody_is_denied_without_forbidden_writes(self):
        source = self.storage.put_bytes(
            kind=StoredFileKind.ORIGINAL,
            file_name="foreign.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            content=b"foreign verified document bytes",
        )
        foreign = register_verified_original_docx_source(
            store=self.store,
            actor=SourceRegistryActor("foreign-owner", "owner", "admin-session-v1"),
            source=verify_original_docx_source(self.storage, source.object_key),
        )

        result = self._assert_forbidden_tables_unchanged(
            lambda: author_document_glossary_revision(
                store=self.store,
                storage=self.storage,
                session=self.session,
                document_custody_id=foreign.document_custody_id,
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )
        )

        self.assertEqual(
            result,
            DocumentGlossaryAuthoringBridgeDenied(
                "glossary_authoring_source_registry_ownership_denied"
            ),
        )
        self.assertEqual(_count(self.store, "document_glossary_revisions"), 0)

    def test_unknown_custody_is_denied_without_forbidden_writes(self):
        result = self._assert_forbidden_tables_unchanged(
            lambda: author_document_glossary_revision(
                store=self.store,
                storage=self.storage,
                session=self.session,
                document_custody_id="document-custody-tampered",
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )
        )

        self.assertEqual(
            result,
            DocumentGlossaryAuthoringBridgeDenied(
                "glossary_authoring_source_registry_custody_not_found"
            ),
        )

    def test_duplicate_snapshot_is_denied_without_new_durable_rows(self):
        created = author_document_glossary_revision(
            store=self.store,
            storage=self.storage,
            session=self.session,
            document_custody_id=self.custody_id,
            snapshot=_snapshot(),
            expected_parent_revision_id=None,
        )
        before = {
            table: _count(self.store, table)
            for table in (
                "glossary_snapshot_custody",
                "glossary_approvals",
                "document_glossary_revisions",
                "document_glossary_revision_events",
            )
        }

        result = author_document_glossary_revision(
            store=self.store,
            storage=self.storage,
            session=self.session,
            document_custody_id=self.custody_id,
            snapshot=_snapshot(),
            expected_parent_revision_id=created.revision_id,
        )

        self.assertEqual(
            result,
            DocumentGlossaryAuthoringBridgeDenied("glossary_authoring_duplicate_snapshot"),
        )
        self.assertEqual(
            {table: _count(self.store, table) for table in before}, before
        )

    def test_non_owner_session_is_denied_before_writes(self):
        session = AdminSession(
            "bootstrap-owner",
            AdminRole.OPERATOR,
            datetime.now(UTC) + timedelta(minutes=5),
            "csrf",
        )

        result = self._assert_forbidden_tables_unchanged(
            lambda: author_document_glossary_revision(
                store=self.store,
                storage=self.storage,
                session=session,
                document_custody_id=self.custody_id,
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )
        )

        self.assertEqual(
            result,
            DocumentGlossaryAuthoringBridgeDenied("glossary_authoring_actor_unauthorized"),
        )

    def test_expired_session_is_denied_before_writes(self):
        session = AdminSession(
            "bootstrap-owner",
            AdminRole.OWNER,
            datetime.now(UTC) - timedelta(seconds=1),
            "csrf",
        )

        result = self._assert_forbidden_tables_unchanged(
            lambda: author_document_glossary_revision(
                store=self.store,
                storage=self.storage,
                session=session,
                document_custody_id=self.custody_id,
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )
        )

        self.assertEqual(
            result,
            DocumentGlossaryAuthoringBridgeDenied("glossary_authoring_session_invalid"),
        )

    def _forbidden_table_counts(self):
        tables = (
            "translation_jobs",
            "work_units",
            "strict_docx_v3_authorizations",
            "strict_docx_v3_job_authorizations",
            "strict_job_glossary_bindings",
        )
        return {table: _count(self.store, table) for table in tables}

    def _assert_forbidden_tables_unchanged(self, operation):
        before = self._forbidden_table_counts()
        result = operation()
        self.assertEqual(self._forbidden_table_counts(), before)
        return result


class DocumentGlossaryAuthoringBridgePostgresTest(unittest.TestCase):
    def setUp(self):
        self.actor = SourceRegistryActor(
            "bootstrap-owner", "owner", "admin-session-v1"
        )
        self.session = AdminSession(
            "bootstrap-owner",
            AdminRole.OWNER,
            datetime.now(UTC) + timedelta(minutes=5),
            "csrf",
        )

    def test_author_postgres_assembles_durable_inserts(self):
        connection = _RecordingPostgresConnection(
            [None, None, {"custody_id": "custody-1"}]
        )

        result = bridge._author_postgres(
            connection,
            "document-custody-1",
            self.actor,
            b"snapshot payload",
            "digest-1",
            "signature-1",
            None,
        )

        self.assertEqual(result.document_custody_id, "document-custody-1")
        self.assertEqual(result.snapshot_custody_id, "custody-1")
        self.assertEqual(result.revision_sequence, 1)
        self.assertIn(bridge._POSTGRES_INSERT_SNAPSHOT_SQL, connection.statements)
        self.assertIn(bridge._POSTGRES_INSERT_APPROVAL_SQL, connection.statements)
        self.assertIn(bridge._POSTGRES_INSERT_REVISION_SQL, connection.statements)
        self.assertIn(bridge._POSTGRES_INSERT_EVENT_SQL, connection.statements)

    def test_author_postgres_rejects_locked_current_revision_before_writes(self):
        active = _postgres_current_row()
        active["snapshot_payload_sha256"] = active["snapshot_digest"]
        connection = _RecordingPostgresConnection([active, {"locked": 1}])

        result = bridge._author_postgres(
            connection,
            "document-custody-1",
            self.actor,
            b"new snapshot payload",
            "new-digest",
            "new-signature",
            active["revision_id"],
        )

        self.assertEqual(
            result, DocumentGlossaryAuthoringBridgeDenied("glossary_authoring_locked")
        )
        self.assertIn(bridge._POSTGRES_ACTIVE_LOCK_SQL, connection.statements)
        self.assertNotIn(bridge._POSTGRES_INSERT_SNAPSHOT_SQL, connection.statements)
        self.assertNotIn(bridge._POSTGRES_INSERT_REVISION_SQL, connection.statements)
        self.assertNotIn(bridge._POSTGRES_INSERT_EVENT_SQL, connection.statements)

    def test_read_current_postgres_returns_metadata_for_consistent_tuple(self):
        current, lineage, events = _postgres_consistent_lineage()
        connection = _ProvenancePostgresConnection(current, lineage, events)
        store = object.__new__(PostgresSchedulerStore)
        store.connection = connection
        store.document_glossary_authoring_migration_ready = True

        with patch.object(bridge, "_service_denial", return_value=None):
            result = read_current_document_glossary_revision(
                store=store,
                storage=object(),
                session=self.session,
                document_custody_id="document-custody-1",
            )

        self.assertEqual(result.outcome, "current")
        self.assertEqual(result.revision_id, "revision-1")
        self.assertIn(
            "JOIN glossary_snapshot_custody snapshot", connection.statements[0]
        )
        self.assertNotIn("FOR UPDATE", connection.statements[0])
        self.assertTrue(all(isinstance(params, dict) for params in connection.params))

    def test_read_current_postgres_returns_successor_metadata_for_consistent_lineage(
        self,
    ):
        current, lineage, events = _postgres_consistent_lineage(successor=True)
        connection = _ProvenancePostgresConnection(current, lineage, events)
        store = object.__new__(PostgresSchedulerStore)
        store.connection = connection
        store.document_glossary_authoring_migration_ready = True

        with patch.object(bridge, "_service_denial", return_value=None):
            result = read_current_document_glossary_revision(
                store=store,
                storage=object(),
                session=self.session,
                document_custody_id="document-custody-1",
            )

        self.assertEqual(
            result,
            bridge.DocumentGlossaryRevisionMetadata(
                "document-custody-1",
                "revision-2",
                2,
                "revision-1",
                "approval-2",
                "custody-2",
                "current",
            ),
        )
        self.assertEqual(
            connection.active_rows,
            [_postgres_active_row_contract(current, connection.statements[0])],
        )
        self.assertIn("revision.revision_sequence", connection.statements[0])
        self.assertIn("revision.parent_revision_id", connection.statements[0])
        self.assertNotIn("snapshot_payload", connection.active_rows[0])
        self.assertNotIn("glossary_content_signature", connection.active_rows[0])
        self.assertEqual(
            [
                params["revision_id"]
                for statement, params in zip(
                    connection.statements, connection.params, strict=True
                )
                if "WHERE revision.revision_id" in statement
            ],
            ["revision-2", "revision-1"],
        )
        self.assertTrue(
            all(
                statement.lstrip().startswith("SELECT")
                for statement in connection.statements
            )
        )
        self.assertTrue(
            all(
                "FOR UPDATE" not in statement.upper()
                for statement in connection.statements
            )
        )

    def test_read_current_postgres_fails_closed_for_tampered_tuple(self):
        for field, value in (
            ("approval_digest", "wrong-digest"),
            ("custody_digest", "wrong-digest"),
            ("approval_schema_version", 999),
            ("snapshot_schema_version", 999),
            ("serialization_schema_version", 999),
        ):
            with self.subTest(field=field):
                row = _postgres_current_row()
                row[field] = value
                connection = _RecordingPostgresConnection([row])
                store = object.__new__(PostgresSchedulerStore)
                store.connection = connection
                store.document_glossary_authoring_migration_ready = True

                with patch.object(bridge, "_service_denial", return_value=None):
                    result = read_current_document_glossary_revision(
                        store=store,
                        storage=object(),
                        session=self.session,
                        document_custody_id="document-custody-1",
                    )

                self.assertEqual(
                    result,
                    DocumentGlossaryAuthoringBridgeDenied(
                        "glossary_authoring_provenance_inconsistent"
                    ),
                )

    def test_read_current_postgres_fails_closed_for_corrupt_lineage_provenance(self):
        for mutation in (
            _mutate_payload_with_matching_digest_columns,
            _mutate_invalid_payload,
            _mutate_content_signature,
            _mutate_predecessor_payload_with_matching_digest_columns,
            _mutate_predecessor_approval_digest,
            _remove_created_event,
            _append_extra_event,
            _malform_created_event,
            _wrong_superseded_successor,
            _wrong_superseded_actor,
            _missing_parent,
            _cross_custody_parent,
            _non_contiguous_parent,
            _mutate_parent_actor_binding,
            _cyclic_parent,
        ):
            with self.subTest(mutation=mutation.__name__):
                current, lineage, events = _postgres_consistent_lineage(successor=True)
                mutation(current, lineage, events)
                connection = _ProvenancePostgresConnection(current, lineage, events)
                store = object.__new__(PostgresSchedulerStore)
                store.connection = connection
                store.document_glossary_authoring_migration_ready = True

                with patch.object(bridge, "_service_denial", return_value=None):
                    result = read_current_document_glossary_revision(
                        store=store,
                        storage=object(),
                        session=self.session,
                        document_custody_id="document-custody-1",
                    )

                self.assertEqual(
                    result,
                    DocumentGlossaryAuthoringBridgeDenied(
                        "glossary_authoring_provenance_inconsistent"
                    ),
                )
                self.assertTrue(
                    all(
                        statement.lstrip().startswith("SELECT")
                        for statement in connection.statements
                    )
                )
                self.assertTrue(
                    all(
                        "FOR UPDATE" not in statement.upper()
                        for statement in connection.statements
                    )
                )


def _snapshot(snapshot_id="snapshot-1", source_canonical="Term"):
    evidence = GlossaryEvidenceRef(
        evidence_id="evidence-1",
        evidence_type=GlossaryEvidenceType.SOURCE_ANCHOR,
        unit_sequence=1,
        source_block_id="block-1",
        source_scope="document",
        surface=GlossaryEvidenceSurface.BODY,
    )
    entry = GlossaryEntry(
        entry_id="entry-1",
        category=GlossaryEntryCategory.TERM,
        layer=GlossaryLayer.SOFT,
        status=GlossaryEntryStatus.AUTO_DETECTED,
        source_canonical=source_canonical,
        evidence_refs=(evidence.evidence_id,),
        confidence=0.8,
    )
    return GlossarySnapshot(
        snapshot_id=snapshot_id,
        source_language="en",
        target_language="ru",
        entries=(entry,),
        evidence=(evidence,),
    )


def _count(store, table):
    return store._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _postgres_current_row():
    payload = serialize_glossary_snapshot_v1(_snapshot())
    digest = snapshot_payload_sha256(payload)
    return {
        "document_custody_id": "document-custody-1",
        "document_kind": "docx",
        "registry_owner_actor_id": "bootstrap-owner",
        "registry_actor_role": "owner",
        "registry_authn_schema_version": "admin-session-v1",
        "revision_id": "revision-1",
        "revision_sequence": 1,
        "parent_revision_id": None,
        "approval_id": "approval-1",
        "snapshot_custody_id": "custody-1",
        "snapshot_digest": digest,
        "snapshot_schema_version": 1,
        "serialization_schema_version": GLOSSARY_SNAPSHOT_SERIALIZATION_VERSION,
        "actor_id": "bootstrap-owner",
        "actor_role": "owner",
        "authn_schema_version": "admin-session-v1",
        "approval_custody_id": "custody-1",
        "approval_digest": digest,
        "approval_schema_version": 1,
        "approval_status": "approved",
        "custody_digest": digest,
        "custody_schema": 1,
    }


def _postgres_consistent_lineage(*, successor=False):
    current = _postgres_current_row()
    current_snapshot = _snapshot(snapshot_id="snapshot-current")
    payload = serialize_glossary_snapshot_v1(current_snapshot)
    digest = snapshot_payload_sha256(payload)
    current.update(
        revision_id="revision-2" if successor else "revision-1",
        revision_sequence=2 if successor else 1,
        parent_revision_id="revision-1" if successor else None,
        approval_id="approval-2" if successor else "approval-1",
        snapshot_custody_id="custody-2" if successor else "custody-1",
        snapshot_digest=digest,
        approval_custody_id="custody-2" if successor else "custody-1",
        approval_digest=digest,
        custody_digest=digest,
    )
    lineage = {
        **current,
        "snapshot_payload": payload,
        "glossary_content_signature": glossary_snapshot_signature(current_snapshot),
    }
    current = lineage
    events = [_created_event(lineage)]
    if not successor:
        return current, lineage, events

    parent_snapshot = _snapshot(
        snapshot_id="snapshot-parent", source_canonical="Parent"
    )
    parent_payload = serialize_glossary_snapshot_v1(parent_snapshot)
    parent_digest = snapshot_payload_sha256(parent_payload)
    parent = {
        **lineage,
        "revision_id": "revision-1",
        "revision_sequence": 1,
        "parent_revision_id": None,
        "approval_id": "approval-1",
        "snapshot_custody_id": "custody-1",
        "snapshot_digest": parent_digest,
        "approval_custody_id": "custody-1",
        "approval_digest": parent_digest,
        "custody_digest": parent_digest,
        "snapshot_payload": parent_payload,
        "glossary_content_signature": glossary_snapshot_signature(parent_snapshot),
    }
    lineage["parent_row"] = parent
    lineage["parent_events"] = [_created_event(parent), _superseded_event(lineage)]
    return current, lineage, events


def _postgres_active_row_contract(row, statement):
    """Model exactly the columns selected by the lock-attestation active-row query."""
    selection = statement.partition("FROM strict_docx_v3_document_custody custody")[0]
    columns = {
        "document_custody_id": "custody.document_custody_id",
        "document_kind": "custody.document_kind",
        "registry_owner_actor_id": "custody.registry_owner_actor_id",
        "registry_actor_role": "custody.registry_actor_role",
        "registry_authn_schema_version": "custody.registry_authn_schema_version",
        "revision_id": "revision.revision_id",
        "revision_sequence": "revision.revision_sequence",
        "parent_revision_id": "revision.parent_revision_id",
        "approval_id": "revision.approval_id",
        "snapshot_custody_id": "revision.snapshot_custody_id",
        "snapshot_digest": "revision.snapshot_payload_sha256 AS snapshot_digest",
        "snapshot_schema_version": "revision.snapshot_schema_version",
        "serialization_schema_version": "revision.serialization_schema_version",
        "actor_id": "revision.actor_id",
        "actor_role": "revision.actor_role",
        "authn_schema_version": "revision.authn_schema_version",
        "approval_custody_id": "approval.custody_id AS approval_custody_id",
        "approval_digest": "approval.snapshot_digest AS approval_digest",
        "approval_schema_version": "approval.approval_schema_version",
        "approval_status": "approval.approval_status",
        "custody_digest": "snapshot.snapshot_digest AS custody_digest",
        "custody_schema": "snapshot.snapshot_schema_version AS custody_schema",
    }
    return {
        field: row[field] for field, column in columns.items() if column in selection
    }


def _created_event(revision):
    return {
        "event_type": "created",
        "successor_revision_id": None,
        "actor_id": revision["actor_id"],
        "actor_role": revision["actor_role"],
        "authn_schema_version": revision["authn_schema_version"],
    }


def _superseded_event(successor):
    return {
        "event_type": "superseded",
        "successor_revision_id": successor["revision_id"],
        "actor_id": successor["actor_id"],
        "actor_role": successor["actor_role"],
        "authn_schema_version": successor["authn_schema_version"],
    }


def _mutate_payload_with_matching_digest_columns(current, lineage, events):
    lineage["snapshot_payload"] = b"tampered payload"


def _mutate_invalid_payload(current, lineage, events):
    lineage["snapshot_payload"] = b"not-a-snapshot"


def _mutate_content_signature(current, lineage, events):
    lineage["glossary_content_signature"] = "wrong-signature"


def _mutate_predecessor_payload_with_matching_digest_columns(current, lineage, events):
    lineage["parent_row"]["snapshot_payload"] = b"tampered parent payload"


def _mutate_predecessor_approval_digest(current, lineage, events):
    lineage["parent_row"]["approval_digest"] = "wrong-parent-digest"


def _remove_created_event(current, lineage, events):
    events.pop(0)


def _append_extra_event(current, lineage, events):
    events.append(_created_event(lineage))


def _malform_created_event(current, lineage, events):
    events[0]["successor_revision_id"] = "revision-tampered"


def _wrong_superseded_successor(current, lineage, events):
    lineage["parent_events"][1]["successor_revision_id"] = "revision-tampered"


def _wrong_superseded_actor(current, lineage, events):
    lineage["parent_events"][1]["actor_id"] = "foreign-owner"


def _missing_parent(current, lineage, events):
    lineage["parent_row"] = None


def _cross_custody_parent(current, lineage, events):
    lineage["parent_row"]["document_custody_id"] = "document-custody-foreign"


def _non_contiguous_parent(current, lineage, events):
    lineage["parent_row"]["revision_sequence"] = 7


def _mutate_parent_actor_binding(current, lineage, events):
    lineage["parent_row"]["actor_id"] = "foreign-owner"


def _cyclic_parent(current, lineage, events):
    lineage["parent_row"]["parent_revision_id"] = lineage["revision_id"]


class _RecordingPostgresConnection:
    def __init__(self, rows):
        self.rows = list(rows)
        self.statements = []
        self.params = []

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, statement, params):
        self.statements.append(statement)
        self.params.append(params)
        row = self.rows.pop(0) if self.rows else None
        return _RecordingResult(row)


class _ProvenancePostgresConnection:
    def __init__(self, current, lineage, events):
        self.current = current
        self.lineage = lineage
        self.events = events
        self.statements = []
        self.params = []
        self.active_rows = []

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, statement, params):
        self.statements.append(statement)
        self.params.append(params)
        if "FROM strict_docx_v3_document_custody custody" in statement:
            row = _postgres_active_row_contract(self.current, statement)
            self.active_rows.append(row)
            return _RecordingResult(row)
        if "FROM document_glossary_revision_events" in statement:
            if params["revision_id"] == self.lineage["revision_id"]:
                return _RecordingResult(self.events)
            if self.lineage.get("parent_row") and (
                params["revision_id"] == self.lineage["parent_row"]["revision_id"]
            ):
                return _RecordingResult(self.lineage["parent_events"])
            return _RecordingResult([])
        if "WHERE revision.revision_id" in statement:
            revision_id = params["revision_id"]
            if revision_id == self.lineage["revision_id"]:
                return _RecordingResult(self.lineage)
            if self.lineage.get("parent_row") and (
                revision_id == self.lineage["parent_row"]["revision_id"]
            ):
                return _RecordingResult(self.lineage["parent_row"])
        return _RecordingResult(None)


class _RecordingResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row if isinstance(self.row, dict) or self.row is None else None

    def fetchall(self):
        return self.row if isinstance(self.row, list) else []


if __name__ == "__main__":
    unittest.main()
