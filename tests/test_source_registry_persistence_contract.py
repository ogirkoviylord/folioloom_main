import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.persistent_jobs import SQLiteTranslationJobStore
from translator_service.postgres_migrations import MIGRATIONS


class SourceRegistryPersistenceContractTest(unittest.TestCase):
    def test_v5_migration_adds_nullable_registry_provenance_and_two_event_audit(self):
        migration = MIGRATIONS[-1]

        self.assertEqual(migration.version, 5)
        self.assertIn(
            "ALTER TABLE strict_docx_v3_document_custody\n"
            "    ADD COLUMN registry_owner_actor_id TEXT NULL",
            migration.sql_payload,
        )
        self.assertIn(
            "ADD COLUMN registry_actor_role TEXT NULL",
            migration.sql_payload,
        )
        self.assertIn(
            "ADD COLUMN registry_authn_schema_version TEXT NULL",
            migration.sql_payload,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS source_registry_events",
            migration.sql_payload,
        )
        self.assertIn("'registered', 'registration_reused'", migration.sql_payload)
        self.assertNotIn("CHECK (registry_actor_role", migration.sql_payload)

    def test_sqlite_initialization_supports_legacy_custody_and_registry_audit(self):
        with TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "jobs.sqlite3"
            store = SQLiteTranslationJobStore(database)
            self.addCleanup(store.close)

            columns = {
                row["name"]: row
                for row in store._connection.execute(
                    "PRAGMA table_info(strict_docx_v3_document_custody)"
                ).fetchall()
            }
            event_sql = store._connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' "
                "AND name = 'source_registry_events'"
            ).fetchone()["sql"]

            self.assertEqual(columns["registry_owner_actor_id"]["notnull"], 0)
            self.assertEqual(columns["registry_actor_role"]["notnull"], 0)
            self.assertEqual(
                columns["registry_authn_schema_version"]["notnull"], 0
            )
            self.assertIn("'registered', 'registration_reused'", event_sql)
            store._connection.execute(
                """INSERT INTO strict_docx_v3_document_custody (
                document_custody_id, source_object_key, source_sha256,
                source_size_bytes, document_kind, created_at
                ) VALUES (?, ?, ?, ?, 'docx', ?)""",
                ("custody-1", "original/registry.docx", "b" * 64, 1, "now"),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                store._connection.execute(
                    """INSERT INTO source_registry_events (
                    registry_event_id, document_custody_id, event_type,
                    registry_owner_actor_id, registry_actor_role,
                    registry_authn_schema_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        "registry-event-1",
                        "custody-1",
                        "invalid",
                        "actor-1",
                        "owner",
                        "v1",
                        "now",
                    ),
                )

    def test_sqlite_opening_legacy_custody_adds_registry_columns_without_adopting_rows(
        self,
    ):
        with TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "jobs.sqlite3"
            legacy_connection = sqlite3.connect(database)
            try:
                legacy_connection.execute(
                    """CREATE TABLE strict_docx_v3_document_custody (
                    document_custody_id TEXT PRIMARY KEY,
                    source_object_key TEXT NOT NULL UNIQUE,
                    source_sha256 TEXT NOT NULL,
                    source_size_bytes INTEGER NOT NULL,
                    document_kind TEXT NOT NULL CHECK (document_kind = 'docx'),
                    created_at TEXT NOT NULL
                    )"""
                )
                legacy_connection.execute(
                    """INSERT INTO strict_docx_v3_document_custody (
                    document_custody_id, source_object_key, source_sha256,
                    source_size_bytes, document_kind, created_at
                    ) VALUES (?, ?, ?, ?, 'docx', ?)""",
                    ("legacy-custody", "original/legacy.docx", "a" * 64, 1, "now"),
                )
                legacy_connection.commit()
            finally:
                legacy_connection.close()

            store = SQLiteTranslationJobStore(database)
            self.addCleanup(store.close)
            columns = {
                row["name"]
                for row in store._connection.execute(
                    "PRAGMA table_info(strict_docx_v3_document_custody)"
                ).fetchall()
            }
            row = store._connection.execute(
                """SELECT registry_owner_actor_id, registry_actor_role,
                registry_authn_schema_version
                FROM strict_docx_v3_document_custody
                WHERE document_custody_id = 'legacy-custody'"""
            ).fetchone()

            self.assertTrue(
                {
                    "registry_owner_actor_id",
                    "registry_actor_role",
                    "registry_authn_schema_version",
                }.issubset(columns)
            )
            self.assertEqual(tuple(row), (None, None, None))
