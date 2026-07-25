import inspect
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.persistent_jobs import SQLiteTranslationJobStore
from translator_service.source_registry_service import (
    _POSTGRES_INSERT_CUSTODY_SQL,
    _POSTGRES_INSERT_EVENT_SQL,
    _POSTGRES_SELECT_BY_CUSTODY_SQL,
    _POSTGRES_SELECT_BY_KEY_SQL,
    RegisteredOriginalDocxSource,
    SourceRegistryActor,
    SourceRegistryDenied,
    _register_postgres,
    register_verified_original_docx_source,
    select_registered_original_docx_source,
)
from translator_service.verified_original_docx import (
    VerifiedOriginalDocxSource,
    verify_original_docx_source,
)


class SourceRegistryServiceTest(unittest.TestCase):
    def test_public_registration_accepts_only_verified_source_and_has_no_list_surface(
        self,
    ):
        import translator_service.source_registry_service as registry_service

        parameters = inspect.signature(
            register_verified_original_docx_source
        ).parameters

        self.assertEqual(set(parameters), {"store", "actor", "source"})
        self.assertNotIn("source_object_key", parameters)
        self.assertFalse(
            hasattr(registry_service, "list_registered_original_docx_sources")
        )

    def test_postgres_sql_shapes_keep_registration_canonical_and_bind_actor_scope(self):
        self.assertIn("%(source_object_key)s", _POSTGRES_SELECT_BY_KEY_SQL)
        self.assertIn("%(document_custody_id)s", _POSTGRES_SELECT_BY_CUSTODY_SQL)
        self.assertIn("registry_authn_schema_version", _POSTGRES_INSERT_CUSTODY_SQL)
        self.assertIn(
            "ON CONFLICT (source_object_key) DO NOTHING",
            _POSTGRES_INSERT_CUSTODY_SQL,
        )
        self.assertIn("RETURNING document_custody_id", _POSTGRES_INSERT_CUSTODY_SQL)
        self.assertIn("%(event_type)s", _POSTGRES_INSERT_EVENT_SQL)

    def test_postgres_conflict_rereads_winner_and_records_reused_event(self):
        source = VerifiedOriginalDocxSource(
            object_key="original/concurrent.docx",
            sha256="a" * 64,
            size_bytes=23,
        )
        winner_row = {
            "document_custody_id": "document-custody-winner",
            "source_sha256": source.sha256,
            "source_size_bytes": source.size_bytes,
            "document_kind": "docx",
            "registry_owner_actor_id": self.owner.actor_id,
            "registry_actor_role": self.owner.role,
            "registry_authn_schema_version": self.owner.authn_schema_version,
        }
        connection = _RecordingPostgresConnection([None, winner_row])

        result = _register_postgres(
            _FakePostgresStore(connection), source, self.owner
        )

        self.assertIsInstance(result, RegisteredOriginalDocxSource)
        self.assertEqual(result.document_custody_id, "document-custody-winner")
        self.assertEqual(
            connection.statements,
            [
                _POSTGRES_INSERT_CUSTODY_SQL,
                _POSTGRES_SELECT_BY_KEY_SQL,
                _POSTGRES_INSERT_EVENT_SQL,
            ],
        )
        insert_params, select_params, event_params = connection.params
        self.assertEqual(insert_params["source_object_key"], source.object_key)
        self.assertEqual(insert_params["registry_owner_actor_id"], self.owner.actor_id)
        self.assertEqual(select_params, {"source_object_key": source.object_key})
        self.assertEqual(event_params["event_type"], "registration_reused")
        self.assertEqual(event_params["registry_owner_actor_id"], self.owner.actor_id)
        self.assertEqual(event_params["registry_actor_role"], self.owner.role)
        self.assertEqual(
            event_params["registry_authn_schema_version"],
            self.owner.authn_schema_version,
        )

    def test_postgres_conflict_denies_mismatched_winner_identity_without_event(self):
        source = VerifiedOriginalDocxSource(
            object_key="original/concurrent.docx",
            sha256="a" * 64,
            size_bytes=23,
        )
        conflicting_winner_row = {
            "document_custody_id": "document-custody-winner",
            "source_sha256": "b" * 64,
            "source_size_bytes": source.size_bytes,
            "document_kind": "docx",
            "registry_owner_actor_id": self.owner.actor_id,
            "registry_actor_role": self.owner.role,
            "registry_authn_schema_version": self.owner.authn_schema_version,
        }
        connection = _RecordingPostgresConnection([None, conflicting_winner_row])

        result = _register_postgres(
            _FakePostgresStore(connection), source, self.owner
        )

        self.assertEqual(
            result,
            SourceRegistryDenied("source_registry_custody_denied"),
        )
        self.assertEqual(
            connection.statements,
            [_POSTGRES_INSERT_CUSTODY_SQL, _POSTGRES_SELECT_BY_KEY_SQL],
        )
        self.assertNotIn(_POSTGRES_INSERT_EVENT_SQL, connection.statements)

    def test_postgres_conflict_denies_foreign_winner_provenance_without_event(self):
        source = VerifiedOriginalDocxSource(
            object_key="original/concurrent.docx",
            sha256="a" * 64,
            size_bytes=23,
        )
        foreign_winner_row = {
            "document_custody_id": "document-custody-winner",
            "source_sha256": source.sha256,
            "source_size_bytes": source.size_bytes,
            "document_kind": "docx",
            "registry_owner_actor_id": "foreign-owner",
            "registry_actor_role": "owner",
            "registry_authn_schema_version": "admin-session-v2",
        }
        connection = _RecordingPostgresConnection([None, foreign_winner_row])

        result = _register_postgres(
            _FakePostgresStore(connection), source, self.owner
        )

        self.assertEqual(
            result,
            SourceRegistryDenied("source_registry_ownership_denied"),
        )
        self.assertEqual(
            connection.statements,
            [_POSTGRES_INSERT_CUSTODY_SQL, _POSTGRES_SELECT_BY_KEY_SQL],
        )
        self.assertNotIn(_POSTGRES_INSERT_EVENT_SQL, connection.statements)

    def test_postgres_first_insert_rereads_canonical_row_and_records_registered_event(
        self,
    ):
        source = VerifiedOriginalDocxSource(
            object_key="original/first-registration.docx",
            sha256="a" * 64,
            size_bytes=23,
        )
        inserted_row = {"document_custody_id": "document-custody-new"}
        canonical_row = {
            "document_custody_id": "document-custody-new",
            "source_sha256": source.sha256,
            "source_size_bytes": source.size_bytes,
            "document_kind": "docx",
            "registry_owner_actor_id": self.owner.actor_id,
            "registry_actor_role": self.owner.role,
            "registry_authn_schema_version": self.owner.authn_schema_version,
        }
        connection = _RecordingPostgresConnection([inserted_row, canonical_row])

        result = _register_postgres(
            _FakePostgresStore(connection), source, self.owner
        )

        self.assertEqual(
            result,
            RegisteredOriginalDocxSource(
                document_custody_id="document-custody-new",
                source_sha256=source.sha256,
                source_size_bytes=source.size_bytes,
            ),
        )
        self.assertFalse(hasattr(result, "source_object_key"))
        self.assertEqual(
            connection.statements,
            [
                _POSTGRES_INSERT_CUSTODY_SQL,
                _POSTGRES_SELECT_BY_KEY_SQL,
                _POSTGRES_INSERT_EVENT_SQL,
            ],
        )
        self.assertEqual(connection.params[2]["event_type"], "registered")

    def test_postgres_first_registration_succeeds_and_records_registered_event(self):
        source = VerifiedOriginalDocxSource(
            object_key="original/first.docx",
            sha256="b" * 64,
            size_bytes=42,
        )
        own_row = {
            "document_custody_id": "document-custody-new",
            "source_sha256": source.sha256,
            "source_size_bytes": source.size_bytes,
            "document_kind": "docx",
            "registry_owner_actor_id": self.owner.actor_id,
            "registry_actor_role": self.owner.role,
            "registry_authn_schema_version": self.owner.authn_schema_version,
        }
        connection = _RecordingPostgresConnection([own_row, own_row])

        result = _register_postgres(
            _FakePostgresStore(connection), source, self.owner
        )

        self.assertIsInstance(result, RegisteredOriginalDocxSource)
        if not isinstance(result, RegisteredOriginalDocxSource):
            self.fail(f"expected registered source, got {result!r}")
        self.assertEqual(result.document_custody_id, "document-custody-new")
        self.assertEqual(
            connection.statements,
            [
                _POSTGRES_INSERT_CUSTODY_SQL,
                _POSTGRES_SELECT_BY_KEY_SQL,
                _POSTGRES_INSERT_EVENT_SQL,
            ],
        )
        insert_params, select_params, event_params = connection.params
        self.assertEqual(insert_params["source_object_key"], source.object_key)
        self.assertEqual(insert_params["registry_owner_actor_id"], self.owner.actor_id)
        self.assertEqual(select_params, {"source_object_key": source.object_key})
        self.assertEqual(event_params["event_type"], "registered")
        self.assertEqual(event_params["registry_owner_actor_id"], self.owner.actor_id)
        self.assertEqual(event_params["registry_actor_role"], self.owner.role)
        self.assertEqual(
            event_params["registry_authn_schema_version"],
            self.owner.authn_schema_version,
        )

    def setUp(self):
        self._temp_dir = TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        root = Path(self._temp_dir.name)
        self.store = SQLiteTranslationJobStore(root / "jobs.sqlite3")
        self.addCleanup(self.store.close)
        self.storage = LocalObjectStorage(root / "objects")
        self.owner = SourceRegistryActor(
            actor_id="bootstrap-owner",
            role="owner",
            authn_schema_version="admin-session-v1",
        )

    def test_register_reuses_exact_identity_and_records_actor_audit(self):
        source = self._verified_original_docx(b"verified source")

        first = register_verified_original_docx_source(
            store=self.store,
            actor=self.owner,
            source=source,
        )
        second = register_verified_original_docx_source(
            store=self.store,
            actor=self.owner,
            source=source,
        )

        self.assertEqual(first, second)
        self.assertEqual(first.source_sha256, source.sha256)
        self.assertEqual(first.source_size_bytes, source.size_bytes)
        self.assertFalse(hasattr(first, "source_object_key"))
        events = self.store._connection.execute(
            "SELECT event_type, registry_owner_actor_id FROM source_registry_events "
            "ORDER BY rowid"
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in events],
            [
                ("registered", "bootstrap-owner"),
                ("registration_reused", "bootstrap-owner"),
            ],
        )

    def test_sqlite_conflict_denies_mismatched_identity_without_event(self):
        source = self._verified_original_docx(b"content-a")
        document_custody_id = "conflicting-identity-custody"
        self.store._connection.execute(
            """INSERT INTO strict_docx_v3_document_custody (
            document_custody_id, source_object_key, source_sha256,
            source_size_bytes, document_kind, created_at,
            registry_owner_actor_id, registry_actor_role,
            registry_authn_schema_version
            ) VALUES (?, ?, ?, ?, 'docx', ?, ?, ?, ?)""",
            (
                document_custody_id,
                source.object_key,
                "b" * 64,
                99,
                "now",
                self.owner.actor_id,
                self.owner.role,
                self.owner.authn_schema_version,
            ),
        )
        self.store._connection.commit()

        result = register_verified_original_docx_source(
            store=self.store,
            actor=self.owner,
            source=source,
        )

        self.assertEqual(
            result,
            SourceRegistryDenied("source_registry_custody_denied"),
        )
        event_count = self.store._connection.execute(
            "SELECT COUNT(*) FROM source_registry_events "
            "WHERE document_custody_id = ?",
            (document_custody_id,),
        ).fetchone()[0]
        self.assertEqual(event_count, 0)

    def test_sqlite_conflict_denies_foreign_provenance_without_event(self):
        source = self._verified_original_docx(b"content-c")
        document_custody_id = "foreign-provenance-custody"
        self.store._connection.execute(
            """INSERT INTO strict_docx_v3_document_custody (
            document_custody_id, source_object_key, source_sha256,
            source_size_bytes, document_kind, created_at,
            registry_owner_actor_id, registry_actor_role,
            registry_authn_schema_version
            ) VALUES (?, ?, ?, ?, 'docx', ?, ?, ?, ?)""",
            (
                document_custody_id,
                source.object_key,
                source.sha256,
                source.size_bytes,
                "now",
                "foreign-owner",
                self.owner.role,
                self.owner.authn_schema_version,
            ),
        )
        self.store._connection.commit()

        result = register_verified_original_docx_source(
            store=self.store,
            actor=self.owner,
            source=source,
        )

        self.assertEqual(
            result,
            SourceRegistryDenied("source_registry_ownership_denied"),
        )
        event_count = self.store._connection.execute(
            "SELECT COUNT(*) FROM source_registry_events "
            "WHERE document_custody_id = ?",
            (document_custody_id,),
        ).fetchone()[0]
        self.assertEqual(event_count, 0)

    def test_select_is_actor_scoped_and_reverifies_storage(self):
        source = self._verified_original_docx(b"verified source")
        registered = register_verified_original_docx_source(
            store=self.store,
            actor=self.owner,
            source=source,
        )
        self.assertIsInstance(registered, RegisteredOriginalDocxSource)
        other_actor = SourceRegistryActor(
            actor_id="other-owner",
            role="owner",
            authn_schema_version="admin-session-v1",
        )

        denied = select_registered_original_docx_source(
            store=self.store,
            storage=self.storage,
            actor=other_actor,
            document_custody_id=registered.document_custody_id,
        )
        selected = select_registered_original_docx_source(
            store=self.store,
            storage=self.storage,
            actor=self.owner,
            document_custody_id=registered.document_custody_id,
        )

        self.assertEqual(
            denied,
            SourceRegistryDenied("source_registry_ownership_denied"),
        )
        self.assertEqual(selected, registered)

    def test_non_owner_and_malformed_actors_are_denied_by_every_entry_point(self):
        source = self._verified_original_docx(b"verified source")
        actors = (
            SourceRegistryActor(
                actor_id="non-owner",
                role="operator",
                authn_schema_version="admin-session-v1",
            ),
            SourceRegistryActor(
                actor_id="",
                role="owner",
                authn_schema_version="admin-session-v1",
            ),
        )

        for actor in actors:
            with self.subTest(actor=actor):
                registered = register_verified_original_docx_source(
                    store=self.store,
                    actor=actor,
                    source=source,
                )
                selected = select_registered_original_docx_source(
                    store=self.store,
                    storage=self.storage,
                    actor=actor,
                    document_custody_id="unknown-custody",
                )

                self.assertEqual(
                    registered,
                    SourceRegistryDenied("source_registry_actor_unauthorized"),
                )
                self.assertEqual(
                    selected,
                    SourceRegistryDenied("source_registry_actor_unauthorized"),
                )

    def test_unsupported_backend_is_denied_by_every_entry_point(self):
        source = self._verified_original_docx(b"verified source")
        unsupported_store = object()

        registered = register_verified_original_docx_source(
            store=unsupported_store,
            actor=self.owner,
            source=source,
        )
        selected = select_registered_original_docx_source(
            store=unsupported_store,
            storage=self.storage,
            actor=self.owner,
            document_custody_id="unknown-custody",
        )

        self.assertEqual(
            registered,
            SourceRegistryDenied("source_registry_unsupported_backend"),
        )
        self.assertEqual(
            selected,
            SourceRegistryDenied("source_registry_unsupported_backend"),
        )

    def test_select_denies_when_reverified_storage_identity_no_longer_matches(self):
        source = self._verified_original_docx(b"verified source")
        registered = register_verified_original_docx_source(
            store=self.store,
            actor=self.owner,
            source=source,
        )
        self.store._connection.execute(
            "UPDATE strict_docx_v3_document_custody SET source_sha256 = 'tampered' "
            "WHERE document_custody_id = ?",
            (registered.document_custody_id,),
        )
        self.store._connection.commit()

        result = select_registered_original_docx_source(
            store=self.store,
            storage=self.storage,
            actor=self.owner,
            document_custody_id=registered.document_custody_id,
        )

        self.assertEqual(
            result,
            SourceRegistryDenied("source_registry_reconciliation_denied"),
        )

    def test_select_fails_closed_when_registered_storage_document_is_missing(self):
        source = self._verified_original_docx(b"verified source")
        registered = register_verified_original_docx_source(
            store=self.store,
            actor=self.owner,
            source=source,
        )
        self.assertIsInstance(registered, RegisteredOriginalDocxSource)
        assert isinstance(registered, RegisteredOriginalDocxSource)
        custody_count_before = self.store._connection.execute(
            "SELECT COUNT(*) FROM strict_docx_v3_document_custody"
        ).fetchone()[0]
        event_count_before = self.store._connection.execute(
            "SELECT COUNT(*) FROM source_registry_events"
        ).fetchone()[0]
        self.assertTrue(self.storage.delete(source.object_key))

        result = select_registered_original_docx_source(
            store=self.store,
            storage=self.storage,
            actor=self.owner,
            document_custody_id=registered.document_custody_id,
        )

        self.assertEqual(
            result,
            SourceRegistryDenied("source_registry_source_document_missing"),
        )
        self.assertFalse(hasattr(result, "source_object_key"))
        self.assertEqual(
            self.store._connection.execute(
                "SELECT COUNT(*) FROM strict_docx_v3_document_custody"
            ).fetchone()[0],
            custody_count_before,
        )
        self.assertEqual(
            self.store._connection.execute(
                "SELECT COUNT(*) FROM source_registry_events"
            ).fetchone()[0],
            event_count_before,
        )

    def test_registration_denies_unverified_sources_without_mutation(self):
        import translator_service.verified_original_docx as verified_original_docx

        stored = self._put_original_docx(b"verified source")
        capability_copied_source = VerifiedOriginalDocxSource(
            object_key=stored.object_key,
            sha256="a" * 64,
            size_bytes=stored.size_bytes,
        )
        object.__setattr__(
            capability_copied_source,
            "_verification_capability",
            verified_original_docx._VERIFICATION_CAPABILITY,
        )
        unverified_sources = (
            _ForgedVerifiedOriginalDocxSource(
                object_key=stored.object_key,
                sha256="a" * 64,
                size_bytes=stored.size_bytes,
            ),
            VerifiedOriginalDocxSource(
                object_key=stored.object_key,
                sha256="a" * 64,
                size_bytes=stored.size_bytes,
            ),
            capability_copied_source,
        )

        for unverified_source in unverified_sources:
            with self.subTest(source_type=type(unverified_source).__name__):
                custody_count_before = self.store._connection.execute(
                    "SELECT COUNT(*) FROM strict_docx_v3_document_custody"
                ).fetchone()[0]
                event_count_before = self.store._connection.execute(
                    "SELECT COUNT(*) FROM source_registry_events"
                ).fetchone()[0]

                result = register_verified_original_docx_source(
                    store=self.store,
                    actor=self.owner,
                    source=cast(VerifiedOriginalDocxSource, unverified_source),
                )

                self.assertEqual(
                    result,
                    SourceRegistryDenied("source_registry_source_unverified"),
                )
                self.assertNotIn(stored.object_key, repr(result))
                self.assertEqual(
                    self.store._connection.execute(
                        "SELECT COUNT(*) FROM strict_docx_v3_document_custody"
                    ).fetchone()[0],
                    custody_count_before,
                )
                self.assertEqual(
                    self.store._connection.execute(
                        "SELECT COUNT(*) FROM source_registry_events"
                    ).fetchone()[0],
                    event_count_before,
                )

    def test_registration_denies_unverified_source_before_backend_dispatch(self):
        stored = self._put_original_docx(b"verified source")

        result = register_verified_original_docx_source(
            store=_DispatchFailingStore(),
            actor=self.owner,
            source=cast(
                VerifiedOriginalDocxSource,
                _ForgedVerifiedOriginalDocxSource(
                    object_key=stored.object_key,
                    sha256="a" * 64,
                    size_bytes=stored.size_bytes,
                ),
            ),
        )

        self.assertEqual(
            result,
            SourceRegistryDenied("source_registry_source_unverified"),
        )

    def test_legacy_custody_without_registry_owner_is_not_adopted(self):
        source = self._verified_original_docx(b"verified source")
        self.store._connection.execute(
            """INSERT INTO strict_docx_v3_document_custody (
            document_custody_id, source_object_key, source_sha256,
            source_size_bytes, document_kind, created_at
            ) VALUES (?, ?, ?, ?, 'docx', ?)""",
            (
                "legacy-custody",
                source.object_key,
                source.sha256,
                source.size_bytes,
                "now",
            ),
        )
        self.store._connection.commit()

        result = register_verified_original_docx_source(
            store=self.store,
            actor=self.owner,
            source=source,
        )

        self.assertEqual(
            result,
            SourceRegistryDenied("source_registry_reconciliation_denied"),
        )

    def _put_original_docx(self, content: bytes):
        return self.storage.put_bytes(
            kind=StoredFileKind.ORIGINAL,
            file_name="book.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            content=content,
        )

    def _verified_original_docx(self, content: bytes) -> VerifiedOriginalDocxSource:
        stored = self._put_original_docx(content)
        source = verify_original_docx_source(self.storage, stored.object_key)
        self.assertIsInstance(source, VerifiedOriginalDocxSource)
        assert isinstance(source, VerifiedOriginalDocxSource)
        return source


class _ForgedVerifiedOriginalDocxSource:
    def __init__(self, *, object_key: str, sha256: str, size_bytes: int):
        self.object_key = object_key
        self.sha256 = sha256
        self.size_bytes = size_bytes


class _DispatchFailingStore:
    @property
    def connection(self):
        raise AssertionError("invalid source must be denied before backend dispatch")


class _FakePostgresStore:
    def __init__(self, connection):
        self.connection = connection


class _RecordingPostgresConnection:
    def __init__(self, rows):
        self.params = []
        self.rows = list(rows)
        self.statements = []

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


class _RecordingResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row
