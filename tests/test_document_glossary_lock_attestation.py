import ast
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from translator_service import document_glossary_lock_attestation
from translator_service.admin.auth import AdminSession
from translator_service.admin.rbac import AdminRole
from translator_service.document_glossary_authoring import (
    create_document_glossary_revision,
    glossary_authoring_actor_from_session,
    revoke_document_glossary_revision,
    supersede_document_glossary_revision,
)
from translator_service.document_glossary_lock_attestation import (
    DocumentGlossaryLockAttestation,
    DocumentGlossaryLockDenied,
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
)
from translator_service.persistent_jobs import SQLiteTranslationJobStore
from translator_service.source_registry_service import (
    SourceRegistryActor,
    register_verified_original_docx_source,
)
from translator_service.verified_original_docx import verify_original_docx_source


class DocumentGlossaryLockAttestationTest(unittest.TestCase):
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
        self.source = source
        actor = SourceRegistryActor("bootstrap-owner", "owner", "admin-session-v1")
        custody = register_verified_original_docx_source(
            store=self.store,
            actor=actor,
            source=verify_original_docx_source(self.storage, source.object_key),
        )
        self.custody_id = custody.document_custody_id
        self.revision = create_document_glossary_revision(
            store=self.store,
            storage=self.storage,
            actor=glossary_authoring_actor_from_session(self.session),
            source_object_key=source.object_key,
            snapshot=_snapshot(),
            expected_parent_revision_id=None,
        )

    def test_first_action_replay_and_status_are_metadata_only(self):
        first = self._assert_prohibited_tables_unchanged(
            lambda: attest_document_glossary_lock(
                store=self.store,
                storage=self.storage,
                session=self.session,
                document_custody_id=self.custody_id,
            )
        )
        replay = self._assert_prohibited_tables_unchanged(
            lambda: attest_document_glossary_lock(
                store=self.store,
                storage=self.storage,
                session=self.session,
                document_custody_id=self.custody_id,
            )
        )
        status = self._assert_prohibited_tables_unchanged(
            lambda: read_document_glossary_lock_status(
                store=self.store,
                storage=self.storage,
                session=self.session,
                document_custody_id=self.custody_id,
            )
        )
        self.assertIsInstance(first, DocumentGlossaryLockAttestation)
        self.assertEqual(
            (
                first.outcome,
                replay.outcome,
                first.attestation_id,
                replay.attestation_id,
            ),
            ("created", "idempotent", first.attestation_id, first.attestation_id),
        )
        self.assertEqual(
            self.store._connection.execute(
                "SELECT COUNT(*) FROM document_glossary_lock_attestations"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(status, DocumentGlossaryLockStatus(self.custody_id, "active"))
        self.assertFalse(hasattr(first, "snapshot_digest"))
        self.assertFalse(hasattr(first, "source_object_key"))

    def test_unattested_current_revision_is_absent(self):
        self.assertEqual(
            read_document_glossary_lock_status(
                store=self.store,
                storage=self.storage,
                session=self.session,
                document_custody_id=self.custody_id,
            ),
            DocumentGlossaryLockStatus(self.custody_id, "absent"),
        )

    def test_source_reverification_failure_is_denied_without_write(self):
        self.assertTrue(self.storage.delete(self.source.object_key))

        result = self._assert_prohibited_tables_unchanged(
            lambda: attest_document_glossary_lock(
                store=self.store,
                storage=self.storage,
                session=self.session,
                document_custody_id=self.custody_id,
            )
        )

        self.assertIsInstance(result, DocumentGlossaryLockDenied)
        self.assertEqual(
            result.code,
            "glossary_lock_attestation_source_registry_source_document_missing",
        )
        self.assertEqual(self._attestation_count(), 0)

    def test_status_distinguishes_superseded_and_revoked_without_mutating_attestation(
        self,
    ):
        attest_document_glossary_lock(
            store=self.store,
            storage=self.storage,
            session=self.session,
            document_custody_id=self.custody_id,
        )
        successor = supersede_document_glossary_revision(
            store=self.store,
            storage=self.storage,
            actor=glossary_authoring_actor_from_session(self.session),
            predecessor_revision_id=self.revision.revision_id,
            snapshot=_snapshot("two"),
        )
        self.assertEqual(
            read_document_glossary_lock_status(
                store=self.store,
                storage=self.storage,
                session=self.session,
                document_custody_id=self.custody_id,
            ),
            DocumentGlossaryLockStatus(self.custody_id, "superseded"),
        )
        revoke_document_glossary_revision(
            store=self.store,
            actor=glossary_authoring_actor_from_session(self.session),
            revision_id=successor.revision_id,
        )
        self.assertEqual(
            read_document_glossary_lock_status(
                store=self.store,
                storage=self.storage,
                session=self.session,
                document_custody_id=self.custody_id,
            ),
            DocumentGlossaryLockStatus(self.custody_id, "superseded"),
        )
        self.assertEqual(
            self.store._connection.execute(
                "SELECT COUNT(*) FROM document_glossary_lock_attestations"
            ).fetchone()[0],
            1,
        )

    def test_status_distinguishes_revoked_without_mutating_attestation(self):
        attest_document_glossary_lock(
            store=self.store,
            storage=self.storage,
            session=self.session,
            document_custody_id=self.custody_id,
        )
        revoke_document_glossary_revision(
            store=self.store,
            actor=glossary_authoring_actor_from_session(self.session),
            revision_id=self.revision.revision_id,
        )

        self.assertEqual(
            read_document_glossary_lock_status(
                store=self.store,
                storage=self.storage,
                session=self.session,
                document_custody_id=self.custody_id,
            ),
            DocumentGlossaryLockStatus(self.custody_id, "revoked"),
        )
        self.assertEqual(self._attestation_count(), 1)

    def test_concurrent_exact_replays_persist_one_attestation(self):
        second_store = SQLiteTranslationJobStore(Path(self.temp.name) / "jobs.sqlite3")
        self.addCleanup(second_store.close)
        barrier = threading.Barrier(2)

        def attest(store):
            barrier.wait()
            return attest_document_glossary_lock(
                store=store,
                storage=self.storage,
                session=self.session,
                document_custody_id=self.custody_id,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attest, (self.store, second_store)))

        self.assertEqual(
            {result.outcome for result in results}, {"created", "idempotent"}
        )
        self.assertEqual(len({result.attestation_id for result in results}), 1)
        self.assertEqual(self._attestation_count(), 1)

    def test_failed_write_rolls_back_without_attestation(self):
        with patch.object(
            document_glossary_lock_attestation,
            "_to_db_time",
            side_effect=RuntimeError("injected failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected failure"):
                attest_document_glossary_lock(
                    store=self.store,
                    storage=self.storage,
                    session=self.session,
                    document_custody_id=self.custody_id,
                )

        self.assertEqual(self._attestation_count(), 0)

    def test_foreign_revision_provenance_fails_closed_without_prohibited_side_effects(
        self,
    ):
        self.store._connection.execute(
            "UPDATE document_glossary_revisions "
            "SET actor_id = 'foreign-owner' WHERE revision_id = ?",
            (self.revision.revision_id,),
        )
        self.store._connection.commit()

        result = self._assert_prohibited_tables_unchanged(
            lambda: attest_document_glossary_lock(
                store=self.store,
                storage=self.storage,
                session=self.session,
                document_custody_id=self.custody_id,
            )
        )

        self.assertIsInstance(result, DocumentGlossaryLockDenied)
        self.assertEqual(
            result.code, "glossary_lock_attestation_provenance_inconsistent"
        )
        self.assertEqual(self._attestation_count(), 0)


    def test_module_isolation_and_postgres_sql_shape(self):
        module_path = Path(document_glossary_lock_attestation.__file__)
        tree = ast.parse(module_path.read_text())
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }

        self.assertFalse(any("workbench" in name for name in imports))
        self.assertNotIn(
            "translator_service.strict_docx_v3_authorization_service", imports
        )
        self.assertFalse(
            any(
                forbidden in _call_target_name(node)
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                for forbidden in ("provider", "cache", "telegram", "workbench")
            )
        )
        self.assertIn(
            "FOR UPDATE OF custody, revision, approval, snapshot",
            document_glossary_lock_attestation._POSTGRES_CURRENT_ROW_SQL,
        )
        self.assertNotIn(
            "FOR UPDATE",
            document_glossary_lock_attestation._POSTGRES_CURRENT_ROW_FOR_READ_SQL,
        )
        self.assertIn(
            "ON CONFLICT (",
            document_glossary_lock_attestation._POSTGRES_INSERT_ATTESTATION_SQL,
        )
        self.assertIn(
            "DO NOTHING RETURNING *",
            document_glossary_lock_attestation._POSTGRES_INSERT_ATTESTATION_SQL,
        )
        self.assertTrue(
            any(
                "SELECT event_type FROM document_glossary_revision_events" in value
                for value in (
                    document_glossary_lock_attestation._postgres_attestation_lifecycle
                    .__code__.co_consts
                )
                if isinstance(value, str)
            )
        )

    def _attestation_count(self):
        return self.store._connection.execute(
            "SELECT COUNT(*) FROM document_glossary_lock_attestations"
        ).fetchone()[0]

    def _prohibited_table_counts(self):
        tables = (
            "translation_jobs",
            "work_units",
            "strict_docx_v3_authorizations",
            "strict_docx_v3_job_authorizations",
            "strict_job_glossary_bindings",
        )
        return {
            table: self.store._connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in tables
        }

    def _assert_prohibited_tables_unchanged(self, operation):
        before = self._prohibited_table_counts()
        result = operation()
        self.assertEqual(self._prohibited_table_counts(), before)
        return result


def _call_target_name(node):
    function = node.func
    parts = []
    while isinstance(function, ast.Attribute):
        parts.append(function.attr)
        function = function.value
    if isinstance(function, ast.Name):
        parts.append(function.id)
    return ".".join(reversed(parts))


def _snapshot(term="one"):
    evidence = GlossaryEvidenceRef(
        evidence_id=f"evidence-{term}",
        evidence_type=GlossaryEvidenceType.SOURCE_ANCHOR,
        unit_sequence=1,
        source_block_id="block-1",
        source_scope="document",
        surface=GlossaryEvidenceSurface.BODY,
    )
    entry = GlossaryEntry(
        entry_id=f"entry-{term}",
        category=GlossaryEntryCategory.TERM,
        layer=GlossaryLayer.SOFT,
        status=GlossaryEntryStatus.AUTO_DETECTED,
        source_canonical=f"Term {term}",
        evidence_refs=(evidence.evidence_id,),
        confidence=0.8,
    )
    return GlossarySnapshot(
        snapshot_id=f"snapshot-{term}",
        source_language="en",
        target_language="ru",
        entries=(entry,),
        evidence=(evidence,),
    )


if __name__ == "__main__":
    unittest.main()
