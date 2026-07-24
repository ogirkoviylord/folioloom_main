import unittest
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Thread
from unittest.mock import patch

from translator_service.admin.auth import AdminSession
from translator_service.admin.rbac import AdminRole
from translator_service.document_glossary_authoring import (
    GlossaryAuthoringDenied,
    create_document_glossary_revision,
    glossary_authoring_actor_from_session,
    read_active_document_glossary_revision,
    register_verified_docx_custody,
    revoke_document_glossary_revision,
    supersede_document_glossary_revision,
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
)
from translator_service.persistent_jobs import (
    DocumentGlossaryRevision,
    SQLiteTranslationJobStore,
)


class DocumentGlossaryAuthoringTest(unittest.TestCase):
    def test_bootstrap_owner_creates_revision_without_job_or_authorization(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"verified document bytes",
            )
            actor = glossary_authoring_actor_from_session(_owner_session())

            result = create_document_glossary_revision(
                store=store,
                storage=storage,
                actor=actor,
                source_object_key=source.object_key,
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )

            self.assertNotIsInstance(result, GlossaryAuthoringDenied)
            self.assertEqual(result.actor_id, "bootstrap-owner")
            self.assertEqual(result.actor_role, "owner")
            self.assertEqual(result.source_object_key, source.object_key)
            self.assertEqual(
                result.source_sha256, sha256(b"verified document bytes").hexdigest()
            )
            self.assertEqual(result.revision_sequence, 1)
            self.assertEqual(_count(store, "document_glossary_revisions"), 1)
            self.assertEqual(_count(store, "document_glossary_revision_events"), 1)
            self.assertEqual(_count(store, "strict_docx_v3_document_custody"), 1)
            self.assertEqual(_count(store, "glossary_approvals"), 1)
            self.assertEqual(_count(store, "translation_jobs"), 0)
            self.assertEqual(_count(store, "strict_docx_v3_authorizations"), 0)

    def test_non_owner_session_denies_without_persistence(self):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"verified document bytes",
            )
            actor = glossary_authoring_actor_from_session(
                AdminSession(
                    actor_id="operator",
                    role=AdminRole.OPERATOR,
                    expires_at=datetime.now(UTC) + timedelta(minutes=5),
                    csrf_token="csrf",
                )
            )

            result = create_document_glossary_revision(
                store=store,
                storage=storage,
                actor=actor,
                source_object_key=source.object_key,
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )

            self.assertEqual(
                result,
                GlossaryAuthoringDenied(code="glossary_authoring_actor_unauthorized"),
            )
            self.assertEqual(_count(store, "document_glossary_revisions"), 0)
            self.assertEqual(_count(store, "glossary_approvals"), 0)
            self.assertEqual(_count(store, "strict_docx_v3_document_custody"), 0)

    def test_custody_registration_verifies_docx_without_authorization_or_approval(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"verified document bytes",
            )

            result = register_verified_docx_custody(
                store=store, storage=storage, source_object_key=source.object_key
            )

            self.assertEqual(result.source_object_key, source.object_key)
            self.assertEqual(_count(store, "strict_docx_v3_document_custody"), 1)
            self.assertEqual(_count(store, "glossary_approvals"), 0)
            self.assertEqual(_count(store, "strict_docx_v3_authorizations"), 0)
            self.assertEqual(_count(store, "translation_jobs"), 0)

    def test_supersede_then_revoke_leaves_append_only_history_and_no_active_revision(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"verified document bytes",
            )
            actor = glossary_authoring_actor_from_session(_owner_session())
            first = create_document_glossary_revision(
                store=store,
                storage=storage,
                actor=actor,
                source_object_key=source.object_key,
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )

            second = supersede_document_glossary_revision(
                store=store,
                storage=storage,
                actor=actor,
                predecessor_revision_id=first.revision_id,
                snapshot=_snapshot(
                    snapshot_id="snapshot-2", source_canonical="Term two"
                ),
            )
            active = read_active_document_glossary_revision(
                store=store, document_custody_id=first.document_custody_id
            )
            revoked = revoke_document_glossary_revision(
                store=store, actor=actor, revision_id=second.revision_id
            )

            self.assertEqual(second.parent_revision_id, first.revision_id)
            self.assertEqual(second.revision_sequence, 2)
            self.assertEqual(active.revision_id, second.revision_id)
            self.assertEqual(revoked.revision_id, second.revision_id)
            self.assertEqual(_count(store, "document_glossary_revisions"), 2)
            self.assertEqual(_count(store, "document_glossary_revision_events"), 4)
            self.assertEqual(
                read_active_document_glossary_revision(
                    store=store, document_custody_id=first.document_custody_id
                ),
                GlossaryAuthoringDenied("glossary_authoring_approval_revoked"),
            )

    def test_supersede_rolls_back_successor_when_predecessor_event_insert_fails(self):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"verified document bytes",
            )
            actor = glossary_authoring_actor_from_session(_owner_session())
            first = create_document_glossary_revision(
                store=store,
                storage=storage,
                actor=actor,
                source_object_key=source.object_key,
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )
            store._connection.execute(
                """
                CREATE TRIGGER reject_superseded_event
                BEFORE INSERT ON document_glossary_revision_events
                WHEN NEW.event_type = 'superseded'
                BEGIN
                    SELECT RAISE(ABORT, 'test failure');
                END
                """
            )

            with self.assertRaisesRegex(Exception, "test failure"):
                supersede_document_glossary_revision(
                    store=store,
                    storage=storage,
                    actor=actor,
                    predecessor_revision_id=first.revision_id,
                    snapshot=_snapshot(
                        snapshot_id="snapshot-2", source_canonical="Term two"
                    ),
                )

            self.assertEqual(_count(store, "document_glossary_revisions"), 1)
            self.assertEqual(_count(store, "document_glossary_revision_events"), 1)
            self.assertEqual(_count(store, "glossary_approvals"), 1)

    def test_supersede_rolls_back_when_begin_immediate_fails(self):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"verified document bytes",
            )
            actor = glossary_authoring_actor_from_session(_owner_session())
            first = create_document_glossary_revision(
                store=store,
                storage=storage,
                actor=actor,
                source_object_key=source.object_key,
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )
            self.assertNotIsInstance(first, GlossaryAuthoringDenied)
            sentinel = RuntimeError("begin immediate failure")
            connection = _BeginFailingConnection(store._connection, sentinel)
            object.__setattr__(store, "_connection", connection)

            with self.assertRaises(RuntimeError) as raised:
                supersede_document_glossary_revision(
                    store=store,
                    storage=storage,
                    actor=actor,
                    predecessor_revision_id=first.revision_id,
                    snapshot=_snapshot(
                        snapshot_id="snapshot-2", source_canonical="Term two"
                    ),
                )

            self.assertIs(raised.exception, sentinel)
            self.assertEqual(connection.begin_attempts, 1)
            self.assertEqual(connection.rollback_calls, 1)

    def test_revoke_rolls_back_when_begin_immediate_fails(self):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"verified document bytes",
            )
            actor = glossary_authoring_actor_from_session(_owner_session())
            revision = create_document_glossary_revision(
                store=store,
                storage=storage,
                actor=actor,
                source_object_key=source.object_key,
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )
            self.assertIsInstance(revision, DocumentGlossaryRevision)
            sentinel = RuntimeError("begin immediate failure")
            connection = _BeginFailingConnection(store._connection, sentinel)
            object.__setattr__(store, "_connection", connection)

            with self.assertRaises(RuntimeError) as raised:
                revoke_document_glossary_revision(
                    store=store, actor=actor, revision_id=revision.revision_id
                )

            self.assertIs(raised.exception, sentinel)
            self.assertEqual(connection.begin_attempts, 1)
            self.assertEqual(connection.rollback_calls, 1)
            self.assertEqual(_count(store, "document_glossary_revision_events"), 1)
            approval_status = store._connection.execute(
                "SELECT approval_status FROM glossary_approvals WHERE approval_id = ?",
                (revision.approval_id,),
            ).fetchone()[0]
            self.assertEqual(approval_status, "approved")

    def test_supersede_verifies_source_before_acquiring_write_lock(self):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"verified document bytes",
            )
            actor = glossary_authoring_actor_from_session(_owner_session())
            first = create_document_glossary_revision(
                store=store,
                storage=storage,
                actor=actor,
                source_object_key=source.object_key,
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )
            original_get_bytes = storage.get_bytes

            def get_bytes_without_write_lock(object_key: str) -> bytes:
                self.assertFalse(store._connection.in_transaction)
                return original_get_bytes(object_key)

            with patch.object(
                storage,
                "get_bytes",
                side_effect=get_bytes_without_write_lock,
            ):
                result = supersede_document_glossary_revision(
                    store=store,
                    storage=storage,
                    actor=actor,
                    predecessor_revision_id=first.revision_id,
                    snapshot=_snapshot(
                        snapshot_id="snapshot-2", source_canonical="Term two"
                    ),
                )

            self.assertNotIsInstance(result, GlossaryAuthoringDenied)

    def test_create_denies_duplicate_snapshot_for_current_parent(self):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"verified document bytes",
            )
            actor = glossary_authoring_actor_from_session(_owner_session())
            first = create_document_glossary_revision(
                store=store,
                storage=storage,
                actor=actor,
                source_object_key=source.object_key,
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )

            result = create_document_glossary_revision(
                store=store,
                storage=storage,
                actor=actor,
                source_object_key=source.object_key,
                snapshot=_snapshot(),
                expected_parent_revision_id=first.revision_id,
            )

            self.assertEqual(
                result,
                GlossaryAuthoringDenied("glossary_authoring_duplicate_snapshot"),
            )
            self.assertEqual(_count(store, "document_glossary_revisions"), 1)

    def test_create_denies_custody_conflict_without_new_revision(self):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"verified document bytes",
            )
            actor = glossary_authoring_actor_from_session(_owner_session())
            first = create_document_glossary_revision(
                store=store,
                storage=storage,
                actor=actor,
                source_object_key=source.object_key,
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )
            store._connection.execute(
                "UPDATE strict_docx_v3_document_custody SET source_sha256 = 'tampered'"
            )
            store._connection.commit()

            result = create_document_glossary_revision(
                store=store,
                storage=storage,
                actor=actor,
                source_object_key=source.object_key,
                snapshot=_snapshot(
                    snapshot_id="snapshot-2", source_canonical="Term two"
                ),
                expected_parent_revision_id=first.revision_id,
            )

            self.assertEqual(
                result,
                GlossaryAuthoringDenied(
                    "glossary_authoring_document_custody_conflict"
                ),
            )
            self.assertEqual(_count(store, "document_glossary_revisions"), 1)

    def test_revoke_denies_non_current_revision_without_new_event(self):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"verified document bytes",
            )
            actor = glossary_authoring_actor_from_session(_owner_session())
            first = create_document_glossary_revision(
                store=store,
                storage=storage,
                actor=actor,
                source_object_key=source.object_key,
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )
            supersede_document_glossary_revision(
                store=store,
                storage=storage,
                actor=actor,
                predecessor_revision_id=first.revision_id,
                snapshot=_snapshot(
                    snapshot_id="snapshot-2", source_canonical="Term two"
                ),
            )

            result = revoke_document_glossary_revision(
                store=store, actor=actor, revision_id=first.revision_id
            )

            self.assertEqual(
                result,
                GlossaryAuthoringDenied("glossary_authoring_parent_not_current"),
            )
            self.assertEqual(_count(store, "document_glossary_revision_events"), 3)

    def test_revoke_rolls_back_without_mutation_when_begin_immediate_fails(self):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"verified document bytes",
            )
            actor = glossary_authoring_actor_from_session(_owner_session())
            revision = create_document_glossary_revision(
                store=store,
                storage=storage,
                actor=actor,
                source_object_key=source.object_key,
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )
            sentinel = RuntimeError("begin immediate failure")
            connection = _BeginFailingConnection(store._connection, sentinel)
            object.__setattr__(store, "_connection", connection)

            with self.assertRaises(RuntimeError) as raised:
                revoke_document_glossary_revision(
                    store=store, actor=actor, revision_id=revision.revision_id
                )

            self.assertIs(raised.exception, sentinel)
            self.assertEqual(connection.begin_attempts, 1)
            self.assertEqual(connection.rollback_calls, 1)
            self.assertEqual(_count(store, "document_glossary_revisions"), 1)
            self.assertEqual(_count(store, "glossary_approvals"), 1)
            self.assertEqual(_count(store, "document_glossary_revision_events"), 1)
            self.assertEqual(
                store._connection.execute(
                    "SELECT approval_status FROM glossary_approvals"
                ).fetchone()[0],
                "approved",
            )

    def test_two_connections_create_a_single_linear_first_revision(self):
        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "jobs.sqlite3"
            initializer = SQLiteTranslationJobStore(database_path)
            self.addCleanup(initializer.close)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"verified document bytes",
            )
            actor = glossary_authoring_actor_from_session(_owner_session())
            barrier = Barrier(2)
            results = []

            def create_from_separate_connection() -> None:
                store = SQLiteTranslationJobStore(database_path)
                try:
                    barrier.wait()
                    results.append(
                        create_document_glossary_revision(
                            store=store,
                            storage=storage,
                            actor=actor,
                            source_object_key=source.object_key,
                            snapshot=_snapshot(),
                            expected_parent_revision_id=None,
                        )
                    )
                finally:
                    store.close()

            threads = [Thread(target=create_from_separate_connection) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(_count(initializer, "document_glossary_revisions"), 1)
            self.assertEqual(
                _count(initializer, "document_glossary_revision_events"), 1
            )
            self.assertEqual(_count(initializer, "glossary_approvals"), 1)
            self.assertEqual(
                sum(not isinstance(item, GlossaryAuthoringDenied) for item in results),
                1,
            )
            self.assertIn(
                GlossaryAuthoringDenied("glossary_authoring_parent_not_current"),
                results,
            )

    def test_active_read_fails_closed_when_revision_actor_provenance_is_tampered(self):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"verified document bytes",
            )
            revision = create_document_glossary_revision(
                store=store,
                storage=storage,
                actor=glossary_authoring_actor_from_session(_owner_session()),
                source_object_key=source.object_key,
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )
            store._connection.execute(
                "UPDATE document_glossary_revisions SET actor_id = 'tampered'"
            )
            store._connection.commit()

            self.assertEqual(
                read_active_document_glossary_revision(
                    store=store, document_custody_id=revision.document_custody_id
                ),
                GlossaryAuthoringDenied("glossary_authoring_provenance_inconsistent"),
            )

    def test_active_read_fails_closed_when_role_or_schema_provenance_is_tampered(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="book.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"verified document bytes",
            )
            revision = create_document_glossary_revision(
                store=store,
                storage=storage,
                actor=glossary_authoring_actor_from_session(_owner_session()),
                source_object_key=source.object_key,
                snapshot=_snapshot(),
                expected_parent_revision_id=None,
            )
            store._connection.execute("PRAGMA ignore_check_constraints = ON")
            store._connection.execute(
                "UPDATE document_glossary_revisions SET actor_role = 'operator'"
            )
            store._connection.commit()
            self.assertEqual(
                read_active_document_glossary_revision(
                    store=store, document_custody_id=revision.document_custody_id
                ),
                GlossaryAuthoringDenied("glossary_authoring_provenance_inconsistent"),
            )
            store._connection.execute(
                "UPDATE document_glossary_revisions SET actor_role = 'owner', "
                "snapshot_schema_version = 'tampered'"
            )
            store._connection.commit()
            store._connection.execute("PRAGMA ignore_check_constraints = OFF")

            self.assertEqual(
                read_active_document_glossary_revision(
                    store=store, document_custody_id=revision.document_custody_id
                ),
                GlossaryAuthoringDenied("glossary_authoring_provenance_inconsistent"),
            )
    def test_active_read_fails_closed_for_tampered_predecessor_superseded_event(
        self,
    ):
        for column, value in (
            ("actor_id", "tampered"),
            ("actor_role", "operator"),
            ("authn_schema_version", "tampered-v1"),
        ):
            with self.subTest(column=column):
                with TemporaryDirectory() as temp_dir:
                    store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
                    self.addCleanup(store.close)
                    storage = LocalObjectStorage(Path(temp_dir) / "objects")
                    source = storage.put_bytes(
                        kind=StoredFileKind.ORIGINAL,
                        file_name="book.docx",
                        content_type=(
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document"
                        ),
                        content=b"verified document bytes",
                    )
                    actor = glossary_authoring_actor_from_session(_owner_session())
                    predecessor = create_document_glossary_revision(
                        store=store,
                        storage=storage,
                        actor=actor,
                        source_object_key=source.object_key,
                        snapshot=_snapshot(),
                        expected_parent_revision_id=None,
                    )
                    successor = supersede_document_glossary_revision(
                        store=store,
                        storage=storage,
                        actor=actor,
                        predecessor_revision_id=predecessor.revision_id,
                        snapshot=_snapshot(
                            snapshot_id="snapshot-2", source_canonical="Term two"
                        ),
                    )
                    store._connection.execute("PRAGMA ignore_check_constraints = ON")
                    store._connection.execute(
                        f"UPDATE document_glossary_revision_events SET {column} = ? "
                        "WHERE revision_id = ? AND event_type = 'superseded'",
                        (value, predecessor.revision_id),
                    )
                    store._connection.commit()
                    store._connection.execute("PRAGMA ignore_check_constraints = OFF")

                    self.assertEqual(
                        read_active_document_glossary_revision(
                            store=store,
                            document_custody_id=successor.document_custody_id,
                        ),
                        GlossaryAuthoringDenied(
                            "glossary_authoring_provenance_inconsistent"
                        ),
                    )


def _owner_session() -> AdminSession:
    return AdminSession(
        actor_id="bootstrap-owner",
        role=AdminRole.OWNER,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        csrf_token="csrf",
    )


def _snapshot(snapshot_id="snapshot-1", source_canonical="Term") -> GlossarySnapshot:
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


def _count(store: SQLiteTranslationJobStore, table_name: str) -> int:
    return store._connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]


class _BeginFailingConnection:
    def __init__(self, connection, sentinel: Exception):
        self._connection = connection
        self._sentinel = sentinel
        self.begin_attempts = 0
        self.rollback_calls = 0

    def execute(self, statement, *args, **kwargs):
        if statement == "BEGIN IMMEDIATE":
            self.begin_attempts += 1
            raise self._sentinel
        return self._connection.execute(statement, *args, **kwargs)

    def rollback(self):
        self.rollback_calls += 1
        return self._connection.rollback()

    def __getattr__(self, name):
        return getattr(self._connection, name)


if __name__ == "__main__":
    unittest.main()
