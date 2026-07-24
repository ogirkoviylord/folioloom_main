import json
import os
import threading
import unittest
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from types import SimpleNamespace

from psycopg.errors import CheckViolation, UniqueViolation

from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.format_adapters import TXT_ADAPTER_VERSION
from translator_service.persistent_jobs import (
    GLOSSARY_APPROVAL_SCHEMA_VERSION,
    GLOSSARY_BINDING_SCHEMA_VERSION,
    GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
    DeleteJobResult,
    PersistentTranslationJobStatus,
    PersistentWorkUnitStatus,
    StrictDocxAdmissionRequest,
    WorkUnitPlan,
)
from translator_service.postgres_migrations import MIGRATIONS, run_postgres_migrations
from translator_service.postgres_scheduler import (
    _CLAIM_NEXT_SCHEDULED_WORK_UNIT_SQL,
    SCHEMA_SQL,
    PostgresSchedulerStore,
    create_postgres_scheduler_claim_performance_indexes,
    postgres_scheduler_claim_performance_index_statements,
)
from translator_service.provider_failure_diagnostics import (
    ProviderFailureCategory,
    ProviderFailureDiagnostic,
)
from translator_service.scheduler import (
    SCHEDULER_FAIR_QUEUE_POLICY,
    ProviderCapacityCap,
    ProviderCapacityCapScope,
    ProviderCapacitySlotDiagnosticStatus,
    ProviderSlotInventoryItem,
    ProviderSlotLeaseStatus,
    SchedulerBackpressureState,
    SchedulerLimits,
    WorkUnitFailureKind,
)

POSTGRES_DSN = os.getenv("TEST_POSTGRES_DSN")


class PostgresSchedulerContractTest(unittest.TestCase):
    def test_strict_snapshot_reader_revalidates_all_binding_predicates(self):
        payload = b"postgres-reader-snapshot"
        valid_row = _strict_snapshot_reader_row(payload=payload)
        invalidations = (
            ("approval_not_approved", {"approval_status": "revoked"}),
            ("approval_unrecognized_status", {"approval_status": "pending"}),
            ("approval_custody_mismatch", {"custody_id": "other-custody"}),
            ("binding_approval_mismatch", {"binding_approval_id": "other-approval"}),
            ("binding_custody_mismatch", {"binding_custody_id": "other-custody"}),
            ("binding_digest_mismatch", {"binding_snapshot_digest": "other-digest"}),
            ("approval_digest_mismatch", {"snapshot_digest": "other-digest"}),
            ("custody_digest_mismatch", {"custody_snapshot_digest": "other-digest"}),
            (
                "unsupported_binding_schema",
                {"binding_schema_version": GLOSSARY_BINDING_SCHEMA_VERSION + 1},
            ),
            (
                "unsupported_approval_schema",
                {"approval_schema_version": GLOSSARY_APPROVAL_SCHEMA_VERSION + 1},
            ),
            (
                "unsupported_snapshot_schema",
                {"snapshot_schema_version": GLOSSARY_SNAPSHOT_SCHEMA_VERSION + 1},
            ),
            ("non_retain_custody", {"retention_mode": "discard"}),
            ("non_docx_job", {"document_kind": "txt"}),
            ("payload_digest_mismatch", {"snapshot_payload": b"tampered"}),
        )

        for name, overrides in invalidations:
            with self.subTest(invalidation=name):
                store = object.__new__(PostgresSchedulerStore)
                store.connection = _RecordingPostgresConnection(
                    rows=[{**valid_row, **overrides}]
                )

                snapshot = store.read_strict_job_glossary_snapshot(job_id="job-1")

                self.assertIsNone(snapshot)
                self.assertEqual(len(store.connection.statements), 1)
                self.assertEqual(store.connection.params, [{"job_id": "job-1"}])

    def test_strict_snapshot_reader_returns_exact_valid_approval_and_payload(self):
        payload = b"postgres-reader-snapshot"
        store = object.__new__(PostgresSchedulerStore)
        store.connection = _RecordingPostgresConnection(
            rows=[_strict_snapshot_reader_row(payload=payload)]
        )

        snapshot = store.read_strict_job_glossary_snapshot(job_id="job-1")

        self.assertIsNotNone(snapshot)
        if snapshot is None:
            self.fail("valid strict snapshot unexpectedly unavailable")
        self.assertEqual(snapshot.snapshot_payload, payload)
        self.assertEqual(snapshot.approval.approval_id, "approval-1")
        self.assertEqual(snapshot.approval.custody_id, "custody-1")
        self.assertEqual(snapshot.approval.snapshot_digest, sha256(payload).hexdigest())
        self.assertEqual(snapshot.approval.approval_status, "approved")

    def test_approved_snapshot_reader_rejects_rehashed_tampered_payload(self):
        tampered_payload = b"postgres-tampered-snapshot"
        synchronized_digest = sha256(b"claimed-snapshot").hexdigest()
        store = object.__new__(PostgresSchedulerStore)
        store.connection = _RecordingPostgresConnection(
            rows=[
                {
                    **_strict_snapshot_reader_row(payload=b"original-snapshot"),
                    "snapshot_payload": tampered_payload,
                    "snapshot_digest": synchronized_digest,
                    "custody_snapshot_digest": synchronized_digest,
                }
            ]
        )

        snapshot = store.read_approved_glossary_snapshot(approval_id="approval-1")

        self.assertIsNone(snapshot)
        self.assertEqual(len(store.connection.statements), 1)
        self.assertEqual(store.connection.params, [{"approval_id": "approval-1"}])

    def test_strict_docx_admission_denials_are_typed_and_do_not_insert(self):
        cases = (
            (
                "document_kind_not_docx",
                _strict_docx_request(document_kind="txt"),
                [],
            ),
            (
                "approval_missing",
                _strict_docx_request(),
                [None],
            ),
            (
                "approval_revoked",
                _strict_docx_request(),
                [_strict_approval_row(approval_status="revoked")],
            ),
            (
                "approval_binding_mismatch",
                _strict_docx_request(),
                [_strict_approval_row(custody_snapshot_digest="other-digest")],
            ),
        )

        for expected_denial, request, rows in cases:
            with self.subTest(denial_code=expected_denial):
                store = object.__new__(PostgresSchedulerStore)
                store.connection = _RecordingPostgresConnection(rows=rows)

                result = store.admit_strict_docx_job(request)

                self.assertFalse(result.admitted)
                self.assertEqual(result.denial_code, expected_denial)
                self.assertEqual(result.work_units, [])
                self.assertFalse(
                    any(
                        statement.lstrip().upper().startswith("INSERT")
                        for statement in store.connection.statements
                    )
                )
                if expected_denial in {"document_kind_not_docx", "invalid_request"}:
                    self.assertEqual(store.connection.statements, [])
                else:
                    self.assertEqual(len(store.connection.statements), 1)

    def test_store_exposes_strict_docx_methods_and_baseline_schema_excludes_v2(self):
        expected_methods = [
            "create_glossary_approval",
            "revoke_glossary_approval",
            "read_approved_glossary_snapshot",
            "read_strict_job_glossary_snapshot",
            "admit_strict_docx_job",
            "claim_next_work_unit",
        ]

        for method_name in expected_methods:
            self.assertTrue(
                callable(getattr(PostgresSchedulerStore, method_name, None)),
                method_name,
            )

        self.assertNotIn("glossary_snapshot_custody", SCHEMA_SQL)
        self.assertNotIn("glossary_approvals", SCHEMA_SQL)
        self.assertNotIn("strict_job_glossary_bindings", SCHEMA_SQL)
        strict_migration_sql = MIGRATIONS[1].sql_payload
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS glossary_snapshot_custody",
            strict_migration_sql,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS glossary_approvals", strict_migration_sql
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS strict_job_glossary_bindings",
            strict_migration_sql,
        )
        self.assertIn("CHECK (retention_mode = 'retain')", strict_migration_sql)
        self.assertIn(
            "CHECK (approval_status IN ('approved', 'revoked'))", strict_migration_sql
        )
        self.assertIn(
            "UNIQUE(custody_id, snapshot_digest, approval_schema_version)",
            strict_migration_sql,
        )

    def test_delete_job_checks_locked_job_and_strict_binding_inside_transaction(
        self,
    ):
        store = object.__new__(PostgresSchedulerStore)
        store.connection = _RecordingPostgresConnection(
            rows=[{"id": "job-1"}, {"exists": 1}]
        )

        result = store.delete_job("job-1")

        self.assertIsInstance(result, DeleteJobResult)
        self.assertFalse(result.deleted)
        self.assertEqual(result.denial_code, "strict_job_non_deletable")
        self.assertEqual(len(store.connection.statements), 2)
        self.assertIn("FROM translation_jobs", store.connection.statements[0])
        self.assertIn("FOR UPDATE", store.connection.statements[0])
        self.assertIn(
            "FROM strict_job_glossary_bindings",
            store.connection.statements[1],
        )
        self.assertEqual(store.connection.transaction_depths, [1, 1])
        self.assertFalse(
            any(
                statement.lstrip().upper().startswith("DELETE")
                for statement in store.connection.statements
            )
        )

    def test_delete_job_returns_typed_result_for_missing_and_regular_jobs(self):
        missing_store = object.__new__(PostgresSchedulerStore)
        missing_store.connection = _RecordingPostgresConnection(rows=[None])

        missing_result = missing_store.delete_job("missing-job")

        self.assertIsInstance(missing_result, DeleteJobResult)
        self.assertFalse(missing_result.deleted)
        self.assertIsNone(missing_result.denial_code)
        self.assertEqual(len(missing_store.connection.statements), 1)
        self.assertIn("FOR UPDATE", missing_store.connection.statements[0])
        self.assertEqual(missing_store.connection.transaction_depths, [1])

        store = object.__new__(PostgresSchedulerStore)
        store.connection = _RecordingPostgresConnection(rows=[{"id": "job-1"}, None])

        result = store.delete_job("job-1")

        self.assertIsInstance(result, DeleteJobResult)
        self.assertTrue(result.deleted)
        self.assertIsNone(result.denial_code)
        self.assertEqual(len(store.connection.statements), 7)
        self.assertIn("FOR UPDATE", store.connection.statements[0])
        self.assertIn(
            "FROM strict_job_glossary_bindings", store.connection.statements[1]
        )
        delete_indexes = [
            index
            for index, statement in enumerate(store.connection.statements)
            if statement.lstrip().upper().startswith("DELETE")
        ]
        self.assertEqual(delete_indexes, [2, 3, 4, 5, 6])
        self.assertEqual(store.connection.transaction_depths, [1] * 7)
        self.assertIn("DELETE FROM translation_jobs", store.connection.statements[-1])

    def test_scheduled_claim_guards_strict_docx_binding_with_null_safe_predicates(self):
        claim_sql = _CLAIM_NEXT_SCHEDULED_WORK_UNIT_SQL
        self.assertIn("strict_job_glossary_bindings binding", claim_sql)
        self.assertEqual(claim_sql.count("strict_job_glossary_bindings binding"), 2)
        self.assertIn("approval.approval_status IS DISTINCT FROM 'approved'", claim_sql)
        self.assertIn(
            "approval.custody_id IS DISTINCT FROM binding.custody_id", claim_sql
        )
        self.assertIn(
            "custody.snapshot_digest IS DISTINCT FROM binding.snapshot_digest",
            claim_sql,
        )

    def test_direct_claim_and_revoke_use_the_scheduler_serialization_lock(self):
        store = object.__new__(PostgresSchedulerStore)
        store.connection = _RecordingPostgresConnection(
            rows=[None, None, None, _strict_approval_row()]
        )

        self.assertIsNone(store.claim_next_work_unit("job-1", worker_id="worker-a"))
        store.revoke_glossary_approval(approval_id="approval-1")

        lock_params = [
            params
            for statement, params in zip(
                store.connection.statements, store.connection.params, strict=True
            )
            if "pg_advisory_xact_lock" in statement
        ]
        self.assertEqual(
            lock_params,
            [
                {"claim_lock_key": "translator_service.postgres_scheduler.claim"},
                {"claim_lock_key": "translator_service.postgres_scheduler.claim"},
            ],
        )

    def test_exact_approval_reuse_is_conflict_safe(self):
        store = object.__new__(PostgresSchedulerStore)
        approval = _strict_approval_row()
        store.connection = _RecordingPostgresConnection(
            rows=[{"custody_id": "custody-1"}, approval]
        )

        stored = store.create_glossary_approval(
            snapshot_payload=b"snapshot",
            snapshot_digest=sha256(b"snapshot").hexdigest(),
            snapshot_schema_version=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
            approval_schema_version=GLOSSARY_APPROVAL_SCHEMA_VERSION,
        )

        self.assertEqual(stored.approval_id, "approval-1")
        self.assertIn(
            "ON CONFLICT (custody_id, snapshot_digest, approval_schema_version)",
            store.connection.statements[1],
        )

    def test_store_exposes_scheduler_runtime_methods(self):
        expected_methods = [
            "complete_claimed_work_unit",
            "fail_claimed_work_unit",
            "defer_claimed_work_unit_for_provider_capacity",
            "attach_job_output",
            "list_jobs_by_status",
            "list_jobs_for_user",
            "cancel_job",
            "request_cancel_job",
            "resume_job",
            "delete_job",
            "mark_job_interrupted",
            "get_usage_summary",
            "mark_job_assembled",
            "list_work_unit_attempts",
            "list_scheduler_events",
            "record_worker_heartbeat",
            "get_worker_heartbeat",
            "recover_expired_leases",
            "upsert_provider_slot_inventory",
            "list_provider_slots",
            "acquire_provider_slot_lease",
            "release_provider_slot_lease",
            "recover_expired_provider_slot_leases",
            "list_provider_slot_leases",
            "get_provider_capacity_diagnostics",
            "get_scheduler_backpressure_diagnostics",
        ]

        for method_name in expected_methods:
            self.assertTrue(
                callable(getattr(PostgresSchedulerStore, method_name, None)),
                method_name,
            )

    def test_cancel_job_uses_claim_lock_and_durable_cancel_marker(self):
        store = object.__new__(PostgresSchedulerStore)
        store.connection = _RecordingPostgresConnection()
        store._require_job = lambda job_id: SimpleNamespace(id=job_id)

        store.cancel_job("job-1")

        executed_sql = "\n".join(store.connection.statements)
        self.assertIn(
            "pg_advisory_xact_lock",
            executed_sql,
        )
        self.assertIn(
            "translator_service.postgres_scheduler.claim",
            str(store.connection.params),
        )
        self.assertIn(
            "cancel_requested_at",
            executed_sql,
        )

    def test_request_cancel_job_uses_claim_lock_and_cancel_requested_status(self):
        store = object.__new__(PostgresSchedulerStore)
        store.connection = _RecordingPostgresConnection()
        store._require_job = lambda job_id: SimpleNamespace(
            id=job_id,
            status=PersistentTranslationJobStatus.CANCEL_REQUESTED,
        )
        store._job_has_active_work = lambda job_id: True

        store.request_cancel_job("job-1")

        executed_sql = "\n".join(store.connection.statements)
        self.assertIn("pg_advisory_xact_lock", executed_sql)
        self.assertIn("cancel_requested_at", executed_sql)
        self.assertIn(
            PersistentTranslationJobStatus.CANCEL_REQUESTED.value,
            str(store.connection.params),
        )

    def test_cancel_requested_idle_job_is_finalized_as_cancelled(self):
        store = object.__new__(PostgresSchedulerStore)
        store.connection = _RecordingPostgresConnection()
        store._require_job = lambda job_id: SimpleNamespace(
            id=job_id,
            status=PersistentTranslationJobStatus.CANCEL_REQUESTED,
        )
        store._job_has_active_work = lambda job_id: False

        finalized = store._finalize_cancel_requested_job_if_idle(
            "job-1",
            now=datetime.now(UTC),
        )

        self.assertTrue(finalized)
        self.assertIn(
            PersistentTranslationJobStatus.CANCELLED.value,
            str(store.connection.params),
        )

    def test_claim_final_job_update_cannot_revive_cancelled_job(self):
        store = object.__new__(PostgresSchedulerStore)
        store.connection = _RecordingPostgresConnection(
            rows=[
                {
                    "job_id": "job-1",
                    "id": "job-1:unit-1",
                    "lease_until": datetime.now(UTC),
                    "attempt_count": 1,
                    "source_object_key": "intermediate/job-1/unit-1.txt",
                    "queue_policy_active_user_units": 0,
                    "queue_policy_active_user_jobs": 0,
                    "queue_policy_active_job_units": 0,
                }
            ]
        )

        claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        self.assertIsNotNone(claim)
        final_update_sql = store.connection.statements[1]

        self.assertIn("status IN ('queued', 'translating')", final_update_sql)
        self.assertIn("cancel_requested_at IS NULL", final_update_sql)

    def test_claim_query_precomputes_active_counts_once(self):
        claim_sql = _CLAIM_NEXT_SCHEDULED_WORK_UNIT_SQL

        self.assertIn("active_work AS", claim_sql)
        self.assertIn("active_by_user AS", claim_sql)
        self.assertIn("active_global AS", claim_sql)
        self.assertIn("JOIN LATERAL", claim_sql)
        self.assertIn("first_waiting_work_units AS", claim_sql)
        self.assertEqual(claim_sql.count("JOIN work_units active"), 1)
        self.assertEqual(claim_sql.count("JOIN LATERAL"), 1)
        self.assertNotIn("FROM work_units earlier", claim_sql)
        self.assertNotIn("COUNT(DISTINCT active.job_id)", claim_sql)

    def test_claim_performance_indexes_are_separate_from_startup_schema(self):
        index_sql = "\n".join(
            postgres_scheduler_claim_performance_index_statements(),
        )

        self.assertNotIn("translation_jobs_scheduler_claim_idx", SCHEMA_SQL)
        self.assertNotIn("work_units_scheduler_waiting_order_idx", SCHEMA_SQL)
        self.assertNotIn("work_units_scheduler_active_job_idx", SCHEMA_SQL)
        self.assertIn("CREATE INDEX CONCURRENTLY IF NOT EXISTS", index_sql)
        self.assertIn("translation_jobs_scheduler_claim_idx", index_sql)
        self.assertIn("work_units_scheduler_waiting_order_idx", index_sql)
        self.assertIn("work_units_scheduler_active_job_idx", index_sql)
        self.assertIn(
            "WHERE status IN ('pending', 'failed', 'failed_retryable')",
            index_sql,
        )
        self.assertIn("WHERE status = 'translating'", index_sql)

    def test_resume_job_clears_durable_cancel_marker(self):
        store = object.__new__(PostgresSchedulerStore)
        store.connection = _RecordingPostgresConnection()
        store._require_job = lambda job_id: SimpleNamespace(
            id=job_id,
            status=PersistentTranslationJobStatus.CANCELLED,
        )

        store.resume_job("job-1")

        executed_sql = "\n".join(store.connection.statements)
        self.assertIn("cancel_requested_at = NULL", executed_sql)
        self.assertIn("partial_object_key = NULL", executed_sql)
        self.assertIn("%(failed_terminal)s", executed_sql)
        self.assertIn("failed_terminal", str(store.connection.params))


class _RecordingPostgresConnection:
    def __init__(self, *, rows: Sequence[object] | None = None) -> None:
        self.statements: list[str] = []
        self.params: list[object] = []
        self.transaction_depths: list[int] = []
        self._transaction_depth = 0
        self.rows = list(rows or [])

    def transaction(self):
        return self

    def __enter__(self):
        self._transaction_depth += 1
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._transaction_depth -= 1
        return None

    def execute(self, statement: str, params=None):
        self.statements.append(statement)
        self.params.append(params)
        self.transaction_depths.append(self._transaction_depth)
        return _FakeCursor(self.rows.pop(0) if self.rows else None)


class _FakeCursor:
    def __init__(self, row=None) -> None:
        self.row = row

    def fetchone(self):
        return self.row


def _strict_docx_request(
    *, approval_id: str = "approval-1", document_kind: str = "docx"
) -> StrictDocxAdmissionRequest:
    return StrictDocxAdmissionRequest(
        approval_id=approval_id,
        order_id="strict-order",
        user_id="strict-user",
        file_id="strict.docx",
        file_name="strict.docx",
        document_kind=document_kind,
        source_object_key="original/strict.docx",
        source_language="en",
        target_language="uk",
        adapter_version="docx-v1",
        prompt_version="plain-v1",
        pricing_snapshot_id="pricing-1",
        translation_policy=None,
        work_units=[
            WorkUnitPlan(
                sequence=1,
                source_block_ids=("docx:1",),
                source_text_hash="hash-1",
                prompt_tier="plain",
                source_language="en",
                target_language="uk",
                source_object_key="original/strict.docx",
            )
        ],
    )


def _strict_approval_row(
    *,
    approval_status: str = "approved",
    custody_snapshot_digest: str = "snapshot-digest",
) -> dict[str, object]:
    return {
        "approval_id": "approval-1",
        "custody_id": "custody-1",
        "snapshot_digest": "snapshot-digest",
        "snapshot_schema_version": GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
        "approval_schema_version": GLOSSARY_APPROVAL_SCHEMA_VERSION,
        "approval_status": approval_status,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "revoked_at": None,
        "custody_snapshot_digest": custody_snapshot_digest,
        "retention_mode": "retain",
    }


def _strict_snapshot_reader_row(*, payload: bytes) -> dict[str, object]:
    digest = sha256(payload).hexdigest()
    return {
        "binding_approval_id": "approval-1",
        "binding_custody_id": "custody-1",
        "binding_snapshot_digest": digest,
        "binding_schema_version": GLOSSARY_BINDING_SCHEMA_VERSION,
        "approval_id": "approval-1",
        "custody_id": "custody-1",
        "snapshot_digest": digest,
        "approval_schema_version": GLOSSARY_APPROVAL_SCHEMA_VERSION,
        "approval_status": "approved",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "revoked_at": None,
        "snapshot_payload": payload,
        "snapshot_schema_version": GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
        "retention_mode": "retain",
        "custody_snapshot_digest": digest,
        "document_kind": "docx",
    }


@unittest.skipUnless(POSTGRES_DSN, "TEST_POSTGRES_DSN is not set")
class PostgresSchedulerStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = PostgresSchedulerStore(POSTGRES_DSN)
        run_postgres_migrations(self.store.connection)
        self.store.clear_for_tests()

    def tearDown(self):
        self.store.close()

    def test_strict_docx_admission_reuses_exact_approval_and_revocation_blocks_claim(
        self,
    ):
        payload = b"postgres-strict-snapshot"
        approval = self.store.create_glossary_approval(
            snapshot_payload=payload,
            snapshot_digest=sha256(payload).hexdigest(),
            snapshot_schema_version=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
            approval_schema_version=GLOSSARY_APPROVAL_SCHEMA_VERSION,
        )
        request = StrictDocxAdmissionRequest(
            approval_id=approval.approval_id,
            order_id="strict-order",
            user_id="strict-user",
            file_id="strict.docx",
            file_name="strict.docx",
            document_kind="docx",
            source_object_key="original/strict.docx",
            source_language="en",
            target_language="uk",
            adapter_version="docx-v1",
            prompt_version="plain-v1",
            pricing_snapshot_id="pricing-1",
            translation_policy=None,
            work_units=[
                WorkUnitPlan(
                    sequence=1,
                    source_block_ids=("docx:1",),
                    source_text_hash="hash-1",
                    prompt_tier="plain",
                    source_language="en",
                    target_language="uk",
                    source_object_key="original/strict.docx",
                )
            ],
        )

        first = self.store.admit_strict_docx_job(request)
        second = self.store.admit_strict_docx_job(request)
        self.assertTrue(first.admitted)
        self.assertTrue(second.admitted)
        if first.job is None:
            self.fail("first strict admission unexpectedly denied")
        snapshot = self.store.read_strict_job_glossary_snapshot(job_id=first.job.id)
        self.assertIsNotNone(snapshot)
        if snapshot is None:
            self.fail("strict snapshot unexpectedly unavailable")
        self.assertEqual(snapshot.snapshot_payload, payload)
        self.assertEqual(
            self.store.connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM strict_job_glossary_bindings
                WHERE approval_id = %(approval_id)s
                """,
                {"approval_id": approval.approval_id},
            ).fetchone()["count"],
            2,
        )

        self.store.revoke_glossary_approval(approval_id=approval.approval_id)
        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=60,
            limits=SchedulerLimits(),
        )

        self.assertIsNone(claim)
        self.assertIsNone(
            self.store.read_strict_job_glossary_snapshot(job_id=first.job.id)
        )
        work_unit = self.store.list_work_units(first.job.id)[0]
        self.assertEqual(work_unit.status, PersistentWorkUnitStatus.PENDING)
        self.assertIsNone(work_unit.claim_token)

    def test_real_postgres_reuses_exact_snapshot_approval(self):
        payload = b"postgres-exact-approval-reuse"
        first = self.store.create_glossary_approval(
            snapshot_payload=payload,
            snapshot_digest=sha256(payload).hexdigest(),
            snapshot_schema_version=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
            approval_schema_version=GLOSSARY_APPROVAL_SCHEMA_VERSION,
        )
        second = self.store.create_glossary_approval(
            snapshot_payload=payload,
            snapshot_digest=sha256(payload).hexdigest(),
            snapshot_schema_version=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
            approval_schema_version=GLOSSARY_APPROVAL_SCHEMA_VERSION,
        )

        self.assertEqual(second.approval_id, first.approval_id)
        self.assertEqual(second.custody_id, first.custody_id)
        self.assertEqual(second.snapshot_digest, first.snapshot_digest)

    def test_two_connections_serialize_revoke_against_both_strict_claim_paths(self):
        assert POSTGRES_DSN is not None
        for claim_path in ("direct", "scheduled"):
            with self.subTest(claim_path=claim_path):
                payload = f"postgres-strict-race-{claim_path}".encode()
                approval = self.store.create_glossary_approval(
                    snapshot_payload=payload,
                    snapshot_digest=sha256(payload).hexdigest(),
                    snapshot_schema_version=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
                    approval_schema_version=GLOSSARY_APPROVAL_SCHEMA_VERSION,
                )
                admitted = self.store.admit_strict_docx_job(
                    _strict_docx_request(approval_id=approval.approval_id)
                )
                self.assertTrue(admitted.admitted)
                if admitted.job is None:
                    raise AssertionError("strict job admission unexpectedly denied")
                job_id = admitted.job.id
                other_store = PostgresSchedulerStore(POSTGRES_DSN)
                self.addCleanup(other_store.close)
                barrier = threading.Barrier(2)

                def revoke(
                    *,
                    release_barrier=barrier,
                    release_approval_id=approval.approval_id,
                ):
                    release_barrier.wait(timeout=5)
                    return (
                        self.store.revoke_glossary_approval(
                            approval_id=release_approval_id
                        ),
                        monotonic(),
                    )

                def claim(
                    *,
                    claim_barrier=barrier,
                    path=claim_path,
                    store=other_store,
                    strict_job_id=job_id,
                ):
                    claim_barrier.wait(timeout=5)
                    if path == "direct":
                        result = store.claim_next_work_unit(
                            strict_job_id,
                            worker_id="worker-race",
                        )
                    else:
                        result = store.claim_next_scheduled_work_unit(
                            worker_id="worker-race",
                            lease_seconds=60,
                            limits=SchedulerLimits(),
                        )
                    return result, monotonic()

                with ThreadPoolExecutor(max_workers=2) as executor:
                    revoke_future = executor.submit(revoke)
                    claim_future = executor.submit(claim)
                    _, revoke_finished = revoke_future.result(timeout=10)
                    claimed, claim_finished = claim_future.result(timeout=10)

                if revoke_finished < claim_finished:
                    self.assertIsNone(claimed)
                elif claimed is not None:
                    self.assertLess(claim_finished, revoke_finished)
                self.assertIsNone(
                    self.store.read_strict_job_glossary_snapshot(job_id=job_id)
                )

    def _create_txt_job_with_unit(
        self,
        *,
        order_id="order-1",
        file_id="file-1",
        user_id="telegram:42",
    ):
        job = self.store.create_job(
            order_id=order_id,
            user_id=user_id,
            file_id=file_id,
            file_name="notes.txt",
            document_kind="txt",
            source_language="en",
            target_language="uk",
            adapter_version=TXT_ADAPTER_VERSION,
            prompt_version="plain-v1",
            pricing_snapshot_id="pricing-1",
            source_object_key="intermediate/job-1/unit-1.txt",
        )
        self.store.add_work_units(
            job.id,
            [
                WorkUnitPlan(
                    sequence=1,
                    source_block_ids=("txt:0",),
                    source_text_hash="hash-1",
                    prompt_tier="plain",
                    source_language="en",
                    target_language="uk",
                    source_object_key="intermediate/job-1/unit-1.txt",
                )
            ],
        )
        return job

    def _admit_strict_docx_job(self):
        payload = b"postgres-delete-guard-snapshot"
        approval = self.store.create_glossary_approval(
            snapshot_payload=payload,
            snapshot_digest=sha256(payload).hexdigest(),
            snapshot_schema_version=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
            approval_schema_version=GLOSSARY_APPROVAL_SCHEMA_VERSION,
        )
        admitted = self.store.admit_strict_docx_job(
            StrictDocxAdmissionRequest(
                approval_id=approval.approval_id,
                order_id="strict-delete-order",
                user_id="strict-delete-user",
                file_id="strict-delete.docx",
                file_name="strict-delete.docx",
                document_kind="docx",
                source_object_key="original/strict-delete.docx",
                source_language="en",
                target_language="uk",
                adapter_version="docx-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                translation_policy=None,
                work_units=[
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("docx:1",),
                        source_text_hash="strict-delete-hash",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key="original/strict-delete.docx",
                    )
                ],
            )
        )
        self.assertTrue(admitted.admitted)
        if admitted.job is None:
            self.fail("strict job admission unexpectedly denied")
        return admitted.job

    def test_delete_job_real_postgres_preserves_strict_dependents_and_removes_regular(
        self,
    ):
        missing = self.store.delete_job("missing-job")
        self.assertIsInstance(missing, DeleteJobResult)
        self.assertFalse(missing.deleted)

        strict_job = self._admit_strict_docx_job()
        strict_claim = self.store.claim_next_scheduled_work_unit(
            worker_id="strict-delete-worker",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )
        self.assertIsNotNone(strict_claim)
        if strict_claim is None:
            self.fail("strict job was not claimable")
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_strictdelete1",
            max_parallel_requests=1,
            capacity_source="test",
        )
        self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            channel_id="chan_strictdelete1",
            job_id=strict_claim.job_id,
            work_unit_id=strict_claim.work_unit_id,
            worker_id=strict_claim.worker_id,
            work_unit_claim_token=strict_claim.claim_token,
            lease_seconds=300,
        )
        self.store.fail_claimed_work_unit(
            work_unit_id=strict_claim.work_unit_id,
            claim_token=strict_claim.claim_token,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message="synthetic strict deletion guard failure",
            retry_base_delay_seconds=30,
            retry_max_delay_seconds=600,
        )
        strict_counts_before = self._job_dependent_counts(strict_job.id)

        strict = self.store.delete_job(strict_job.id)

        self.assertIsInstance(strict, DeleteJobResult)
        self.assertFalse(strict.deleted)
        self.assertEqual(strict.denial_code, "strict_job_non_deletable")
        self.assertIsNotNone(self.store.get_job(strict_job.id))
        self.assertEqual(
            strict_counts_before,
            self._job_dependent_counts(strict_job.id),
        )

        regular_job = self._create_txt_job_with_unit(
            order_id="regular-delete-order",
            file_id="regular-delete-file",
            user_id="regular-delete-user",
        )
        regular = self.store.delete_job(regular_job.id)

        self.assertIsInstance(regular, DeleteJobResult)
        self.assertTrue(regular.deleted)
        self.assertIsNone(self.store.get_job(regular_job.id))
        self.assertEqual(
            self._job_dependent_counts(regular_job.id),
            {"attempts": 0, "events": 0, "leases": 0, "units": 0},
        )

    def test_schema_rejects_invalid_strict_docx_retention_approval_and_duplicate(self):
        digest = sha256(b"postgres-ddl-synthetic-snapshot").hexdigest()
        with self.assertRaises(CheckViolation):
            self.store.connection.execute(
                """
                INSERT INTO glossary_snapshot_custody (
                    custody_id, snapshot_payload, snapshot_digest,
                    snapshot_schema_version, retention_mode
                ) VALUES (
                    'invalid-retention', %(payload)s, %(digest)s,
                    %(schema)s, 'discard'
                )
                """,
                {
                    "payload": b"postgres-ddl-synthetic-snapshot",
                    "digest": digest,
                    "schema": GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
                },
            )
        self.store.connection.execute(
            """
            INSERT INTO glossary_snapshot_custody (
                custody_id, snapshot_payload, snapshot_digest,
                snapshot_schema_version, retention_mode
            ) VALUES (
                'valid-custody', %(payload)s, %(digest)s, %(schema)s, 'retain'
            )
            """,
            {
                "payload": b"postgres-ddl-synthetic-snapshot",
                "digest": digest,
                "schema": GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
            },
        )
        with self.assertRaises(CheckViolation):
            self.store.connection.execute(
                """
                INSERT INTO glossary_approvals (
                    approval_id, custody_id, snapshot_digest,
                    approval_schema_version, approval_status
                ) VALUES (
                    'invalid-approval', 'valid-custody', %(digest)s,
                    %(schema)s, 'pending'
                )
                """,
                {"digest": digest, "schema": GLOSSARY_APPROVAL_SCHEMA_VERSION},
            )
        self.store.connection.execute(
            """
            INSERT INTO glossary_approvals (
                approval_id, custody_id, snapshot_digest,
                approval_schema_version, approval_status
            ) VALUES (
                'first-approval', 'valid-custody', %(digest)s, %(schema)s, 'approved'
            )
            """,
            {"digest": digest, "schema": GLOSSARY_APPROVAL_SCHEMA_VERSION},
        )
        with self.assertRaises(UniqueViolation):
            self.store.connection.execute(
                """
                INSERT INTO glossary_approvals (
                    approval_id, custody_id, snapshot_digest,
                    approval_schema_version, approval_status
                ) VALUES (
                    'duplicate-approval', 'valid-custody', %(digest)s,
                    %(schema)s, 'revoked'
                )
                """,
                {"digest": digest, "schema": GLOSSARY_APPROVAL_SCHEMA_VERSION},
            )

    def _job_dependent_counts(self, job_id: str) -> dict[str, int]:
        return {
            name: self.store.connection.execute(
                f"SELECT COUNT(*) AS count FROM {table} WHERE job_id = %(job_id)s",
                {"job_id": job_id},
            ).fetchone()["count"]
            for name, table in {
                "attempts": "work_unit_attempts",
                "events": "scheduler_events",
                "leases": "provider_slot_leases",
                "units": "work_units",
            }.items()
        }

    def _claim_txt_job(
        self,
        *,
        order_id="order-1",
        file_id="file-1",
        user_id="telegram:42",
        worker_id="worker-a",
    ):
        job = self._create_txt_job_with_unit(
            order_id=order_id,
            file_id=file_id,
            user_id=user_id,
        )
        claim = self.store.claim_next_scheduled_work_unit(
            worker_id=worker_id,
            lease_seconds=300,
            limits=SchedulerLimits(
                max_active_units_global=10,
                max_active_units_per_job=1,
                max_active_units_per_user=1,
                max_active_jobs_per_user=1,
            ),
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim.job_id, job.id)
        return job, claim

    def _create_txt_job_with_units(
        self,
        *,
        unit_count=3,
        order_id="order-1",
        file_id="file-1",
        user_id="telegram:42",
    ):
        job = self._create_txt_job_with_unit(
            order_id=order_id,
            file_id=file_id,
            user_id=user_id,
        )
        if unit_count <= 1:
            return job
        self.store.add_work_units(
            job.id,
            [
                WorkUnitPlan(
                    sequence=sequence,
                    source_block_ids=(f"txt:{sequence - 1}",),
                    source_text_hash=f"hash-{sequence}",
                    prompt_tier="plain",
                    source_language="en",
                    target_language="uk",
                    source_object_key=f"intermediate/job-1/unit-{sequence}.txt",
                )
                for sequence in range(2, unit_count + 1)
            ],
        )
        return job

    def _insert_large_claim_plan_fixture(self):
        with self.store.connection.transaction():
            self.store.connection.execute(
                """
                INSERT INTO translation_jobs (
                    id, order_id, user_id, file_id, file_name, document_kind,
                    source_object_key, source_language, target_language,
                    adapter_version, prompt_version, pricing_snapshot_id,
                    status, priority, created_at, updated_at
                )
                SELECT
                    'hist-job-' || job_no::text,
                    'order-hist-' || job_no::text,
                    'telegram:hist-' || (job_no %% 50)::text,
                    'file-hist-' || job_no::text,
                    'notes.txt',
                    'txt',
                    'source-hist-' || job_no::text,
                    'en',
                    'uk',
                    %(adapter_version)s,
                    'plain-v1',
                    'pricing-1',
                    'ready',
                    0,
                    now() - (job_no || ' seconds')::interval,
                    now()
                FROM generate_series(1, 260) AS gs(job_no)
                """,
                {"adapter_version": TXT_ADAPTER_VERSION},
            )
            self.store.connection.execute(
                """
                INSERT INTO translation_jobs (
                    id, order_id, user_id, file_id, file_name, document_kind,
                    source_object_key, source_language, target_language,
                    adapter_version, prompt_version, pricing_snapshot_id,
                    status, priority, created_at, updated_at
                )
                SELECT
                    'archive-job-' || job_no::text,
                    'order-archive-' || job_no::text,
                    'telegram:archive-' || (job_no %% 200)::text,
                    'file-archive-' || job_no::text,
                    'notes.txt',
                    'txt',
                    'source-archive-' || job_no::text,
                    'en',
                    'uk',
                    %(adapter_version)s,
                    'plain-v1',
                    'pricing-1',
                    'ready',
                    0,
                    now() - (job_no || ' seconds')::interval,
                    now()
                FROM generate_series(1, 8000) AS gs(job_no)
                """,
                {"adapter_version": TXT_ADAPTER_VERSION},
            )
            self.store.connection.execute(
                """
                INSERT INTO translation_jobs (
                    id, order_id, user_id, file_id, file_name, document_kind,
                    source_object_key, source_language, target_language,
                    adapter_version, prompt_version, pricing_snapshot_id,
                    status, priority, created_at, updated_at
                )
                SELECT
                    'queued-job-' || job_no::text,
                    'order-queued-' || job_no::text,
                    'telegram:queued-' || (job_no %% 80)::text,
                    'file-queued-' || job_no::text,
                    'notes.txt',
                    'txt',
                    'source-queued-' || job_no::text,
                    'en',
                    'uk',
                    %(adapter_version)s,
                    'plain-v1',
                    'pricing-1',
                    'queued',
                    job_no %% 3,
                    now() - (job_no || ' minutes')::interval,
                    now()
                FROM generate_series(1, 120) AS gs(job_no)
                """,
                {"adapter_version": TXT_ADAPTER_VERSION},
            )
            self.store.connection.execute(
                """
                INSERT INTO translation_jobs (
                    id, order_id, user_id, file_id, file_name, document_kind,
                    source_object_key, source_language, target_language,
                    adapter_version, prompt_version, pricing_snapshot_id,
                    status, priority, created_at, updated_at
                )
                SELECT
                    'active-job-' || job_no::text,
                    'order-active-' || job_no::text,
                    'telegram:active-' || job_no::text,
                    'file-active-' || job_no::text,
                    'notes.txt',
                    'txt',
                    'source-active-' || job_no::text,
                    'en',
                    'uk',
                    %(adapter_version)s,
                    'plain-v1',
                    'pricing-1',
                    'translating',
                    0,
                    now() - (job_no || ' minutes')::interval,
                    now()
                FROM generate_series(1, 8) AS gs(job_no)
                """,
                {"adapter_version": TXT_ADAPTER_VERSION},
            )
            self.store.connection.execute(
                """
                INSERT INTO work_units (
                    id, job_id, sequence, source_block_ids_json,
                    source_object_key, source_text_hash, prompt_tier,
                    source_language, target_language, status, translated_text,
                    completed_at
                )
                SELECT
                    'hist-job-' || job_no::text || ':unit-' || unit_no::text,
                    'hist-job-' || job_no::text,
                    unit_no,
                    json_build_array('hist:' || unit_no::text)::text,
                    'source-hist-' || job_no::text || '-' || unit_no::text,
                    'hash-hist-' || job_no::text || '-' || unit_no::text,
                    'plain',
                    'en',
                    'uk',
                    'translated',
                    '[uk] synthetic',
                    now()
                FROM generate_series(1, 260) AS jobs(job_no)
                CROSS JOIN generate_series(1, 80) AS units(unit_no)
                """
            )
            self.store.connection.execute(
                """
                INSERT INTO work_units (
                    id, job_id, sequence, source_block_ids_json,
                    source_object_key, source_text_hash, prompt_tier,
                    source_language, target_language, status
                )
                SELECT
                    'queued-job-' || job_no::text || ':unit-' || unit_no::text,
                    'queued-job-' || job_no::text,
                    unit_no,
                    json_build_array('queued:' || unit_no::text)::text,
                    'source-queued-' || job_no::text || '-' || unit_no::text,
                    'hash-queued-' || job_no::text || '-' || unit_no::text,
                    'plain',
                    'en',
                    'uk',
                    'pending'
                FROM generate_series(1, 120) AS jobs(job_no)
                CROSS JOIN generate_series(1, 70) AS units(unit_no)
                """
            )
            self.store.connection.execute(
                """
                INSERT INTO work_units (
                    id, job_id, sequence, source_block_ids_json,
                    source_object_key, source_text_hash, prompt_tier,
                    source_language, target_language, status, worker_id,
                    claim_token, lease_until, attempt_count, started_at
                )
                SELECT
                    'active-job-' || job_no::text || ':unit-' || unit_no::text,
                    'active-job-' || job_no::text,
                    unit_no,
                    json_build_array('active:' || unit_no::text)::text,
                    'source-active-' || job_no::text || '-' || unit_no::text,
                    'hash-active-' || job_no::text || '-' || unit_no::text,
                    'plain',
                    'en',
                    'uk',
                    CASE WHEN unit_no = 1 THEN 'translating' ELSE 'pending' END,
                    CASE WHEN unit_no = 1 THEN 'worker-active' ELSE NULL END,
                    CASE WHEN unit_no = 1 THEN 'claim-active' ELSE NULL END,
                    CASE
                      WHEN unit_no = 1 THEN now() + interval '5 minutes'
                      ELSE NULL
                    END,
                    CASE WHEN unit_no = 1 THEN 1 ELSE 0 END,
                    CASE WHEN unit_no = 1 THEN now() ELSE NULL END
                FROM generate_series(1, 8) AS jobs(job_no)
                CROSS JOIN generate_series(1, 50) AS units(unit_no)
                """
            )
            self.store.connection.execute("ANALYZE translation_jobs")
            self.store.connection.execute("ANALYZE work_units")

    def test_two_workers_do_not_claim_same_unit(self):
        self._create_txt_job_with_unit()

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_provider_slot_inventory_expands_key_capacity(self):
        slots = self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            max_parallel_requests=2,
            capacity_source="admin",
        )

        self.assertEqual([slot.slot_index for slot in slots], [0, 1])
        self.assertEqual([slot.enabled for slot in slots], [True, True])
        self.assertEqual({slot.capacity_source for slot in slots}, {"admin"})

        reduced = self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            max_parallel_requests=1,
            capacity_source="admin",
        )

        self.assertEqual([slot.slot_index for slot in reduced], [0, 1])
        self.assertEqual([slot.enabled for slot in reduced], [True, False])

    def test_provider_slot_acquire_does_not_double_lease_same_slot(self):
        _, first_claim = self._claim_txt_job(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
            worker_id="worker-a",
        )
        _, second_claim = self._claim_txt_job(
            order_id="order-2",
            file_id="file-2",
            user_id="telegram:100",
            worker_id="worker-b",
        )
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            max_parallel_requests=1,
            capacity_source="admin",
        )

        first_lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            job_id=first_claim.job_id,
            work_unit_id=first_claim.work_unit_id,
            worker_id=first_claim.worker_id,
            work_unit_claim_token=first_claim.claim_token,
            lease_seconds=300,
        )
        second_lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            job_id=second_claim.job_id,
            work_unit_id=second_claim.work_unit_id,
            worker_id=second_claim.worker_id,
            work_unit_claim_token=second_claim.claim_token,
            lease_seconds=300,
        )

        self.assertIsNotNone(first_lease)
        self.assertEqual(first_lease.status, ProviderSlotLeaseStatus.ACTIVE)
        self.assertIsNone(second_lease)

    def test_provider_slot_account_cap_limits_one_key_with_multiple_slots(self):
        _, first_claim = self._claim_txt_job(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
            worker_id="worker-a",
        )
        _, second_claim = self._claim_txt_job(
            order_id="order-2",
            file_id="file-2",
            user_id="telegram:100",
            worker_id="worker-b",
        )
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_shared",
            max_parallel_requests=2,
            capacity_source="admin",
        )
        cap = _provider_capacity_cap(
            cap_id="deepseek-account-shared",
            max_parallel_requests=1,
            channel_ids=("chan_shared",),
        )

        first_lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=first_claim.job_id,
            work_unit_id=first_claim.work_unit_id,
            worker_id=first_claim.worker_id,
            work_unit_claim_token=first_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )
        second_lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=second_claim.job_id,
            work_unit_id=second_claim.work_unit_id,
            worker_id=second_claim.worker_id,
            work_unit_claim_token=second_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )

        self.assertIsNotNone(first_lease)
        self.assertIsNone(second_lease)

    def test_provider_slot_model_cap_limits_one_key_with_multiple_slots(self):
        _, first_claim = self._claim_txt_job(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
            worker_id="worker-a",
        )
        _, second_claim = self._claim_txt_job(
            order_id="order-2",
            file_id="file-2",
            user_id="telegram:100",
            worker_id="worker-b",
        )
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_model",
            max_parallel_requests=2,
            capacity_source="admin",
        )
        cap = _provider_capacity_cap(
            cap_id="deepseek-model-shared",
            scope=ProviderCapacityCapScope.MODEL,
            max_parallel_requests=1,
            channel_ids=("chan_model",),
        )

        first_lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=first_claim.job_id,
            work_unit_id=first_claim.work_unit_id,
            worker_id=first_claim.worker_id,
            work_unit_claim_token=first_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )
        second_lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=second_claim.job_id,
            work_unit_id=second_claim.work_unit_id,
            worker_id=second_claim.worker_id,
            work_unit_claim_token=second_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )

        self.assertIsNotNone(first_lease)
        self.assertIsNone(second_lease)

    def test_provider_slot_account_cap_limits_multiple_keys_in_one_group(self):
        _, first_claim = self._claim_txt_job(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
            worker_id="worker-a",
        )
        _, second_claim = self._claim_txt_job(
            order_id="order-2",
            file_id="file-2",
            user_id="telegram:100",
            worker_id="worker-b",
        )
        for channel_id in ("chan_a", "chan_b"):
            self.store.upsert_provider_slot_inventory(
                provider_id="deepseek",
                channel_id=channel_id,
                max_parallel_requests=1,
                capacity_source="admin",
            )
        cap = _provider_capacity_cap(
            cap_id="deepseek-account-shared",
            max_parallel_requests=1,
            channel_ids=("chan_a", "chan_b"),
        )

        first_lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=first_claim.job_id,
            work_unit_id=first_claim.work_unit_id,
            worker_id=first_claim.worker_id,
            work_unit_claim_token=first_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )
        second_lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=second_claim.job_id,
            work_unit_id=second_claim.work_unit_id,
            worker_id=second_claim.worker_id,
            work_unit_claim_token=second_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )
        self.store.release_provider_slot_lease(
            lease_token=first_lease.lease_token,
            work_unit_claim_token=first_claim.claim_token,
            release_reason="completed",
        )
        second_after_release = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=second_claim.job_id,
            work_unit_id=second_claim.work_unit_id,
            worker_id=second_claim.worker_id,
            work_unit_claim_token=second_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )

        self.assertIsNotNone(first_lease)
        self.assertEqual(first_lease.channel_id, "chan_a")
        self.assertIsNone(second_lease)
        self.assertIsNotNone(second_after_release)

    def test_provider_slot_account_cap_serializes_concurrent_workers(self):
        _, first_claim = self._claim_txt_job(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
            worker_id="worker-a",
        )
        _, second_claim = self._claim_txt_job(
            order_id="order-2",
            file_id="file-2",
            user_id="telegram:100",
            worker_id="worker-b",
        )
        for channel_id in ("chan_a", "chan_b"):
            self.store.upsert_provider_slot_inventory(
                provider_id="deepseek",
                channel_id=channel_id,
                max_parallel_requests=1,
                capacity_source="admin",
            )
        cap = _provider_capacity_cap(
            cap_id="deepseek-account-shared",
            max_parallel_requests=1,
            channel_ids=("chan_a", "chan_b"),
        )
        other_store = PostgresSchedulerStore(POSTGRES_DSN)
        self.addCleanup(other_store.close)
        barrier = threading.Barrier(2)
        results = []

        def acquire(store, claim):
            barrier.wait(timeout=5)
            results.append(
                store.acquire_provider_slot_lease(
                    provider_id="deepseek",
                    job_id=claim.job_id,
                    work_unit_id=claim.work_unit_id,
                    worker_id=claim.worker_id,
                    work_unit_claim_token=claim.claim_token,
                    lease_seconds=300,
                    capacity_caps=[cap],
                )
            )

        first_thread = threading.Thread(target=acquire, args=(self.store, first_claim))
        second_thread = threading.Thread(
            target=acquire,
            args=(other_store, second_claim),
        )
        first_thread.start()
        second_thread.start()
        first_thread.join(timeout=5)
        second_thread.join(timeout=5)

        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(sum(result is None for result in results), 1)

    def test_provider_capacity_diagnostics_show_cap_denied_free_slot(self):
        _, first_claim = self._claim_txt_job(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
            worker_id="worker-a",
        )
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_shared",
            max_parallel_requests=2,
            capacity_source="admin",
        )
        cap = _provider_capacity_cap(
            cap_id="deepseek-account-shared",
            max_parallel_requests=1,
            channel_ids=("chan_shared",),
        )
        self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=first_claim.job_id,
            work_unit_id=first_claim.work_unit_id,
            worker_id=first_claim.worker_id,
            work_unit_claim_token=first_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )

        diagnostic = self.store.get_provider_capacity_diagnostics(
            provider_id="deepseek",
            capacity_caps=[cap],
        )

        self.assertEqual(diagnostic.capacity_state, "cap_denied")
        self.assertEqual(diagnostic.total_slots, 2)
        self.assertEqual(diagnostic.active_leases, 1)
        self.assertEqual(diagnostic.free_slots, 0)
        self.assertEqual(diagnostic.cap_denied_slots, 1)
        self.assertEqual(
            [slot.status for slot in diagnostic.slots],
            [
                ProviderCapacitySlotDiagnosticStatus.LEASED,
                ProviderCapacitySlotDiagnosticStatus.CAP_DENIED,
            ],
        )
        self.assertEqual(diagnostic.caps[0].active_leases, 1)
        self.assertTrue(diagnostic.caps[0].at_limit)

    def test_backpressure_diagnostics_use_durable_queue_and_capacity(self):
        _, first_claim = self._claim_txt_job(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
            worker_id="worker-a",
        )
        self._create_txt_job_with_unit(
            order_id="order-2",
            file_id="file-2",
            user_id="telegram:100",
        )
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_shared",
            max_parallel_requests=2,
            capacity_source="admin",
        )
        cap = _provider_capacity_cap(
            cap_id="deepseek-account-shared",
            max_parallel_requests=1,
            channel_ids=("chan_shared",),
        )
        self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=first_claim.job_id,
            work_unit_id=first_claim.work_unit_id,
            worker_id=first_claim.worker_id,
            work_unit_claim_token=first_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )

        diagnostics = self.store.get_scheduler_backpressure_diagnostics(
            provider_id="deepseek",
            capacity_caps=[cap],
        )

        self.assertEqual(
            diagnostics.backpressure_state,
            SchedulerBackpressureState.CAP_PRESSURE,
        )
        self.assertEqual(diagnostics.queue_depth_units, 1)
        self.assertEqual(diagnostics.eligible_waiting_units, 1)
        self.assertEqual(diagnostics.active_work_units, 1)
        self.assertEqual(diagnostics.provider_active_leases, 1)
        self.assertEqual(diagnostics.provider_cap_denied_slots, 1)
        self.assertIn("account_model_cap_pressure", diagnostics.pressure_reasons)

    def test_provider_slot_release_is_claim_scoped_and_idempotent(self):
        _, claim = self._claim_txt_job()
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            max_parallel_requests=1,
            capacity_source="admin",
        )
        lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            job_id=claim.job_id,
            work_unit_id=claim.work_unit_id,
            worker_id=claim.worker_id,
            work_unit_claim_token=claim.claim_token,
            lease_seconds=300,
        )

        wrong_claim_release = self.store.release_provider_slot_lease(
            lease_token=lease.lease_token,
            work_unit_claim_token="wrong-claim-token",
            release_reason="completed",
        )
        first_release = self.store.release_provider_slot_lease(
            lease_token=lease.lease_token,
            work_unit_claim_token=claim.claim_token,
            release_reason="completed",
        )
        second_release = self.store.release_provider_slot_lease(
            lease_token=lease.lease_token,
            work_unit_claim_token=claim.claim_token,
            release_reason="raw unsafe text should not persist",
        )

        self.assertIsNone(wrong_claim_release)
        self.assertEqual(first_release.status, ProviderSlotLeaseStatus.RELEASED)
        self.assertEqual(first_release.release_reason, "completed")
        self.assertEqual(second_release.status, ProviderSlotLeaseStatus.RELEASED)
        self.assertEqual(second_release.release_reason, "completed")

    def test_provider_slot_expiry_does_not_recover_active_work_unit_claim(self):
        _, claim = self._claim_txt_job()
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            max_parallel_requests=1,
            capacity_source="admin",
        )
        lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            job_id=claim.job_id,
            work_unit_id=claim.work_unit_id,
            worker_id=claim.worker_id,
            work_unit_claim_token=claim.claim_token,
            lease_seconds=1,
        )

        recovered = self.store.recover_expired_provider_slot_leases(
            now=lease.lease_until + timedelta(seconds=1),
        )
        active = self.store.list_provider_slot_leases(
            status=ProviderSlotLeaseStatus.ACTIVE,
        )
        work_unit = self.store.get_work_unit(claim.work_unit_id)

        self.assertEqual(recovered, 0)
        self.assertEqual([item.lease_token for item in active], [lease.lease_token])
        self.assertEqual(work_unit.status.value, "translating")
        self.assertEqual(work_unit.claim_token, claim.claim_token)

    def test_provider_capacity_diagnostics_show_expired_active_lease(self):
        _, claim = self._claim_txt_job()
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            max_parallel_requests=1,
            capacity_source="admin",
        )
        lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            job_id=claim.job_id,
            work_unit_id=claim.work_unit_id,
            worker_id=claim.worker_id,
            work_unit_claim_token=claim.claim_token,
            lease_seconds=1,
        )

        diagnostic = self.store.get_provider_capacity_diagnostics(
            provider_id="deepseek",
            now=lease.lease_until + timedelta(seconds=1),
        )

        self.assertEqual(diagnostic.capacity_state, "recovering_expired_leases")
        self.assertEqual(diagnostic.expired_active_leases, 1)
        self.assertEqual(
            diagnostic.slots[0].status,
            ProviderCapacitySlotDiagnosticStatus.EXPIRED_ACTIVE,
        )

    def test_provider_slot_expiry_recovers_after_work_unit_lease_is_stale(self):
        _, claim = self._claim_txt_job()
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            max_parallel_requests=1,
            capacity_source="admin",
        )
        lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            job_id=claim.job_id,
            work_unit_id=claim.work_unit_id,
            worker_id=claim.worker_id,
            work_unit_claim_token=claim.claim_token,
            lease_seconds=1,
        )

        recovered = self.store.recover_expired_provider_slot_leases(
            now=claim.lease_until + timedelta(seconds=1),
        )
        [expired] = self.store.list_provider_slot_leases(
            status=ProviderSlotLeaseStatus.EXPIRED,
        )

        self.assertEqual(recovered, 1)
        self.assertEqual(expired.lease_token, lease.lease_token)
        self.assertEqual(expired.release_reason, "lease_expired")

    def test_delete_job_removes_provider_slot_leases_first(self):
        job, claim = self._claim_txt_job()
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            max_parallel_requests=1,
            capacity_source="admin",
        )
        self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            job_id=claim.job_id,
            work_unit_id=claim.work_unit_id,
            worker_id=claim.worker_id,
            work_unit_claim_token=claim.claim_token,
            lease_seconds=300,
        )

        deleted = self.store.delete_job(job.id)

        self.assertTrue(deleted)
        self.assertEqual(self.store.list_provider_slot_leases(), [])
        self.assertIsNone(self.store.get_job(job.id))

    def test_provider_slot_lease_schema_has_safe_metadata_columns(self):
        columns = {
            row["column_name"]
            for row in self.store.connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'provider_slot_leases'
                """
            ).fetchall()
        }

        self.assertIn("lease_token", columns)
        self.assertIn("work_unit_claim_token", columns)
        self.assertNotIn("api_key", columns)
        self.assertNotIn("source_text", columns)
        self.assertNotIn("translated_text", columns)
        self.assertNotIn("prompt", columns)
        self.assertNotIn("provider_payload", columns)
        self.assertNotIn("stack_trace", columns)

    def test_defer_claimed_unit_for_provider_capacity_returns_pending_without_attempt(
        self,
    ):
        _, claim = self._claim_txt_job()

        deferred = self.store.defer_claimed_work_unit_for_provider_capacity(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
        )

        attempts = self.store.list_work_unit_attempts(claim.work_unit_id)
        events = self.store.list_scheduler_events(claim.job_id)
        next_claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        self.assertIsNotNone(deferred)
        self.assertEqual(deferred.status.value, "pending")
        self.assertIsNone(deferred.worker_id)
        self.assertIsNone(deferred.claim_token)
        self.assertIsNone(deferred.lease_until)
        self.assertEqual(deferred.attempt_count, 0)
        self.assertEqual(attempts, [])
        self.assertEqual(
            events[-1].event_type,
            "work_unit_provider_capacity_deferred",
        )
        self.assertEqual(next_claim.work_unit_id, claim.work_unit_id)

    def test_per_job_limit_of_one_preserves_unit_ordering(self):
        job = self._create_txt_job_with_units()

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(max_active_units_per_job=1),
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(max_active_units_per_job=1),
        )

        self.assertEqual(first.work_unit_id, f"{job.id}:unit-1")
        self.assertIsNone(second)

    def test_per_job_limit_allows_later_units_up_to_limit(self):
        job = self._create_txt_job_with_units()
        limits = SchedulerLimits(
            max_active_units_per_job=2,
            max_active_units_per_user=2,
            max_active_units_global=10,
        )

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )
        third = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-c",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.work_unit_id, f"{job.id}:unit-1")
        self.assertEqual(second.work_unit_id, f"{job.id}:unit-2")
        self.assertIsNone(third)

    def test_single_user_job_can_claim_up_to_eight_units_when_capacity_is_free(self):
        job = self._create_txt_job_with_units(unit_count=9)
        limits = SchedulerLimits(
            max_active_units_global=16,
            max_active_units_per_job=8,
            max_active_units_per_user=8,
            max_active_jobs_per_user=1,
        )

        claims = [
            self.store.claim_next_scheduled_work_unit(
                worker_id=f"worker-{index}",
                lease_seconds=300,
                limits=limits,
            )
            for index in range(1, 10)
        ]

        self.assertEqual(
            [claim.work_unit_id for claim in claims[:8]],
            [f"{job.id}:unit-{sequence}" for sequence in range(1, 9)],
        )
        self.assertIsNone(claims[8])

    def test_global_limit_blocks_second_job_sequentially(self):
        first_job = self._create_txt_job_with_unit(order_id="order-1", file_id="file-1")
        self._create_txt_job_with_unit(order_id="order-2", file_id="file-2")
        limits = SchedulerLimits(max_active_units_global=1)

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.job_id, first_job.id)
        self.assertIsNone(second)

    def test_user_unit_cap_blocks_second_job_for_same_user(self):
        first_job = self._create_txt_job_with_unit(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
        )
        self._create_txt_job_with_unit(
            order_id="order-2",
            file_id="file-2",
            user_id="telegram:42",
        )
        limits = SchedulerLimits(
            max_active_units_global=10,
            max_active_units_per_job=1,
            max_active_units_per_user=1,
            max_active_jobs_per_user=2,
        )

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.job_id, first_job.id)
        self.assertIsNone(second)

    def test_claim_prefers_user_with_lower_active_load(self):
        first_user_first_job = self._create_txt_job_with_unit(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
        )
        self._create_txt_job_with_unit(
            order_id="order-2",
            file_id="file-2",
            user_id="telegram:42",
        )
        other_user_job = self._create_txt_job_with_unit(
            order_id="order-3",
            file_id="file-3",
            user_id="telegram:100",
        )
        limits = SchedulerLimits(
            max_active_units_global=10,
            max_active_units_per_job=1,
            max_active_units_per_user=2,
            max_active_jobs_per_user=2,
        )

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.job_id, first_user_first_job.id)
        self.assertEqual(second.job_id, other_user_job.id)

    def test_claim_fair_queue_prevents_large_job_from_monopolizing_slots(self):
        large_job = self._create_txt_job_with_units(
            order_id="order-large",
            file_id="file-large",
            user_id="telegram:42",
            unit_count=4,
        )
        small_a = self._create_txt_job_with_units(
            order_id="order-small-a",
            file_id="file-small-a",
            user_id="telegram:100",
            unit_count=1,
        )
        small_b = self._create_txt_job_with_units(
            order_id="order-small-b",
            file_id="file-small-b",
            user_id="telegram:200",
            unit_count=1,
        )
        limits = SchedulerLimits(
            max_active_units_global=3,
            max_active_units_per_job=3,
            max_active_units_per_user=3,
            max_active_jobs_per_user=3,
        )

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )
        third = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-c",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.job_id, large_job.id)
        self.assertEqual({second.job_id, third.job_id}, {small_a.id, small_b.id})
        self.assertNotIn(large_job.id, {second.job_id, third.job_id})

    def test_claim_fair_queue_allows_same_user_rotation_when_caps_allow(self):
        first_job = self._create_txt_job_with_units(
            order_id="order-same-user-a",
            file_id="file-same-user-a",
            user_id="telegram:42",
            unit_count=2,
        )
        second_job = self._create_txt_job_with_units(
            order_id="order-same-user-b",
            file_id="file-same-user-b",
            user_id="telegram:42",
            unit_count=1,
        )
        limits = SchedulerLimits(
            max_active_units_global=2,
            max_active_units_per_job=1,
            max_active_units_per_user=2,
            max_active_jobs_per_user=2,
        )

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.job_id, first_job.id)
        self.assertEqual(second.job_id, second_job.id)
        second_events = self.store.list_scheduler_events(second_job.id)
        second_payload = json.loads(second_events[-1].payload_json)
        diagnostics = second_payload["queue_policy_diagnostics"]
        self.assertEqual(diagnostics["active_user_units_before_claim"], 1)
        self.assertEqual(diagnostics["active_user_jobs_before_claim"], 1)
        self.assertEqual(diagnostics["active_job_units_before_claim"], 0)

    def test_claim_user_job_cap_still_allows_more_units_from_active_job(self):
        active_job = self._create_txt_job_with_units(
            order_id="order-active-user-a",
            file_id="file-active-user-a",
            user_id="telegram:42",
            unit_count=2,
        )
        blocked_job = self._create_txt_job_with_units(
            order_id="order-active-user-b",
            file_id="file-active-user-b",
            user_id="telegram:42",
            unit_count=1,
        )
        limits = SchedulerLimits(
            max_active_units_global=2,
            max_active_units_per_job=2,
            max_active_units_per_user=2,
            max_active_jobs_per_user=1,
        )

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.job_id, active_job.id)
        self.assertEqual(second.job_id, active_job.id)
        self.assertEqual(second.work_unit_id, f"{active_job.id}:unit-2")
        self.assertNotEqual(second.job_id, blocked_job.id)

    def test_claim_query_plan_uses_scheduler_indexes_for_large_tables(self):
        create_postgres_scheduler_claim_performance_indexes(
            self.store.connection,
            concurrently=False,
        )
        self._insert_large_claim_plan_fixture()

        work_unit_count = self.store.connection.execute(
            "SELECT COUNT(*) AS count FROM work_units"
        ).fetchone()["count"]
        self.assertGreaterEqual(work_unit_count, 29000)

        with self.store.connection.transaction():
            plan_row = self.store.connection.execute(
                "EXPLAIN (FORMAT JSON) " + _CLAIM_NEXT_SCHEDULED_WORK_UNIT_SQL,
                {
                    "worker_id": "worker-plan",
                    "claim_token": "claim-plan",
                    "claim_lock_key": "translator_service.postgres_scheduler.claim",
                    "lease_seconds": 300,
                    "max_active_units_global": 10,
                    "max_active_units_per_job": 2,
                    "max_active_units_per_user": 2,
                    "max_active_jobs_per_user": 2,
                    "priority_aging_seconds": 0,
                },
            ).fetchone()

        plan = plan_row["QUERY PLAN"]
        if isinstance(plan, str):
            plan = json.loads(plan)
        nodes = list(_flatten_plan_nodes(plan[0]["Plan"]))
        work_unit_seq_scans = [
            node
            for node in nodes
            if node.get("Node Type") == "Seq Scan"
            and node.get("Relation Name") == "work_units"
        ]
        index_names = {
            node.get("Index Name")
            for node in nodes
            if node.get("Index Name") is not None
        }

        self.assertEqual(work_unit_seq_scans, [])
        self.assertIn("translation_jobs_scheduler_claim_idx", index_names)
        self.assertIn("work_units_scheduler_waiting_order_idx", index_names)
        self.assertIn("work_units_scheduler_active_job_idx", index_names)

    def test_claim_priority_aging_prevents_old_job_starvation(self):
        old_low_priority = self._create_txt_job_with_unit(
            order_id="order-old",
            file_id="file-old",
            user_id="telegram:42",
        )
        new_high_priority = self._create_txt_job_with_unit(
            order_id="order-new",
            file_id="file-new",
            user_id="telegram:100",
        )
        now = datetime.now(UTC)
        with self.store.connection.transaction():
            self.store.connection.execute(
                """
                UPDATE translation_jobs
                SET priority = %(priority)s, created_at = %(created_at)s
                WHERE id = %(job_id)s
                """,
                {
                    "priority": 0,
                    "created_at": now - timedelta(minutes=3),
                    "job_id": old_low_priority.id,
                },
            )
            self.store.connection.execute(
                """
                UPDATE translation_jobs
                SET priority = %(priority)s, created_at = %(created_at)s
                WHERE id = %(job_id)s
                """,
                {
                    "priority": 1,
                    "created_at": now,
                    "job_id": new_high_priority.id,
                },
            )

        claimed = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(
                max_active_units_global=10,
                max_active_units_per_job=1,
                max_active_units_per_user=1,
                max_active_jobs_per_user=1,
                priority_aging_seconds=60,
            ),
        )

        self.assertEqual(claimed.job_id, old_low_priority.id)

    def test_legacy_failed_unit_is_retryable_for_claiming(self):
        job = self._create_txt_job_with_unit()
        with self.store.connection.transaction():
            self.store.connection.execute(
                """
                UPDATE work_units
                SET status = 'failed', available_at = now() - interval '1 second'
                WHERE id = %(work_unit_id)s
                """,
                {"work_unit_id": f"{job.id}:unit-1"},
            )

        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        self.assertIsNotNone(claim)
        self.assertEqual(claim.work_unit_id, f"{job.id}:unit-1")

    def test_complete_claimed_unit_moves_job_to_assembling(self):
        job = self._create_txt_job_with_unit()
        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        completed = self.store.complete_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            translated_text="[uk] First paragraph",
            prompt_tokens=10,
            completion_tokens=5,
            cache_hit_tokens=1,
            cache_miss_tokens=9,
        )

        persisted_job = self.store.get_job(job.id)
        events = self.store.list_scheduler_events(job.id)
        claim_payload = json.loads(events[0].payload_json)
        self.assertEqual(completed.status.value, "translated")
        self.assertEqual(
            persisted_job.status,
            PersistentTranslationJobStatus.ASSEMBLING,
        )
        self.assertEqual(
            claim_payload["queue_policy"],
            SCHEDULER_FAIR_QUEUE_POLICY,
        )
        diagnostics = claim_payload["queue_policy_diagnostics"]
        self.assertEqual(diagnostics["active_user_units_before_claim"], 0)
        self.assertEqual(diagnostics["active_user_jobs_before_claim"], 0)
        self.assertEqual(diagnostics["active_job_units_before_claim"], 0)
        self.assertEqual(diagnostics["max_active_units_per_job"], 1)
        self.assertEqual(diagnostics["max_active_units_per_user"], 1)
        self.assertEqual(diagnostics["max_active_jobs_per_user"], 1)
        self.assertEqual(events[-1].event_type, "work_unit_completed")

    def test_retryable_failure_records_attempt_and_releases_claim(self):
        job = self._create_txt_job_with_unit()
        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        failed = self.store.fail_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message="provider timeout",
            retry_base_delay_seconds=30,
            retry_max_delay_seconds=600,
        )

        attempts = self.store.list_work_unit_attempts(claim.work_unit_id)
        events = self.store.list_scheduler_events(job.id)
        self.assertEqual(failed.status.value, "failed_retryable")
        self.assertIsNone(failed.claim_token)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(events[-1].event_type, "work_unit_retry_scheduled")

    def test_provider_failure_diagnostic_is_persisted_on_attempt_and_event(self):
        job = self._create_txt_job_with_unit()
        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        self.store.fail_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message="retryable provider failure",
            retry_base_delay_seconds=30,
            retry_max_delay_seconds=600,
            provider_failure_diagnostic=ProviderFailureDiagnostic(
                failure_category=ProviderFailureCategory.AUTH,
                http_status_bucket="4xx",
                provider_id="deepseek",
                channel_fingerprint="chan_abcdef123456",
            ),
        )

        attempts = self.store.list_work_unit_attempts(claim.work_unit_id)
        events = self.store.list_scheduler_events(job.id)
        payload = json.loads(events[-1].payload_json)

        self.assertEqual(attempts[0].error_code, "auth")
        self.assertEqual(attempts[0].error_message, "provider failure: auth")
        self.assertEqual(payload["provider_failure"]["failure_category"], "auth")
        self.assertEqual(payload["provider_failure"]["http_status_bucket"], "4xx")

    def test_stale_completion_with_wrong_token_leaves_claim_intact(self):
        self._create_txt_job_with_unit()
        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        with self.assertRaises(ValueError):
            self.store.complete_claimed_work_unit(
                work_unit_id=claim.work_unit_id,
                claim_token="wrong-token",
                translated_text="[uk] stale",
                prompt_tokens=1,
                completion_tokens=1,
                cache_hit_tokens=0,
                cache_miss_tokens=1,
            )

        work_unit = self.store.get_work_unit(claim.work_unit_id)
        self.assertEqual(work_unit.claim_token, claim.claim_token)
        self.assertEqual(work_unit.status.value, "translating")

    def test_worker_heartbeat_is_upserted(self):
        self.store.record_worker_heartbeat(
            worker_id="worker-a",
            worker_kind="translation",
            status="idle",
            active_job_id=None,
            active_work_unit_id=None,
        )
        self.store.record_worker_heartbeat(
            worker_id="worker-a",
            worker_kind="translation",
            status="busy",
            active_job_id="job-1",
            active_work_unit_id="job-1:unit-1",
        )

        heartbeat = self.store.get_worker_heartbeat("worker-a")

        self.assertEqual(heartbeat.worker_id, "worker-a")
        self.assertEqual(heartbeat.status, "busy")
        self.assertEqual(heartbeat.active_job_id, "job-1")

    def test_scheduler_runner_translates_and_assembles_txt_job(self):
        from translator_service.scheduler_runner import run_scheduler_once

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="notes.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            job = self.store.create_job(
                order_id="order-runtime-smoke",
                user_id="telegram:42",
                file_id="file-runtime-smoke",
                file_name="notes.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version=TXT_ADAPTER_VERSION,
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=original.object_key,
            )
            self.store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:segment:1",),
                        source_text_hash="hash-runtime-smoke",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=source.object_key,
                    )
                ],
            )
            translator = PostgresSmokeTranslator()

            summary = run_scheduler_once(
                store=self.store,
                storage=storage,
                worker_id="postgres-smoke-worker",
                translator=translator,
                limits=SchedulerLimits(),
                lease_seconds=300,
            )

            persisted_job = self.store.get_job(job.id)
            events = self.store.list_scheduler_events(job.id)
            leases = self.store.list_provider_slot_leases()
            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(summary.assembled_jobs, 1)
            self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.READY)
            self.assertIsNotNone(persisted_job.final_object_key)
            self.assertEqual(
                storage.get_bytes(persisted_job.final_object_key).decode("utf-8"),
                "[uk] First paragraph",
            )
            self.assertEqual(
                [event.event_type for event in events],
                ["work_unit_claimed", "work_unit_completed"],
            )
            self.assertEqual(len(leases), 1)
            self.assertEqual(leases[0].status, ProviderSlotLeaseStatus.RELEASED)
            self.assertEqual(leases[0].release_reason, "completed")
            self.assertEqual(translator.channel_contexts, ["deepseek-channel-1"])


class PostgresSmokeTranslator:
    provider_id = "deepseek"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.last_usage: _ProviderUsage | None = None
        self.channel_contexts: list[str] = []

    def provider_slot_inventory(self) -> list[ProviderSlotInventoryItem]:
        return [
            ProviderSlotInventoryItem(
                provider_id="deepseek",
                channel_id="deepseek-channel-1",
                max_parallel_requests=1,
                capacity_source="test",
            )
        ]

    def provider_slot_channel_lease(self, channel_id: str):
        class _Context:
            def __enter__(inner_self):
                self.channel_contexts.append(channel_id)

            def __exit__(inner_self, exc_type, exc_value, traceback):
                return False

        return _Context()

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
        translation_context=None,
    ) -> str:
        self.calls.append((text, source_language, target_language))
        self.last_usage = _ProviderUsage(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            prompt_cache_hit_tokens=2,
            prompt_cache_miss_tokens=8,
        )
        return f"[{target_language}] {text}"


def _flatten_plan_nodes(plan_node):
    yield plan_node
    for child in plan_node.get("Plans", []):
        yield from _flatten_plan_nodes(child)


def _provider_capacity_cap(
    *,
    cap_id: str,
    max_parallel_requests: int,
    channel_ids: tuple[str, ...],
    scope: ProviderCapacityCapScope = ProviderCapacityCapScope.ACCOUNT,
) -> ProviderCapacityCap:
    return ProviderCapacityCap(
        provider_id="deepseek",
        cap_id=cap_id,
        scope=scope,
        max_parallel_requests=max_parallel_requests,
        channel_ids=channel_ids,
    )


class _ProviderUsage:
    def __init__(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        prompt_cache_hit_tokens: int,
        prompt_cache_miss_tokens: int,
    ) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.prompt_cache_hit_tokens = prompt_cache_hit_tokens
        self.prompt_cache_miss_tokens = prompt_cache_miss_tokens


if __name__ == "__main__":
    unittest.main()
