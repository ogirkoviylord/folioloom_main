import unittest

from translator_service import postgres_migrations
from translator_service.postgres_migrations import (
    MIGRATIONS,
    PostgresMigrationBootstrapError,
    run_postgres_migrations,
)
from translator_service.postgres_scheduler import SCHEMA_SQL


class PostgresMigrationsTest(unittest.TestCase):
    def test_rejects_checksum_mismatch_before_pending_sql(self):
        connection = _RecordingConnection(
            ledger_rows=[{"version": 1, "checksum": "wrong"}],
            baseline_relations=[],
        )

        with self.assertRaisesRegex(PostgresMigrationBootstrapError, "checksum"):
            run_postgres_migrations(connection)

        self.assertFalse(connection.contains(MigrationSql.v1_payload))

    def test_rejects_unknown_or_noncontiguous_ledger_before_pending_sql(self):
        for ledger_rows in (
            [{"version": 2, "checksum": "x"}],
            [
                {"version": 1, "checksum": MIGRATIONS[0].checksum},
                {"version": 3, "checksum": "x"},
            ],
        ):
            with self.subTest(ledger_rows=ledger_rows):
                connection = _RecordingConnection(
                    ledger_rows=ledger_rows,
                    baseline_relations=[],
                )

                with self.assertRaises(PostgresMigrationBootstrapError):
                    run_postgres_migrations(connection)

                self.assertFalse(connection.contains(MigrationSql.v1_payload))

    def test_fresh_database_records_exact_ledger_rows(self):
        connection = _RecordingConnection(ledger_rows=[], baseline_relations=[])

        run_postgres_migrations(connection)

        self.assertTrue(connection.contains("pg_advisory_xact_lock"))
        self.assertIn(
            "translator_service.postgres_migrations.runner.v1",
            str(connection.params),
        )
        self.assertTrue(connection.contains(MigrationSql.v1_payload))
        ledger_inserts = [
            params
            for statement, params in zip(
                connection.statements, connection.params, strict=True
            )
            if "INSERT INTO schema_migrations" in statement
        ]
        self.assertEqual(
            ledger_inserts,
            [
                {"version": 1, "checksum": MIGRATIONS[0].checksum},
                {"version": 2, "checksum": MIGRATIONS[1].checksum},
            ],
        )

    def test_complete_valid_ledger_skips_migration_payloads_and_stamping(self):
        connection = _RecordingConnection(
            ledger_rows=[
                {"version": migration.version, "checksum": migration.checksum}
                for migration in MIGRATIONS
            ],
            baseline_relations=[],
        )

        run_postgres_migrations(connection)

        self.assertTrue(connection.contains("pg_advisory_xact_lock"))
        self.assertTrue(
            connection.contains("CREATE TABLE IF NOT EXISTS schema_migrations")
        )
        self.assertFalse(
            any(connection.contains(migration.sql_payload) for migration in MIGRATIONS)
        )
        self.assertFalse(_ledger_inserts(connection))

    def test_fresh_database_applies_strict_docx_v2_after_scheduler_baseline(self):
        connection = _RecordingConnection(ledger_rows=[], baseline_relations=[])

        run_postgres_migrations(connection)

        if [migration.version for migration in MIGRATIONS] != [1, 2]:
            self.fail("strict DOCX migration v2 is missing")
        self.assertTrue(connection.contains(MigrationSql.v1_payload))
        self.assertTrue(connection.contains(MigrationSql.v2_payload()))
        ledger_inserts = [
            params
            for statement, params in zip(
                connection.statements, connection.params, strict=True
            )
            if "INSERT INTO schema_migrations" in statement
        ]
        self.assertEqual(
            ledger_inserts,
            [
                {"version": 1, "checksum": MIGRATIONS[0].checksum},
                {"version": 2, "checksum": MIGRATIONS[1].checksum},
            ],
        )

    def test_complete_legacy_v1_catalog_stamps_then_applies_v2(self):
        connection = _RecordingConnection(
            ledger_rows=[],
            baseline_relations=_legacy_v1_catalog()["relations"],
            column_rows=_legacy_v1_catalog()["columns"],
            constraint_rows=_legacy_v1_catalog()["constraints"],
            index_rows=_legacy_v1_catalog()["indexes"],
        )

        run_postgres_migrations(connection)

        self.assertFalse(connection.contains(MigrationSql.v1_payload))
        self.assertTrue(connection.contains(MigrationSql.v2_payload()))
        ledger_inserts = [
            params
            for statement, params in zip(
                connection.statements, connection.params, strict=True
            )
            if "INSERT INTO schema_migrations" in statement
        ]
        self.assertEqual(
            ledger_inserts,
            [
                {"version": 1, "checksum": MIGRATIONS[0].checksum},
                {"version": 2, "checksum": MIGRATIONS[1].checksum},
            ],
        )
        v2_sql_index = connection.statements.index(MigrationSql.v2_payload())
        v2_ledger_index = next(
            index
            for index, (statement, params) in enumerate(
                zip(connection.statements, connection.params, strict=True)
            )
            if "INSERT INTO schema_migrations" in statement
            and params["version"] == 2
        )
        self.assertEqual(
            connection.transaction_ids[v2_sql_index],
            connection.transaction_ids[v2_ledger_index],
        )

    def test_partial_legacy_v1_catalog_rejects_without_running_or_stamping_migrations(
        self,
    ):
        connection = _RecordingConnection(
            ledger_rows=[], baseline_relations=[{"relname": "translation_jobs"}]
        )

        with self.assertRaisesRegex(PostgresMigrationBootstrapError, "partial"):
            run_postgres_migrations(connection)

        self.assertFalse(connection.contains(MigrationSql.v1_payload))
        self.assertFalse(connection.contains(MigrationSql.v2_payload()))
        self.assertFalse(_ledger_inserts(connection))

    def test_invalid_complete_legacy_v1_column_manifest_rejects_without_stamping(self):
        catalog = _legacy_v1_catalog()
        catalog["columns"] = [
            row
            for row in catalog["columns"]
            if not (
                row["table_name"] == "translation_jobs"
                and row["column_name"] == "file_id"
            )
        ]
        connection = _RecordingConnection(
            ledger_rows=[],
            baseline_relations=catalog["relations"],
            column_rows=catalog["columns"],
            constraint_rows=catalog["constraints"],
            index_rows=catalog["indexes"],
        )

        with self.assertRaisesRegex(PostgresMigrationBootstrapError, "column manifest"):
            run_postgres_migrations(connection)

        self.assertFalse(connection.contains(MigrationSql.v1_payload))
        self.assertFalse(connection.contains(MigrationSql.v2_payload()))
        self.assertFalse(_ledger_inserts(connection))

    def test_complete_legacy_v1_catalog_rejects_constraint_with_added_clause(self):
        catalog = _legacy_v1_catalog()
        catalog["constraints"] = [
            {
                **row,
                "definition": "CHECK ((slot_index >= 0)) NOT VALID",
            }
            if row["table_name"] == "provider_slots" and row["contype"] == "c"
            else row
            for row in catalog["constraints"]
        ]
        connection = _RecordingConnection(
            ledger_rows=[],
            baseline_relations=catalog["relations"],
            column_rows=catalog["columns"],
            constraint_rows=catalog["constraints"],
            index_rows=catalog["indexes"],
        )

        with self.assertRaisesRegex(
            PostgresMigrationBootstrapError, "constraint manifest"
        ):
            run_postgres_migrations(connection)

        self.assertFalse(connection.contains(MigrationSql.v1_payload))
        self.assertFalse(connection.contains(MigrationSql.v2_payload()))
        self.assertFalse(_ledger_inserts(connection))

    def test_v1_migration_payload_matches_scheduler_source_of_truth(self):
        self.assertEqual(postgres_migrations._V1_SCHEDULER_SQL, SCHEMA_SQL)

    def test_v2_owns_exact_strict_docx_tables_without_extra_index(self):
        if len(MIGRATIONS) != 2:
            self.fail("strict DOCX migration v2 is missing")
        v2_sql = MigrationSql.v2_payload()

        self.assertIn("CREATE TABLE IF NOT EXISTS glossary_snapshot_custody", v2_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS glossary_approvals", v2_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS strict_job_glossary_bindings", v2_sql)
        self.assertIn(
            "UNIQUE(custody_id, snapshot_digest, approval_schema_version)",
            v2_sql,
        )
        self.assertNotIn("CREATE INDEX", v2_sql)

    def test_migration_sql_failure_does_not_record_ledger_row(self):
        connection = _RecordingConnection(
            ledger_rows=[], baseline_relations=[], fail_on=MigrationSql.v1_payload
        )

        with self.assertRaisesRegex(RuntimeError, "migration failed"):
            run_postgres_migrations(connection)

        self.assertFalse(
            any(
                "INSERT INTO schema_migrations" in statement
                for statement in connection.statements
            )
        )


class MigrationSql:
    v1_payload = MIGRATIONS[0].sql_payload

    @staticmethod
    def v2_payload() -> str:
        return MIGRATIONS[1].sql_payload


class _RecordingConnection:
    def __init__(
        self,
        *,
        ledger_rows,
        baseline_relations,
        column_rows=None,
        constraint_rows=None,
        index_rows=None,
        fail_on=None,
    ):
        self.ledger_rows = ledger_rows
        self.baseline_relations = baseline_relations
        self.column_rows = column_rows or []
        self.constraint_rows = constraint_rows or []
        self.index_rows = index_rows or []
        self.fail_on = fail_on
        self.statements = []
        self.params = []
        self.transaction_ids = []
        self._active_transaction_id = None
        self._next_transaction_id = 0

    def transaction(self):
        return _Transaction(self)

    def execute(self, statement, params=None):
        self.statements.append(statement)
        self.params.append(params)
        self.transaction_ids.append(self._active_transaction_id)
        if self.fail_on == statement:
            raise RuntimeError("migration failed")
        if "INSERT INTO schema_migrations" in statement:
            self.ledger_rows.append(dict(params))
        if "SELECT version, checksum" in statement:
            return _Cursor(self.ledger_rows)
        if "FROM pg_catalog.pg_class relation" in statement:
            return _Cursor(self.baseline_relations)
        if "FROM pg_catalog.pg_attribute attribute" in statement:
            return _Cursor(self.column_rows)
        if "FROM pg_catalog.pg_constraint constraint_item" in statement:
            return _Cursor(self.constraint_rows)
        if "FROM pg_catalog.pg_index index_item" in statement:
            return _Cursor(self.index_rows)
        return _Cursor([])

    def contains(self, statement):
        return any(statement in recorded for recorded in self.statements)


class _Transaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection._next_transaction_id += 1
        self.connection._active_transaction_id = self.connection._next_transaction_id
        return self

    def __exit__(self, exc_type, exc, tb):
        self.connection._active_transaction_id = None
        return None


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


def _ledger_inserts(connection):
    return [
        params
        for statement, params in zip(
            connection.statements, connection.params, strict=True
        )
        if "INSERT INTO schema_migrations" in statement
    ]


def _legacy_v1_catalog():
    return {
        "relations": [
            {"relname": relation_name}
            for relation_name in postgres_migrations._BASELINE_RELATIONS
        ],
        "columns": [
            {
                "table_name": table_name,
                "column_name": column_name,
                "type_name": type_name,
                "not_null": not_null,
                "default_expr": default_expr,
            }
            for table_name, columns in postgres_migrations._COLUMN_MANIFEST.items()
            for column_name, type_name, not_null, default_expr in columns
        ],
        "constraints": [
            {
                "table_name": table_name,
                "contype": constraint_type,
                "definition": definition,
            }
            for table_name, constraint_type, definition in _LEGACY_V1_CONSTRAINTS
        ],
        "indexes": [
            {
                "index_name": "provider_slot_leases_active_slot_idx",
                "table_name": "provider_slot_leases",
                "definition": (
                    "CREATE UNIQUE INDEX provider_slot_leases_active_slot_idx "
                    "ON provider_slot_leases USING btree "
                    "(provider_id, channel_id, slot_index) "
                    "WHERE (status = 'active'::text)"
                ),
            },
            {
                "index_name": "provider_slot_leases_active_work_unit_idx",
                "table_name": "provider_slot_leases",
                "definition": (
                    "CREATE UNIQUE INDEX provider_slot_leases_active_work_unit_idx "
                    "ON provider_slot_leases USING btree (work_unit_id) "
                    "WHERE (status = 'active'::text)"
                ),
            },
        ],
    }


_LEGACY_V1_CONSTRAINTS = (
    ("translation_jobs", "p", "PRIMARY KEY (id)"),
    ("work_units", "p", "PRIMARY KEY (id)"),
    ("work_units", "u", "UNIQUE (job_id, sequence)"),
    ("work_unit_attempts", "p", "PRIMARY KEY (id)"),
    ("scheduler_events", "p", "PRIMARY KEY (id)"),
    ("worker_heartbeats", "p", "PRIMARY KEY (worker_id)"),
    ("provider_slots", "p", "PRIMARY KEY (provider_id, channel_id, slot_index)"),
    ("provider_slots", "c", "CHECK ((slot_index >= 0))"),
    ("provider_slot_leases", "p", "PRIMARY KEY (id)"),
    ("provider_slot_leases", "u", "UNIQUE (lease_token)"),
    (
        "provider_slot_leases",
        "c",
        (
            "CHECK ((status = ANY (ARRAY['active'::text, 'released'::text, "
            "'expired'::text])))"
        ),
    ),
    ("work_units", "f", "FOREIGN KEY (job_id) REFERENCES translation_jobs(id)"),
    (
        "work_unit_attempts",
        "f",
        "FOREIGN KEY (work_unit_id) REFERENCES work_units(id)",
    ),
    (
        "work_unit_attempts",
        "f",
        "FOREIGN KEY (job_id) REFERENCES translation_jobs(id)",
    ),
    (
        "scheduler_events",
        "f",
        "FOREIGN KEY (job_id) REFERENCES translation_jobs(id)",
    ),
    (
        "provider_slot_leases",
        "f",
        "FOREIGN KEY (job_id) REFERENCES translation_jobs(id)",
    ),
    (
        "provider_slot_leases",
        "f",
        "FOREIGN KEY (work_unit_id) REFERENCES work_units(id)",
    ),
    (
        "provider_slot_leases",
        "f",
        (
            "FOREIGN KEY (provider_id, channel_id, slot_index) "
            "REFERENCES provider_slots(provider_id, channel_id, slot_index)"
        ),
    ),
)


if __name__ == "__main__":
    unittest.main()
